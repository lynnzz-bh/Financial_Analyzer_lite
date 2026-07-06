"""本模块覆盖项目最基础的纯 Python 逻辑，包括日期校验、元单位换算、指标计算、风险红旗和评分可信度，避免依赖外部接口。"""

from datetime import date
import json
import sys
import pandas as pd
import pytest
import main as main_module
from main import cleanup_old_output_files
from src.anti_dependency import anti_dependency_mode
from src.data_cleaner.financial_cleaner import build_financial_cleaning_audit, normalize_financial_dataframe, normalize_money_to_yuan
from src.data_fetcher import akshare_fetcher
from src.data_fetcher.akshare_fetcher import to_eastmoney_symbol
from src.data_fetcher.astock_data_provider import (
    market_prefix,
    normalize_stock_code,
    parse_eastmoney_fund_flow_klines,
    parse_tencent_quote_payload,
)
from src.data_fetcher.business_fetcher import build_business_context
from src.data_fetcher.market_fetcher import _map_market_row
from src.factors.financial_factors import compute_financial_factors, enrich_market_data_with_report_valuations
from src.factors.metric_registry import META_FACTOR_KEYS, build_metric_provenance, registered_metric_names
from src.llm import llm_pipeline
from src.factors.risk_flags import generate_risk_flags
from src.report import report_generator
from src.scoring.financial_score import score_financials
from src.utils.data_quality import inspect_business_context_quality, inspect_cleaned_reports_quality, inspect_raw_fetch_quality, summarize_quality_status
from src.utils.date_utils import parse_analysis_date, validate_stock_code


def test_date_and_code_validation() -> None:
    assert parse_analysis_date("2026-06-24") == date(2026, 6, 24)
    assert validate_stock_code("600519") == "600519"
    assert validate_stock_code("000001") == "000001"
    assert validate_stock_code("002415") == "002415"
    assert normalize_stock_code("SH600519") == "600519"
    assert normalize_stock_code("000001.SZ") == "000001"
    assert market_prefix("600519") == "sh"
    assert market_prefix("000001") == "sz"
    assert to_eastmoney_symbol("600519") == "SH600519"
    assert to_eastmoney_symbol("000001") == "SZ000001"
    assert to_eastmoney_symbol("830799") == "BJ830799"
    with pytest.raises(ValueError):
        validate_stock_code("abc")
    for unsupported_code in ("300750", "688981", "830799", "400001"):
        with pytest.raises(ValueError, match="当前仅支持 A 股主板普通股票"):
            validate_stock_code(unsupported_code)
    with pytest.raises(ValueError):
        normalize_stock_code("abc")


def test_astock_tencent_payload_parser() -> None:
    vals = [""] * 60
    vals[1] = "贵州茅台"
    vals[2] = "600519"
    vals[3] = "1700.00"
    vals[4] = "1690.00"
    vals[5] = "1688.00"
    vals[31] = "10.00"
    vals[32] = "0.59"
    vals[33] = "1710.00"
    vals[34] = "1680.00"
    vals[37] = "123456.78"
    vals[38] = "0.50"
    vals[39] = "25.60"
    vals[43] = "1.80"
    vals[44] = "21000.00"
    vals[45] = "21000.00"
    vals[46] = "8.80"
    vals[47] = "1859.00"
    vals[48] = "1521.00"
    vals[49] = "1.20"
    vals[52] = "26.10"
    parsed = parse_tencent_quote_payload(f'v_sh600519="{"~".join(vals)}";')
    quote = parsed["600519"]
    assert quote["股票简称"] == "贵州茅台"
    assert quote["最新价"] == 1700.0
    assert quote["PE TTM"] == 25.6
    assert quote["PB"] == 8.8


def test_push2_stock_info_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": {
                    "f57": "600519",
                    "f58": "贵州茅台",
                    "f84": 1256197800,
                    "f85": 1256197800,
                    "f116": 1500000000000,
                    "f117": 1500000000000,
                    "f127": "白酒",
                    "f189": 20010827,
                    "f43": 1182.18,
                }
            }

    def fake_get(url: str, params: dict, timeout: int) -> FakeResponse:
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(akshare_fetcher.requests, "get", fake_get)
    info = akshare_fetcher._fetch_stock_info_from_push2("600519")
    assert captured["params"]["secid"] == "1.600519"
    assert info["股票代码"] == "600519"
    assert info["股票简称"] == "贵州茅台"
    assert info["行业"] == "白酒"


def test_astock_fund_flow_parser() -> None:
    rows = parse_eastmoney_fund_flow_klines([
        "2026-06-24,1000,-200,300,400,500,1,2",
        "bad,row",
        "2026-06-25,-,-,-,-,-",
    ])
    assert rows[0]["date"] == "2026-06-24"
    assert rows[0]["main_net"] == 1000
    assert rows[1]["main_net"] is None


def test_market_row_keeps_source_valuation_fields_separate_from_project_metrics() -> None:
    market = _map_market_row({"名称": "四方股份", "最新价": 58, "总市值": 48320119000, "市盈率-动态": 44.63, "PEG": 3.47, "市净率": 10.57, "市销率": 6.2}, "601126")
    assert market["PE 动态"] == 44.63
    assert market["PE TTM"] is None
    assert market["行情源PEG"] == 3.47
    assert market["PB 行情源"] == 10.57
    assert market["PB"] is None
    assert market["行情源PS"] == 6.2
    assert market["PS"] is None


def test_money_normalized_to_yuan() -> None:
    assert normalize_money_to_yuan("1亿元") == 100000000
    assert normalize_money_to_yuan("300万元") == 3000000
    assert normalize_money_to_yuan(10000) == 10000
    assert normalize_money_to_yuan("-") is None


