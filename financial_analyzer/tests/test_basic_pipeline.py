"""本模块覆盖项目最基础的纯 Python 逻辑，包括日期校验、元单位换算、指标计算、风险红旗和评分可信度，避免依赖外部接口。"""

from datetime import date
import json
import pandas as pd
import pytest
from main import cleanup_old_output_files
from src.anti_dependency import anti_dependency_mode
from src.data_cleaner.financial_cleaner import normalize_financial_dataframe, normalize_money_to_yuan
from src.data_fetcher import akshare_fetcher
from src.data_fetcher.akshare_fetcher import to_eastmoney_symbol
from src.data_fetcher.astock_data_provider import (
    market_prefix,
    normalize_stock_code,
    parse_eastmoney_fund_flow_klines,
    parse_tencent_quote_payload,
)
from src.factors.financial_factors import compute_financial_factors
from src.llm import llm_pipeline
from src.factors.risk_flags import generate_risk_flags
from src.scoring.financial_score import score_financials
from src.utils.data_quality import inspect_cleaned_reports_quality, inspect_raw_fetch_quality, summarize_quality_status
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


def test_money_normalized_to_yuan() -> None:
    assert normalize_money_to_yuan("1亿元") == 100000000
    assert normalize_money_to_yuan("300万元") == 3000000
    assert normalize_money_to_yuan(10000) == 10000
    assert normalize_money_to_yuan("-") is None


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
    factors = compute_financial_factors(reports, {"PE TTM": 20, "PB": 3, "PS": 4, "总市值": 1000})
    assert factors["毛利率"] is not None
    assert factors["指标总数量"] >= 20
    risks = generate_risk_flags(factors, reports, [{"公告标题": "关于收到监管函的公告"}])
    assert any(item["flag_name"] == "公告风险" for item in risks)
    score = score_financials(factors)
    assert 0 <= score["total_score"] <= 100
    assert score["score_confidence"] in {"high", "medium", "low"}


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
            {"report_period": "2023Q1", "扣非归母净利润": 5, "营业收入": 80},
            {"report_period": "2023A", "扣非归母净利润": 80, "营业收入": 800},
            {"report_period": "2024Q1", "扣非归母净利润": 10, "营业收入": 100},
            {"report_period": "2024A", "扣非归母净利润": 100, "营业收入": 1000},
            {"report_period": "2025Q1", "扣非归母净利润": 20, "营业收入": 140},
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
    assert factors["市值/扣非净利润"] == pytest.approx(10)
    assert factors["市值/经营现金流"] == pytest.approx(11)
    assert factors["PEG"] == pytest.approx(20 / ((110 / 85 - 1) * 100))
