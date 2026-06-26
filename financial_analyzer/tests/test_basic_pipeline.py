"""本模块覆盖项目最基础的纯 Python 逻辑，包括日期校验、万元换算、指标计算、风险红旗和评分可信度，避免依赖外部接口。"""

from datetime import date
import pandas as pd
import pytest
from src.data_cleaner.financial_cleaner import normalize_financial_dataframe, normalize_money_to_wan
from src.data_fetcher.astock_data_provider import (
    market_prefix,
    normalize_stock_code,
    parse_eastmoney_fund_flow_klines,
    parse_tencent_quote_payload,
)
from src.factors.financial_factors import compute_financial_factors
from src.factors.risk_flags import generate_risk_flags
from src.scoring.financial_score import score_financials
from src.utils.date_utils import parse_analysis_date, validate_stock_code


def test_date_and_code_validation() -> None:
    assert parse_analysis_date("2026-06-24") == date(2026, 6, 24)
    assert validate_stock_code("600519") == "600519"
    assert normalize_stock_code("SH600519") == "600519"
    assert normalize_stock_code("000001.SZ") == "000001"
    assert market_prefix("600519") == "sh"
    assert market_prefix("000001") == "sz"
    with pytest.raises(ValueError):
        validate_stock_code("abc")
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


def test_astock_fund_flow_parser() -> None:
    rows = parse_eastmoney_fund_flow_klines([
        "2026-06-24,1000,-200,300,400,500,1,2",
        "bad,row",
        "2026-06-25,-,-,-,-,-",
    ])
    assert rows[0]["date"] == "2026-06-24"
    assert rows[0]["main_net"] == 1000
    assert rows[1]["main_net"] is None


def test_money_normalized_to_wan() -> None:
    assert normalize_money_to_wan("1亿元") == 10000
    assert normalize_money_to_wan("300万元") == 300
    assert normalize_money_to_wan(10000) == 1
    assert normalize_money_to_wan("-") is None


def test_cleaner_filters_future_publish_date() -> None:
    df = pd.DataFrame([
        {"REPORT_DATE": "2024-12-31", "NOTICE_DATE": "2025-04-01", "TOTAL_OPERATE_INCOME": 10000},
        {"REPORT_DATE": "2025-12-31", "NOTICE_DATE": "2026-07-01", "TOTAL_OPERATE_INCOME": 20000},
    ])
    cleaned = normalize_financial_dataframe(df, date(2026, 6, 24))
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["营业收入"] == 1


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