def test_financial_cleaning_audit_maps_raw_aliases_without_changing_cleaning() -> None:
    audit = build_financial_cleaning_audit({
        "income_statement": pd.DataFrame([{"TOTAL_OPERATE_INCOME": "1亿元", "REPORT_DATE": "2025-12-31"}]),
        "balance_sheet": pd.DataFrame([{"TOTAL_ASSETS": 100}]),
        "cash_flow": pd.DataFrame(),
    })
    revenue = audit["income_statement"]["field_mappings"]["营业收入"]
    missing_cost = audit["income_statement"]["field_mappings"]["营业成本"]
    assert revenue["aliases"] == ["营业收入", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME"]
    assert revenue["source_field"] == "TOTAL_OPERATE_INCOME"
    assert revenue["status"] == "ok"
    assert revenue["target_unit"] == "元"
    assert revenue["conversion"] == "normalize_money_to_yuan"
    assert missing_cost["status"] == "missing"
    assert audit["income_statement"]["date_mappings"]["report_period"]["source_field"] == "REPORT_DATE"
    assert audit["cash_flow"]["status"] == "missing"


def test_cleaner_filters_future_publish_date() -> None:
    df = pd.DataFrame([
        {"REPORT_DATE": "2024-12-31", "NOTICE_DATE": "2025-04-01", "TOTAL_OPERATE_INCOME": 10000},
        {"REPORT_DATE": "2025-12-31", "NOTICE_DATE": "2026-07-01", "TOTAL_OPERATE_INCOME": 20000},
    ])
    cleaned = normalize_financial_dataframe(df, date(2026, 6, 24))
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["营业收入"] == 10000


def test_data_quality_warnings_for_empty_fetches() -> None:
    raw_warnings = inspect_raw_fetch_quality(
        {"股票代码": "600519", "error": "stock_individual_info_em 返回空数据"},
        {"股票代码": "600519"},
        {
            "income_statement": pd.DataFrame(),
            "balance_sheet": pd.DataFrame(),
            "cash_flow": pd.DataFrame(),
        },
    )
    assert any(item["source"] == "stock_info" for item in raw_warnings)
    assert any(item["source"] == "income_statement" for item in raw_warnings)
    assert any(item["source"] == "market_data" for item in raw_warnings)
    assert any(item["level"] == "fatal" and item["source"] == "financial_reports" for item in raw_warnings)
    assert summarize_quality_status(raw_warnings) == "fatal"

    cleaned_warnings = inspect_cleaned_reports_quality({
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
    })
    assert len(cleaned_warnings) == 4
    assert summarize_quality_status(cleaned_warnings) == "fatal"


def test_data_quality_warning_for_missing_disclosure_date() -> None:
    warnings = inspect_cleaned_reports_quality({
        "income_statement": [{"report_period": "2025A", "publish_date": None, "营业收入": 100}],
        "balance_sheet": [{"report_period": "2025A", "publish_date": "2026-04-01", "总资产": 300}],
        "cash_flow": [{"report_period": "2025A", "publish_date": "2026-04-01", "经营活动现金流净额": 20}],
    })
    assert any(item["level"] == "warning" and "披露日期未知" in item["message"] for item in warnings)
    assert summarize_quality_status(warnings) == "warning"


def test_data_quality_status_ok_without_warnings() -> None:
    assert summarize_quality_status([]) == "ok"


def test_raw_fetch_quality_accepts_source_valuation_fields_after_caliber_split() -> None:
    warnings = inspect_raw_fetch_quality(
        {"股票代码": "601126", "股票简称": "四方股份"},
        {
            "股票代码": "601126",
            "股票简称": "四方股份",
            "最新收盘价": 61.6,
            "总市值": 51319298800.0,
            "PE 动态": 47.4,
            "PE TTM": None,
            "行情源PEG": 3.47,
            "PB 行情源": 11.23,
            "PB": None,
            "行情源PS": 7.5,
        },
        {
            "income_statement": pd.DataFrame([{"营业收入": 1}]),
            "balance_sheet": pd.DataFrame([{"总资产": 1}]),
            "cash_flow": pd.DataFrame([{"经营活动现金流净额": 1}]),
        },
    )

    assert warnings == []


def test_business_context_builds_latest_composition_and_sw_industry() -> None:
    profile = pd.DataFrame([
        {"公司名称": "富士康工业互联网股份有限公司", "所属行业": "计算机、通信和其他电子设备制造业", "主营业务": "各类电子设备产品的设计、研发、制造与销售业务。", "经营范围": "工业互联网技术研发。"}
    ])
    composition = pd.DataFrame([
        {"报告日期": "2024-12-31", "分类类型": "按行业分类", "主营构成": "旧业务", "主营收入": 100, "收入比例": 1.0, "毛利率": 0.1},
        {"报告日期": "2025-12-31", "分类类型": "按行业分类", "主营构成": "云计算", "主营收入": 602678703000, "收入比例": 0.667502, "毛利率": 0.0573},
        {"报告日期": "2025-12-31", "分类类型": "按行业分类", "主营构成": "通信及移动网络设备", "主营收入": 297851348000, "收入比例": 0.329888, "毛利率": 0.092836},
        {"报告日期": "2025-12-31", "分类类型": "按产品分类", "主营构成": "3C电子产品", "主营收入": 901224002000, "收入比例": 0.998158, "毛利率": 0.069357},
        {"报告日期": "2025-12-31", "分类类型": "按地区分类", "主营构成": "中国大陆及其他", "主营收入": 504808399000, "收入比例": 0.559105},
    ])
    industry_change = pd.DataFrame([
        {"分类标准": "申银万国行业分类标准(旧)", "行业门类": "电子", "行业次类": "电子制造", "行业大类": "电子系统组装", "行业中类": "电子系统组装", "行业编码": "S270501", "变更日期": "2018-05-28"},
        {"分类标准": "申银万国行业分类标准", "行业门类": "电子", "行业次类": "消费电子", "行业大类": "消费电子零部件及组装", "行业中类": "消费电子零部件及组装", "行业编码": "S270504", "变更日期": "2021-07-30"},
    ])
    context = build_business_context({
        "company_profile": profile,
        "business_composition": composition,
        "industry_change": industry_change,
    })
    assert context["company_profile"]["main_business"].startswith("各类电子设备")
    assert context["business_composition"]["report_date"] == "2025-12-31"
    assert context["business_composition"]["by_industry"][0]["name"] == "云计算"
    assert context["business_composition"]["by_product"][0]["name"] == "3C电子产品"
    assert context["business_composition"]["by_region"][0]["name"] == "中国大陆及其他"
    assert context["sw_industry"]["standard"] == "申银万国行业分类标准"
    assert context["sw_industry"]["sub_industry"] == "消费电子零部件及组装"


def test_business_context_missing_data_is_info_only() -> None:
    items = inspect_business_context_quality({"company_profile": {}, "sw_industry": {}, "business_composition": {"by_industry": [], "by_product": []}})
    assert {item["level"] for item in items} == {"info"}
    assert summarize_quality_status(items) == "ok"


def test_failure_report_omits_score_rating_and_trade_meaning(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_generator, "OUTPUT_DIR", tmp_path)
    path = report_generator.generate_data_failure_report({
        "code": "600519",
        "mode": "买入前检查",
        "analysis_date": "2026-06-24",
        "stock_info": {"股票代码": "600519", "股票简称": "贵州茅台"},
        "market_data": {"股票简称": "贵州茅台"},
        "data_quality_status": "fatal",
        "data_quality_warnings": [{"level": "fatal", "stage": "raw_fetch", "source": "financial_reports", "message": "三张财报中 2 张为空"}],
    })
    content = path.read_text(encoding="utf-8")
    assert "数据失败报告" in content
    assert "fatal" in content
    assert "综合评分" not in content
    assert "财务评级" not in content
    assert "交易意义" not in content


def test_warning_report_marks_degraded_analysis(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_generator, "OUTPUT_DIR", tmp_path)
    path = report_generator.generate_markdown_report({
        "code": "600519",
        "mode": "买入前检查",
        "analysis_date": "2026-06-24",
        "stock_info": {"股票代码": "600519", "股票简称": "贵州茅台"},
        "market_data": {"股票简称": "贵州茅台"},
        "financial_score": {"total_score": 60, "score_confidence": "medium"},
        "financial_factors": {},
        "risk_flags": [],
        "announcements": [],
        "llm_results": {},
        "business_context": {
            "company_profile": {"main_business": "各类电子设备产品的设计、研发、制造与销售业务。", "base_industry": "计算机、通信和其他电子设备制造业"},
            "sw_industry": {"standard": "申银万国行业分类标准", "sector": "电子", "sub_sector": "消费电子", "industry": "消费电子零部件及组装", "sub_industry": "消费电子零部件及组装"},
            "business_composition": {
                "report_date": "2025-12-31",
                "by_industry": [{"name": "云计算", "revenue": 602678703000, "revenue_ratio": 0.667502, "gross_margin": 0.0573}],
                "by_product": [{"name": "3C电子产品", "revenue": 901224002000, "revenue_ratio": 0.998158, "gross_margin": 0.069357}],
            },
        },
        "data_quality_status": "warning",
        "data_quality_warnings": [{"level": "warning", "stage": "raw_fetch", "source": "market_data", "message": "估值字段缺失"}],
    })
    content = path.read_text(encoding="utf-8")
    assert "分析状态：降级分析" in content
    assert "数据质量状态：warning" in content
    assert "估值字段缺失" in content
    assert "## 行业" in content
    assert "主营业务：各类电子设备产品的设计、研发、制造与销售业务。" in content
    assert "云计算" in content
    assert "3C电子产品" in content


def test_report_displays_metric_provenance_summary(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_generator, "OUTPUT_DIR", tmp_path)
    metric_provenance = build_metric_provenance(
        {
            "income_statement": [{"report_period": "2025A", "publish_date": "2026-04-01", "毛利": 30, "营业收入": 100, "归母净利润": 10}],
            "balance_sheet": [{"report_period": "2025A", "publish_date": "2026-04-01", "股东权益": 50}],
            "cash_flow": [{"report_period": "2025A", "publish_date": "2026-04-01", "经营活动现金流净额": 20, "购建固定资产、无形资产和其他长期资产支付的现金": 5}],
        },
        {"股票简称": "贵州茅台", "PE TTM": 20},
        {"毛利率": 0.3, "年度ROE": 0.2, "季度ROE": 0.2, "ROE": 0.2, "自由现金流": 15, "PE TTM": 20},
        source_audit={
            "status": "ok",
            "analysis_date": "2026-06-24",
            "generated_at": "2026-06-24T00:00:00+00:00",
            "data_sources": {
                "income_statement": {"status": "ok", "field_mappings": {"营业收入": {"status": "ok"}}},
                "market_data": {"status": "ok", "field_mappings": {"PE TTM": {"status": "ok"}}},
            },
            "file_paths": {"processed": {"metric_provenance": "data/processed/600519_metric_provenance.json"}},
        },
    )
    path = report_generator.generate_markdown_report({
        "code": "600519",
        "mode": "买入前检查",
        "analysis_date": "2026-06-24",
        "stock_info": {"股票代码": "600519", "股票简称": "贵州茅台"},
        "market_data": {"股票简称": "贵州茅台"},
        "financial_score": {"total_score": 60, "score_confidence": "medium"},
        "financial_factors": {"毛利率": 0.3, "年度ROE": 0.2, "季度ROE": 0.2, "ROE": 0.2, "自由现金流": 15, "PE TTM": 20},
        "metric_provenance": metric_provenance,
        "risk_flags": [],
        "announcements": [],
        "llm_results": {},
        "business_context": {},
        "data_quality_status": "ok",
        "data_quality_warnings": [],
    })
    content = path.read_text(encoding="utf-8")
    assert "## 三、指标口径与来源追溯" in content
    assert "追溯模式：description_only" in content
    assert "毛利率：毛利 / 营业收入" in content
    assert "年度ROE：年报归母净利润 / 年报股东权益" in content
    assert "季度ROE：最新非年报报告期归母净利润 / 最新非年报报告期股东权益" in content
    assert "来源审计摘要：ok" in content
    assert "字段映射：2/2" in content
    assert "毛利率：0.3000（口径：毛利 / 营业收入；来源：年度income_statement）" in content


def test_main_raw_fatal_generates_failure_report_without_scoring(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(main_module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(main_module, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(main_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(report_generator, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(sys, "argv", ["main.py", "--code", "600519", "--date", "2026-06-24", "--mode", "买入前检查"])
    monkeypatch.setattr(main_module, "fetch_stock_info", lambda code: {"股票代码": code, "股票简称": "贵州茅台"})
    monkeypatch.setattr(main_module, "fetch_market_data", lambda code, analysis_date: {"股票简称": "贵州茅台", "最新收盘价": 100, "总市值": 1000, "PE 动态": 22, "PE TTM": None, "行情源PEG": 3.47, "PB 行情源": 4, "PB": None, "行情源PS": 9})
    monkeypatch.setattr(main_module, "fetch_financial_reports", lambda code: {
        "income_statement": pd.DataFrame(),
        "balance_sheet": pd.DataFrame(),
        "cash_flow": pd.DataFrame(),
    })
    monkeypatch.setattr(main_module, "fetch_announcements", lambda code, analysis_date: [])

    def forbidden_call(*args, **kwargs):
        raise AssertionError("fatal 数据不应继续进入清洗、评分或 LLM")

    monkeypatch.setattr(main_module, "clean_financial_reports", forbidden_call)
    monkeypatch.setattr(main_module, "compute_financial_factors", forbidden_call)
    monkeypatch.setattr(main_module, "score_financials", forbidden_call)
    monkeypatch.setattr(main_module, "run_llm_pipeline", forbidden_call)

    assert main_module.main() == 0
    reports = list(output_dir.glob("*数据失败报告.md"))
    assert len(reports) == 1
    content = reports[0].read_text(encoding="utf-8")
    assert "数据失败报告" in content
    assert "综合评分" not in content
    assert not list(processed_dir.glob("*financial_score.json"))


def test_main_normal_run_saves_metric_provenance(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(main_module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(main_module, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(main_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(report_generator, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main_module, "cleanup_output_if_requested", lambda enabled, code: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--code", "600519", "--date", "2026-06-24", "--mode", "买入前检查"])
    monkeypatch.setattr(main_module, "fetch_stock_info", lambda code: {"股票代码": code, "股票简称": "贵州茅台"})
    monkeypatch.setattr(main_module, "fetch_market_data", lambda code, analysis_date: {"股票简称": "贵州茅台", "最新收盘价": 100, "总市值": 1000, "PE 动态": 22, "PE TTM": None, "行情源PEG": 3.47, "PB 行情源": 4, "PB": None, "行情源PS": 9})
    monkeypatch.setattr(main_module, "fetch_financial_reports", lambda code: {"income_statement": pd.DataFrame([{"x": 1}]), "balance_sheet": pd.DataFrame([{"x": 1}]), "cash_flow": pd.DataFrame([{"x": 1}])})
    monkeypatch.setattr(main_module, "fetch_announcements", lambda code, analysis_date: [])
    monkeypatch.setattr(main_module, "clean_financial_reports", lambda reports, analysis_date: {
        "income_statement": [{"report_period": "2025A", "publish_date": "2026-04-01", "毛利": 30, "营业收入": 100, "归母净利润": 10, "扣非归母净利润": 9}],
        "balance_sheet": [{"report_period": "2025A", "publish_date": "2026-04-01", "股东权益": 50, "总资产": 100, "总负债": 40}],
        "cash_flow": [{"report_period": "2025A", "publish_date": "2026-04-01", "经营活动现金流净额": 20, "购建固定资产、无形资产和其他长期资产支付的现金": 5}],
    })
    monkeypatch.setattr(main_module, "fetch_business_source_tables", lambda code, analysis_date: {})
    monkeypatch.setattr(main_module, "build_business_context", lambda source_tables: {})
    monkeypatch.setattr(main_module, "run_llm_pipeline", lambda context: {})

    assert main_module.main() == 0
    provenance_path = processed_dir / "600519_metric_provenance.json"
    assert provenance_path.exists()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == "metric_provenance.v1.1"
    assert provenance["registry_mode"] == "description_only"
    assert provenance["source_audit"]["status"] == "ok"
    assert provenance["source_audit"]["data_sources"]["market_data"]["fetcher_function"] == "market_fetcher.fetch_market_data"
    assert provenance["source_audit"]["data_sources"]["income_statement"]["fetcher_function"] == "akshare_fetcher.fetch_financial_reports"
    assert provenance["source_audit"]["data_sources"]["income_statement"]["raw_path"].endswith("600519_income_statement.csv")
    assert provenance["source_audit"]["file_paths"]["processed"]["metric_provenance"].endswith("600519_metric_provenance.json")
    assert provenance["metrics"]["毛利率"]["formula_text"] == "毛利 / 营业收入"
    assert provenance["metrics"]["毛利率"]["sources"][0]["audit_ref"] == "data_sources.income_statement"
    market_data = json.loads((processed_dir / "600519_market_data.json").read_text(encoding="utf-8"))
    assert market_data["PE 动态"] == 22
    assert market_data["PE TTM"] == pytest.approx(100)
    assert market_data["行情源PEG"] == 3.47
    assert market_data["PB 行情源"] == 4
    assert market_data["PB"] == pytest.approx(20)
    assert market_data["行情源PS"] == 9
    assert market_data["PS"] == pytest.approx(10)
    assert market_data["财报估值计算"]["PE TTM"]["状态"] == "ok"
    assert market_data["财报估值计算"]["PS"]["状态"] == "ok"
    reports = list(output_dir.glob("*财务分析简报.md"))
    assert len(reports) == 1
    assert "指标口径与来源追溯" in reports[0].read_text(encoding="utf-8")


def test_cleanup_old_output_files_keeps_latest_date(tmp_path) -> None:
    old_report = tmp_path / "600519_贵州茅台_2026-06-24_财务分析简报.md"
    latest_report = tmp_path / "600519_贵州茅台_2026-06-26_财务分析简报.md"
    old_review = tmp_path / "600519_2026-06-20_anti_dependency_review.md"
    latest_review = tmp_path / "600519_2026-06-26_anti_dependency_review.md"
    other_code_old_report = tmp_path / "601138_工业富联_2026-06-24_财务分析简报.md"
    undated_file = tmp_path / ".gitkeep"
    old_report.write_text("old", encoding="utf-8")
    latest_report.write_text("latest", encoding="utf-8")
    old_review.write_text("old review", encoding="utf-8")
    latest_review.write_text("latest review", encoding="utf-8")
    other_code_old_report.write_text("other old", encoding="utf-8")
    undated_file.write_text("", encoding="utf-8")

    deleted_paths = cleanup_old_output_files("600519", tmp_path)

    assert deleted_paths == [old_report]
    assert not old_report.exists()
    assert latest_report.exists()
    assert old_review.exists()
    assert latest_review.exists()
    assert other_code_old_report.exists()
    assert undated_file.exists()


def test_qwen_audit_receives_market_data_and_quality_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_deepseek(prompt: str) -> dict[str, str]:
        return {"status": "ok", "content": "deepseek report"}

    def fake_qwen(prompt: str) -> dict[str, str]:
        captured["prompt"] = prompt
        return {"status": "ok", "content": "qwen audit"}

    monkeypatch.setattr(llm_pipeline, "call_deepseek", fake_deepseek)
    monkeypatch.setattr(llm_pipeline, "call_qwen", fake_qwen)
    result = llm_pipeline.run_llm_pipeline({
        "stock_info": {"股票代码": "600519"},
        "market_data": {"股票简称": "贵州茅台", "总市值": 100000000},
        "financial_factors": {"PE TTM": 20},
        "financial_score": {"total_score": 60},
        "risk_flags": [],
        "announcements": [],
        "data_quality_warnings": [{"level": "warning", "stage": "raw_fetch", "source": "stock_info", "message": "空数据"}],
    })
    assert result["qwen"]["status"] == "ok"
    assert "market_data" in captured["prompt"]
    assert "贵州茅台" in captured["prompt"]
    assert "data_quality_warnings" in captured["prompt"]


def test_llm_pipeline_omits_business_context_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_deepseek(prompt: str) -> dict[str, str]:
        captured["deepseek_prompt"] = prompt
        return {"status": "ok", "content": "deepseek report"}

    def fake_qwen(prompt: str) -> dict[str, str]:
        captured["qwen_prompt"] = prompt
        return {"status": "ok", "content": "qwen audit"}

    monkeypatch.setattr(llm_pipeline, "call_deepseek", fake_deepseek)
    monkeypatch.setattr(llm_pipeline, "call_qwen", fake_qwen)
    context = {
        "stock_info": {"股票代码": "601138"},
        "market_data": {"股票简称": "工业富联"},
        "financial_factors": {},
        "financial_score": {},
        "risk_flags": [],
        "announcements": [],
        "data_quality_warnings": [],
        "business_context": {"company_profile": {"main_business": "should_not_be_sent"}},
    }
    llm_pipeline.run_llm_pipeline(context)
    assert "business_context" not in captured["qwen_prompt"]
    assert "should_not_be_sent" not in captured["deepseek_prompt"]
    assert "should_not_be_sent" not in captured["qwen_prompt"]


def test_llm_pipeline_can_include_business_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_deepseek(prompt: str) -> dict[str, str]:
        captured["deepseek_prompt"] = prompt
        return {"status": "ok", "content": "deepseek report"}

    def fake_qwen(prompt: str) -> dict[str, str]:
        captured["qwen_prompt"] = prompt
        return {"status": "ok", "content": "qwen audit"}

    monkeypatch.setattr(llm_pipeline, "call_deepseek", fake_deepseek)
    monkeypatch.setattr(llm_pipeline, "call_qwen", fake_qwen)
    context = {
        "stock_info": {"股票代码": "601138"},
        "market_data": {"股票简称": "工业富联"},
        "financial_factors": {},
        "financial_score": {},
        "risk_flags": [],
        "announcements": [],
        "data_quality_warnings": [],
        "business_context": {"company_profile": {"main_business": "should_be_sent"}},
    }
    llm_pipeline.run_llm_pipeline(context, include_business_context=True)
    assert "主营业务与收入构成" in captured["deepseek_prompt"]
    assert "should_be_sent" in captured["deepseek_prompt"]
    assert "business_context" in captured["qwen_prompt"]


def test_anti_dependency_mode_records_human_judgment_before_qwen(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_qwen(prompt: str) -> dict[str, str]:
        captured["prompt"] = prompt
        return {"status": "ok", "content": "漏判：现金流风险；误判：无；过度判断：估值确定性过高"}

    inputs = iter(["我认为收入增长不错，但需要看现金流。", "END"])
    outputs: list[str] = []
    monkeypatch.setattr(anti_dependency_mode, "call_qwen", fake_qwen)
    monkeypatch.setattr(anti_dependency_mode, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(anti_dependency_mode, "OUTPUT_DIR", tmp_path)
    record = anti_dependency_mode.run_anti_dependency_mode(
        code="600519",
        mode="买入前检查",
        analysis_date=date(2026, 6, 24),
        stock_info={"股票代码": "600519", "股票简称": "贵州茅台"},
        market_data={"股票代码": "600519", "股票简称": "贵州茅台", "总市值": 1000, "PE TTM": 20},
        reports={
            "income_statement": pd.DataFrame([
                {"REPORT_DATE": "2025-12-31", "NOTICE_DATE": "2026-04-01", "TOTAL_OPERATE_INCOME": 100, "PARENT_NETPROFIT": 10},
                {"REPORT_DATE": "2026-03-31", "NOTICE_DATE": "2026-04-25", "TOTAL_OPERATE_INCOME": 120, "PARENT_NETPROFIT": 12},
            ]),
            "balance_sheet": pd.DataFrame([
                {"REPORT_DATE": "2026-03-31", "NOTICE_DATE": "2026-04-25", "TOTAL_ASSETS": 300, "TOTAL_LIABILITIES": 100, "PARENT_EQUITY": 200},
            ]),
            "cash_flow": pd.DataFrame([
                {"REPORT_DATE": "2026-03-31", "NOTICE_DATE": "2026-04-25", "NETCASH_OPERATE": 8},
            ]),
        },
        announcements=[],
        data_quality_warnings=[],
        input_func=lambda prompt: next(inputs),
        output_func=outputs.append,
    )
    assert record["human_judgment"] == "我认为收入增长不错，但需要看现金流。"
    assert record["qwen_comparison"]["status"] == "ok"
    assert "用户人工判断" in captured["prompt"]
    assert "我认为收入增长不错" in captured["prompt"]
    record_path = tmp_path / "600519_anti_dependency_record.json"
    assert record_path.exists()
    assert (tmp_path / "600519_2026-06-24_anti_dependency_review.md").exists()
    saved_record = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved_record["output_path"].endswith("600519_2026-06-24_anti_dependency_review.md")


def test_factor_score_and_risk_rules() -> None:
    reports = {
        "income_statement": [
            {"营业收入": 100, "营业成本": 70, "归母净利润": 10, "扣非归母净利润": 9, "研发费用": 3},
            {"营业收入": 120, "营业成本": 80, "归母净利润": 15, "扣非归母净利润": 12, "研发费用": 4},
        ],
        "balance_sheet": [
            {"总资产": 300, "总负债": 120, "股东权益": 180, "货币资金": 20, "短期借款": 30, "长期借款": 20, "应收账款": 40, "存货": 50, "商誉": 10},
            {"总资产": 360, "总负债": 180, "股东权益": 180, "货币资金": 20, "短期借款": 30, "长期借款": 20, "应收账款": 80, "存货": 100, "商誉": 60},
        ],
        "cash_flow": [
            {"经营活动现金流净额": 3, "销售商品、提供劳务收到的现金": 90, "购建固定资产、无形资产和其他长期资产支付的现金": 10},
            {"经营活动现金流净额": -1, "销售商品、提供劳务收到的现金": 100, "购建固定资产、无形资产和其他长期资产支付的现金": 10},
        ],
    }
    factors = compute_financial_factors(reports, {"PE TTM": 20, "PB": 3, "行情源PS": 4, "总市值": 1000})
    assert factors["毛利率"] is not None
    assert factors["指标总数量"] >= 20
    risks = generate_risk_flags(factors, reports, [{"公告标题": "关于收到监管函的公告"}])
    assert any(item["flag_name"] == "公告风险" for item in risks)
    score = score_financials(factors)
    assert 0 <= score["total_score"] <= 100
    assert score["score_confidence"] in {"high", "medium", "low"}


def test_metric_registry_matches_financial_factor_fields() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2024A", "营业收入": 100, "营业成本": 70, "归母净利润": 10, "扣非归母净利润": 9, "研发费用": 3},
            {"report_period": "2025A", "营业收入": 120, "营业成本": 80, "归母净利润": 15, "扣非归母净利润": 12, "研发费用": 4},
        ],
        "balance_sheet": [
            {"report_period": "2024A", "总资产": 300, "总负债": 120, "股东权益": 180, "货币资金": 20, "短期借款": 30, "长期借款": 20, "应收账款": 40, "存货": 50, "商誉": 10, "固定资产": 70, "在建工程": 7, "合同负债": 6, "一年内到期非流动负债": 5},
            {"report_period": "2025A", "总资产": 360, "总负债": 180, "股东权益": 180, "货币资金": 20, "短期借款": 30, "长期借款": 20, "应收账款": 80, "存货": 100, "商誉": 60, "固定资产": 80, "在建工程": 12, "合同负债": 10, "一年内到期非流动负债": 5},
        ],
        "cash_flow": [
            {"report_period": "2024A", "经营活动现金流净额": 3, "销售商品、提供劳务收到的现金": 90, "购建固定资产、无形资产和其他长期资产支付的现金": 10},
            {"report_period": "2025A", "经营活动现金流净额": -1, "销售商品、提供劳务收到的现金": 100, "购建固定资产、无形资产和其他长期资产支付的现金": 10},
        ],
    }
    factors = compute_financial_factors(reports, {"PE TTM": 20, "PB": 3, "行情源PS": 4, "总市值": 1000})
    factor_names = set(factors) - META_FACTOR_KEYS
    assert factor_names <= registered_metric_names()
    assert registered_metric_names() <= factor_names


def test_pb_is_computed_from_market_cap_and_latest_equity() -> None:
    reports = {
        "income_statement": [],
        "balance_sheet": [
            {"report_period": "2025A", "publish_date": "2026-03-24", "股东权益": 4896176437.38},
            {"report_period": "2026Q1", "publish_date": "2026-04-30", "股东权益": 5171824698.32},
        ],
        "cash_flow": [],
    }
    factors = compute_financial_factors(reports, {"总市值": 48320119000.0, "PB 行情源": 10.57})
    provenance = build_metric_provenance(reports, {"总市值": 48320119000.0, "PB 行情源": 10.57}, factors)
    assert factors["PB 行情源"] == pytest.approx(10.57)
    assert factors["PB"] == pytest.approx(48320119000.0 / 5171824698.32)
    assert provenance["metrics"]["PB"]["sources"][0]["report"] == "market_data"
    assert provenance["metrics"]["PB"]["sources"][1]["period_prefix"] == "季度"


def test_market_data_is_enriched_with_report_based_valuation_details() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2022Q1", "publish_date": "2022-04-28", "归母净利润": 4, "营业收入": 50},
            {"report_period": "2022A", "publish_date": "2023-03-28", "归母净利润": 70, "营业收入": 700},
            {"report_period": "2023Q1", "publish_date": "2023-04-28", "归母净利润": 5, "营业收入": 60},
            {"report_period": "2023A", "publish_date": "2024-03-28", "归母净利润": 80, "营业收入": 760},
            {"report_period": "2024Q1", "publish_date": "2024-04-28", "归母净利润": 10, "营业收入": 90},
        ],
        "balance_sheet": [
            {"report_period": "2024Q1", "publish_date": "2024-04-28", "股东权益": 220},
        ],
        "cash_flow": [],
    }

    market = enrich_market_data_with_report_valuations(
        {"股票代码": "600519", "总市值": 850, "PE 动态": 12.5, "PE TTM": None, "行情源PEG": 3.47, "PB 行情源": 4.0, "PB": None, "行情源PS": 7.2},
        reports,
    )

    assert market["PE 动态"] == 12.5
    assert market["行情源PEG"] == 3.47
    assert market["PB 行情源"] == 4.0
    assert market["行情源PS"] == 7.2
    assert market["PE TTM"] == pytest.approx(10)
    assert market["PEG"] == pytest.approx(10 / ((85 / 71 - 1) * 100))
    assert market["PB"] == pytest.approx(850 / 220)
    assert market["PS"] == pytest.approx(850 / 790)
    assert market["财报估值计算"]["PE TTM"]["公式"] == "总市值 / 近四季度滚动归母净利润"
    assert market["财报估值计算"]["PE TTM"]["近四季度滚动归母净利润"] == pytest.approx(85)
    assert market["财报估值计算"]["PE TTM"]["状态"] == "ok"
    assert market["财报估值计算"]["PB"]["资产负债表最新报告期"] == "2024Q1"
    assert market["财报估值计算"]["PS"]["近四季度滚动营业收入"] == pytest.approx(790)
    assert market["财报估值计算"]["PEG"]["TTM归母净利润同比"] == pytest.approx(85 / 71 - 1)


def test_annual_and_quarterly_roe_are_separate() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2024A", "publish_date": "2025-04-01", "营业收入": 1000, "营业成本": 700, "归母净利润": 120},
            {"report_period": "2025Q1", "publish_date": "2025-04-30", "营业收入": 300, "营业成本": 200, "归母净利润": 20},
        ],
        "balance_sheet": [
            {"report_period": "2024A", "publish_date": "2025-04-01", "股东权益": 600, "总资产": 1000},
            {"report_period": "2025Q1", "publish_date": "2025-04-30", "股东权益": 650, "总资产": 1100},
        ],
        "cash_flow": [],
    }
    factors = compute_financial_factors(reports, {})
    provenance = build_metric_provenance(reports, {}, factors)
    assert factors["年度ROE"] == pytest.approx(0.2)
    assert factors["季度ROE"] == pytest.approx(20 / 650)
    assert factors["单季度年化ROE"] == pytest.approx((20 * 4) / ((650 + 600) / 2))
    assert factors["ROE"] == pytest.approx(factors["年度ROE"])
    assert provenance["metrics"]["年度ROE"]["sources"][0]["report_period"] == "2024A"
    assert provenance["metrics"]["年度ROE"]["sources"][1]["report_period"] == "2024A"
    assert provenance["metrics"]["年度ROE"]["sources"][0]["period_prefix"] == "年度"
    assert provenance["metrics"]["季度ROE"]["sources"][0]["report_period"] == "2025Q1"
    assert provenance["metrics"]["季度ROE"]["sources"][1]["report_period"] == "2025Q1"
    assert provenance["metrics"]["季度ROE"]["sources"][0]["period_prefix"] == "季度"
    assert provenance["metrics"]["单季度年化ROE"]["sources"][0]["report_period"] == "2025Q1"
    assert provenance["metrics"]["单季度年化ROE"]["sources"][1]["report_period"] == "2025Q1"
    assert provenance["metrics"]["单季度年化ROE"]["sources"][2]["report_period"] == "2024A"


def test_metric_provenance_marks_half_year_sources() -> None:
    reports = {
        "income_statement": [{"report_period": "2025H1", "publish_date": "2025-08-30", "营业收入": 200, "营业成本": 120}],
        "balance_sheet": [],
        "cash_flow": [],
    }
    factors = compute_financial_factors(reports, {})
    provenance = build_metric_provenance(reports, {}, factors)
    source = provenance["metrics"]["毛利率"]["sources"][0]
    assert source["report_period"] == "2025H1"
    assert source["period_type"] == "half_year"
    assert source["period_prefix"] == "半年度"


def test_roa_and_working_capital_ratios_use_ttm_income_denominators() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2023Q1", "归母净利润": 5, "营业收入": 80},
            {"report_period": "2023A", "归母净利润": 80, "营业收入": 800},
            {"report_period": "2024Q1", "归母净利润": 10, "营业收入": 100},
        ],
        "balance_sheet": [
            {"report_period": "2023Q1", "总资产": 900, "应收账款": 90, "存货": 120},
            {"report_period": "2024Q1", "总资产": 1100, "应收账款": 220, "存货": 330},
        ],
        "cash_flow": [],
    }

    factors = compute_financial_factors(reports, {})
    provenance = build_metric_provenance(reports, {}, factors)

    assert factors["ROA"] == pytest.approx(85 / 1000)
    assert factors["应收账款/营业收入"] == pytest.approx(220 / 820)
    assert factors["存货/营业收入"] == pytest.approx(330 / 820)
    assert provenance["metrics"]["ROA"]["formula_text"] == "TTM 归母净利润 / 平均总资产"
    assert provenance["metrics"]["应收账款/营业收入"]["formula_text"] == "期末应收账款 / TTM 营业收入"
    assert provenance["metrics"]["存货/营业收入"]["formula_text"] == "期末存货 / TTM 营业收入"


def test_metric_provenance_schema_snapshot() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2024A", "publish_date": "2025-04-01", "毛利": 20, "营业收入": 80, "营业成本": 60, "归母净利润": 8, "扣非归母净利润": 8},
            {"report_period": "2025A", "publish_date": "2026-04-01", "毛利": 30, "营业收入": 100, "营业成本": 70, "归母净利润": 12, "扣非归母净利润": 12},
        ],
        "balance_sheet": [],
        "cash_flow": [],
    }
    factors = compute_financial_factors(reports, {"PE TTM": 20, "行情源PEG": 3.47, "PB": 3, "行情源PS": 4, "总市值": 1000})
    provenance = build_metric_provenance(reports, {"PE TTM": 20, "行情源PEG": 3.47, "PB": 3, "行情源PS": 4, "总市值": 1000}, factors)
    assert sorted(provenance.keys()) == ["calculation_source", "metrics", "registry_mode", "schema_version", "source_audit"]
    assert provenance["schema_version"] == "metric_provenance.v1.1"
    assert provenance["registry_mode"] == "description_only"
    assert provenance["source_audit"]["status"] == "missing"
    gross_margin = provenance["metrics"]["毛利率"]
    assert sorted(gross_margin.keys()) == ["caliber_note", "category", "formula_text", "is_ttm", "period_note", "sources", "status", "unit", "value"]
    assert gross_margin["formula_text"] == "毛利 / 营业收入"
    assert gross_margin["is_ttm"] is False
    assert gross_margin["status"] == "ok"
    assert gross_margin["sources"] == [
        {
            "report": "income_statement",
            "fields": ["毛利", "营业收入", "营业成本"],
            "available_fields": ["毛利", "营业收入", "营业成本"],
            "report_period": "2025A",
            "period_type": "annual",
            "period_prefix": "年度",
            "publish_date": "2026-04-01",
            "unit": "元",
            "audit_ref": "data_sources.income_statement",
        }
    ]
    pe_ttm = provenance["metrics"]["PE TTM"]
    assert pe_ttm["is_ttm"] is True
    assert pe_ttm["sources"] == [
        {
            "report": "market_data",
            "fields": ["总市值"],
            "available_fields": ["总市值"],
            "report_period": None,
            "publish_date": None,
            "unit": "market_data",
            "audit_ref": "data_sources.market_data",
        },
        {
            "report": "income_statement",
            "fields": ["归母净利润"],
            "available_fields": ["归母净利润"],
            "report_period": "2025A",
            "period_type": "annual",
            "period_prefix": "年度",
            "publish_date": "2026-04-01",
            "unit": "元",
            "audit_ref": "data_sources.income_statement",
        },
    ]
    assert "当年已披露的归母净利润倍增为全年预测利润" in provenance["metrics"]["PE 动态"]["caliber_note"]
    assert provenance["metrics"]["行情源PEG"]["sources"][0]["available_fields"] == ["行情源PEG"]
    assert "未来 3 年每股收益复合增长率" in provenance["metrics"]["行情源PEG"]["caliber_note"]
    assert "分析师预测 EPS" in provenance["metrics"]["行情源PEG"]["caliber_note"]
    assert provenance["metrics"]["PEG"]["formula_text"] == "PE TTM / TTM 归母净利润同比百分数"
    assert provenance["metrics"]["行情源PS"]["sources"][0]["available_fields"] == ["行情源PS"]
    assert provenance["metrics"]["PS"]["formula_text"] == "总市值 / 近四季度滚动营业收入"
    assert provenance["metrics"]["PS"]["is_ttm"] is True


def test_yoy_uses_same_report_period_last_year() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2024Q1", "营业收入": 100, "营业成本": 70, "归母净利润": 10, "扣非归母净利润": 9},
            {"report_period": "2024Q3", "营业收入": 900, "营业成本": 700, "归母净利润": 90, "扣非归母净利润": 80},
            {"report_period": "2025Q3", "营业收入": 2000, "营业成本": 1500, "归母净利润": 200, "扣非归母净利润": 190},
            {"report_period": "2025Q1", "营业收入": 120, "营业成本": 80, "归母净利润": 15, "扣非归母净利润": 12},
        ],
        "balance_sheet": [
            {"report_period": "2024Q1", "合同负债": 50, "在建工程": 10, "应收账款": 20, "存货": 30},
            {"report_period": "2024Q3", "合同负债": 500, "在建工程": 100, "应收账款": 200, "存货": 300},
            {"report_period": "2025Q3", "合同负债": 2000, "在建工程": 1000, "应收账款": 800, "存货": 900},
            {"report_period": "2025Q1", "合同负债": 75, "在建工程": 20, "应收账款": 30, "存货": 45},
        ],
        "cash_flow": [],
    }
    factors = compute_financial_factors(reports, {"PE TTM": 20})
    assert factors["营收同比"] == pytest.approx(0.2)
    assert factors["归母净利润同比"] == pytest.approx(0.5)
    assert factors["扣非归母净利润同比"] == pytest.approx(1 / 3)
    assert factors["合同负债同比"] == pytest.approx(0.5)
    assert factors["在建工程同比"] == pytest.approx(1.0)


def test_valuation_uses_ttm_denominators() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2023Q1", "归母净利润": 5, "扣非归母净利润": 5, "营业收入": 80},
            {"report_period": "2023A", "归母净利润": 80, "扣非归母净利润": 80, "营业收入": 800},
            {"report_period": "2024Q1", "归母净利润": 10, "扣非归母净利润": 10, "营业收入": 100},
            {"report_period": "2024A", "归母净利润": 100, "扣非归母净利润": 100, "营业收入": 1000},
            {"report_period": "2025Q1", "归母净利润": 20, "扣非归母净利润": 20, "营业收入": 140},
        ],
        "balance_sheet": [],
        "cash_flow": [
            {"report_period": "2024Q1", "经营活动现金流净额": 8},
            {"report_period": "2024A", "经营活动现金流净额": 90},
            {"report_period": "2025Q1", "经营活动现金流净额": 18},
        ],
    }
    factors = compute_financial_factors(reports, {"PE TTM": 20, "总市值": 1100})
    assert factors["近四季度滚动扣非净利润"] == pytest.approx(110)
    assert factors["PE TTM"] == pytest.approx(10)
    assert factors["PS"] == pytest.approx(1100 / 1040)
    assert factors["市值/扣非净利润"] == pytest.approx(10)
    assert factors["市值/经营现金流"] == pytest.approx(11)
    assert factors["PEG"] == pytest.approx(10 / ((110 / 85 - 1) * 100))


def test_peg_uses_parent_profit_ttm_growth_not_deducted_profit_growth() -> None:
    reports = {
        "income_statement": [
            {"report_period": "2023Q1", "归母净利润": 10, "扣非归母净利润": 10},
            {"report_period": "2023A", "归母净利润": 100, "扣非归母净利润": 100},
            {"report_period": "2024Q1", "归母净利润": 10, "扣非归母净利润": 20},
            {"report_period": "2024A", "归母净利润": 100, "扣非归母净利润": 200},
            {"report_period": "2025Q1", "归母净利润": 20, "扣非归母净利润": 40},
        ],
        "balance_sheet": [],
        "cash_flow": [],
    }

    factors = compute_financial_factors(reports, {"总市值": 1100, "行情源PEG": 3.47})

    assert factors["PE TTM"] == pytest.approx(10)
    assert factors["行情源PEG"] == pytest.approx(3.47)
    assert factors["PEG"] == pytest.approx(1)
