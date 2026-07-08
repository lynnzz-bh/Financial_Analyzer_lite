"""本模块负责基于清洗后的三张财务报表和市场数据计算财务指标。所有比率、同比和估值指标均由 Python 完成，并处理缺失值与除零。"""

from typing import Any
import re

import pandas as pd

from src.factors.quarterly_factors import split_ytd_reports_to_quarters

QUARTERLY_INCOME_FIELDS = ["营业收入", "归母净利润", "扣非归母净利润"]
QUARTERLY_CASH_FIELDS = ["经营活动现金流净额"]
QUARTERLY_TRANSITION_FIELDS = {
    "单季度营业收入",
    "单季度归母净利润",
    "单季度扣非净利润",
    "单季度经营现金流",
    "单季度同比信号",
}


def compute_financial_factors(cleaned_reports: dict[str, list[dict[str, Any]]], market_data: dict[str, Any]) -> dict[str, Any]:
    income_rows = cleaned_reports.get("income_statement", [])
    balance_rows = cleaned_reports.get("balance_sheet", [])
    cash_rows = cleaned_reports.get("cash_flow", [])
    latest_income, latest_balance, latest_cash = _latest_row(income_rows), _latest_row(balance_rows), _latest_row(cash_rows)
    income_quarters = split_ytd_reports_to_quarters(income_rows, QUARTERLY_INCOME_FIELDS, report_name="income_statement")
    cash_quarters = split_ytd_reports_to_quarters(cash_rows, QUARTERLY_CASH_FIELDS, report_name="cash_flow")
    latest_income_quarter = _latest_quarter_result(income_quarters, income_rows)
    latest_cash_quarter = _latest_quarter_result(cash_quarters, cash_rows)
    single_quarter_revenue_yoy, single_quarter_revenue_signal = _single_quarter_yoy(income_quarters, latest_income_quarter, "营业收入", "单季度营收同比")
    single_quarter_deducted_profit_yoy, single_quarter_deducted_profit_signal = _single_quarter_yoy(income_quarters, latest_income_quarter, "扣非归母净利润", "单季度扣非净利润同比")
    annual_income, annual_balance = _latest_annual_row(income_rows), _latest_annual_row(balance_rows)
    quarterly_income, quarterly_balance = _latest_quarterly_row(income_rows), _latest_quarterly_row(balance_rows)
    annual_roe = _safe_div(annual_income.get("归母净利润"), annual_balance.get("股东权益"))
    quarterly_roe = _safe_div(quarterly_income.get("归母净利润"), quarterly_balance.get("股东权益"))
    single_quarter_annualized_roe = _single_quarter_annualized_roe(income_rows, balance_rows, income_quarters)
    ttm_revenue = _ttm(income_rows, "营业收入")
    report_based_valuation = compute_report_based_valuation(cleaned_reports, market_data)
    factors = {
        "毛利率": _safe_div(_gross_profit(latest_income), latest_income.get("营业收入")),
        "净利率": _safe_div(latest_income.get("归母净利润"), latest_income.get("营业收入")),
        "扣非净利率": _safe_div(latest_income.get("扣非归母净利润"), latest_income.get("营业收入")),
        "年度ROE": annual_roe,
        "季度ROE": quarterly_roe,
        "单季度年化ROE": single_quarter_annualized_roe,
        "ROE": annual_roe,
        "ROA": _safe_div(_ttm(income_rows, "归母净利润"), _average_same_period_balance(balance_rows, "总资产")),
        "研发费用率": _safe_div(latest_income.get("研发费用"), latest_income.get("营业收入")),
        "营收同比": _yoy(income_rows, "营业收入"),
        "归母净利润同比": _yoy(income_rows, "归母净利润"),
        "扣非归母净利润同比": _yoy(income_rows, "扣非归母净利润"),
        "单季度营业收入": _quarter_value(latest_income_quarter, "营业收入"),
        "单季度归母净利润": _quarter_value(latest_income_quarter, "归母净利润"),
        "单季度扣非净利润": _quarter_value(latest_income_quarter, "扣非归母净利润"),
        "单季度经营现金流": _quarter_value(latest_cash_quarter, "经营活动现金流净额"),
        "单季度营收同比": single_quarter_revenue_yoy,
        "单季度扣非净利润同比": single_quarter_deducted_profit_yoy,
        "单季度同比信号": {
            "单季度营收同比": single_quarter_revenue_signal,
            "单季度扣非净利润同比": single_quarter_deducted_profit_signal,
        },
        "近四季度滚动营收": _ttm(income_rows, "营业收入"),
        "近四季度滚动扣非净利润": _ttm(income_rows, "扣非归母净利润"),
        "合同负债同比": _yoy(balance_rows, "合同负债"),
        "在建工程同比": _yoy(balance_rows, "在建工程"),
        "应收账款同比": _yoy(balance_rows, "应收账款"),
        "存货同比": _yoy(balance_rows, "存货"),
        "经营现金流/归母净利润": _safe_div(latest_cash.get("经营活动现金流净额"), latest_income.get("归母净利润")),
        "经营现金流/扣非归母净利润": _safe_div(latest_cash.get("经营活动现金流净额"), latest_income.get("扣非归母净利润")),
        "销售收现比": _safe_div(latest_cash.get("销售商品、提供劳务收到的现金"), latest_income.get("营业收入")),
        "自由现金流": _free_cash_flow(latest_cash),
        "资本开支/营业收入": _safe_div(latest_cash.get("购建固定资产、无形资产和其他长期资产支付的现金"), latest_income.get("营业收入")),
        "资产负债率": _safe_div(latest_balance.get("总负债"), latest_balance.get("总资产")),
        "有息负债": _interest_bearing_debt(latest_balance),
        "有息负债率": _safe_div(_interest_bearing_debt(latest_balance), latest_balance.get("总资产")),
        "短债/货币资金": _safe_div(_short_debt(latest_balance), latest_balance.get("货币资金")),
        "应收账款/营业收入": _safe_div(latest_balance.get("应收账款"), ttm_revenue),
        "存货/营业收入": _safe_div(latest_balance.get("存货"), ttm_revenue),
        "商誉/净资产": _safe_div(latest_balance.get("商誉"), latest_balance.get("股东权益")),
        "在建工程/固定资产": _safe_div(latest_balance.get("在建工程"), latest_balance.get("固定资产")),
        "PE 动态": _to_float(market_data.get("PE 动态")),
        "PE TTM": report_based_valuation["PE TTM"],
        "行情源PEG": _to_float(market_data.get("行情源PEG")),
        "PB 行情源": _to_float(market_data.get("PB 行情源")),
        "PB": report_based_valuation["PB"],
        "行情源PS": _to_float(market_data.get("行情源PS")),
        "PS": report_based_valuation["PS"],
        # PEG 采用财务分析口径：PE TTM / TTM 归母净利润同比。
        # 东财行情源 PEG 使用 PE TTM 和未来三年预测 EPS 复合增速，保留为“行情源PEG”对照。
        "PEG": report_based_valuation["PEG"],
        "市值/扣非净利润": _safe_div(_to_float(market_data.get("总市值")), _ttm(income_rows, "扣非归母净利润")),
        "市值/经营现金流": _safe_div(_to_float(market_data.get("总市值")), _ttm(cash_rows, "经营活动现金流净额")),
    }
    countable_values = [value for key, value in factors.items() if key not in QUARTERLY_TRANSITION_FIELDS]
    factors["指标缺失数量"] = sum(1 for value in countable_values if value is None)
    factors["指标总数量"] = len(countable_values)
    return factors


def enrich_market_data_with_report_valuations(market_data: dict[str, Any], cleaned_reports: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    enriched = dict(market_data)
    report_based_valuation = compute_report_based_valuation(cleaned_reports, market_data)
    for field in ("PE TTM", "PB", "PS", "PEG"):
        if report_based_valuation[field] is not None:
            enriched[field] = report_based_valuation[field]
    enriched["财报估值计算"] = report_based_valuation["计算明细"]
    return enriched


def compute_report_based_valuation(cleaned_reports: dict[str, list[dict[str, Any]]], market_data: dict[str, Any]) -> dict[str, Any]:
    income_rows = cleaned_reports.get("income_statement", [])
    balance_rows = cleaned_reports.get("balance_sheet", [])
    latest_income = _latest_row(income_rows)
    latest_balance = _latest_row(balance_rows)
    market_cap = _to_float(market_data.get("总市值"))
    ttm_parent_net_profit = _ttm(income_rows, "归母净利润")
    ttm_parent_net_profit_yoy = _ttm_yoy(income_rows, "归母净利润")
    ttm_revenue = _ttm(income_rows, "营业收入")
    latest_equity = _to_float(latest_balance.get("股东权益"))
    pe_ttm = _safe_div(market_cap, ttm_parent_net_profit)
    pb = _safe_div(market_cap, latest_equity)
    ps = _safe_div(market_cap, ttm_revenue)
    peg = _safe_div(pe_ttm, _pct_to_number(ttm_parent_net_profit_yoy))
    return {
        "PE TTM": pe_ttm,
        "PB": pb,
        "PS": ps,
        "PEG": peg,
        "计算明细": {
            "PE TTM": {
                "公式": "总市值 / 近四季度滚动归母净利润",
                "总市值": market_cap,
                "近四季度滚动归母净利润": ttm_parent_net_profit,
                "利润表最新报告期": latest_income.get("report_period"),
                "利润表最新披露日期": latest_income.get("publish_date"),
                "计算值": pe_ttm,
                "状态": "ok" if pe_ttm is not None else "missing",
            },
            "PB": {
                "公式": "总市值 / 最新股东权益",
                "总市值": market_cap,
                "最新股东权益": latest_equity,
                "资产负债表最新报告期": latest_balance.get("report_period"),
                "资产负债表最新披露日期": latest_balance.get("publish_date"),
                "计算值": pb,
                "状态": "ok" if pb is not None else "missing",
            },
            "PS": {
                "公式": "总市值 / 近四季度滚动营业收入",
                "总市值": market_cap,
                "近四季度滚动营业收入": ttm_revenue,
                "利润表最新报告期": latest_income.get("report_period"),
                "利润表最新披露日期": latest_income.get("publish_date"),
                "计算值": ps,
                "状态": "ok" if ps is not None else "missing",
            },
            "PEG": {
                "公式": "PE TTM / TTM 归母净利润同比百分数",
                "PE TTM": pe_ttm,
                "TTM归母净利润同比": ttm_parent_net_profit_yoy,
                "TTM归母净利润同比百分数": _pct_to_number(ttm_parent_net_profit_yoy),
                "利润表最新报告期": latest_income.get("report_period"),
                "利润表最新披露日期": latest_income.get("publish_date"),
                "计算值": peg,
                "状态": "ok" if peg is not None else "missing",
            },
        },
    }


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[-1] if rows else {}


def _latest_annual_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in reversed(rows):
        if str(row.get("report_period") or "").endswith("A"):
            return row
    return _latest_row(rows)


def _latest_quarterly_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in reversed(rows):
        period = str(row.get("report_period") or "")
        if period and not period.endswith("A"):
            return row
    return _latest_row(rows)


def _single_quarter_annualized_roe(
    income_rows: list[dict[str, Any]],
    balance_rows: list[dict[str, Any]],
    income_quarters: dict[str, Any] | None = None,
) -> float | None:
    latest_balance = _latest_row(balance_rows)
    income_quarters = income_quarters or split_ytd_reports_to_quarters(income_rows, QUARTERLY_INCOME_FIELDS, report_name="income_statement")
    single_quarter_profit = _quarter_value(_latest_quarter_result(income_quarters, income_rows), "归母净利润")
    previous_balance = _previous_balance_for_single_quarter(balance_rows, latest_balance)
    average_equity = _average_values(latest_balance.get("股东权益"), previous_balance.get("股东权益"))
    return _safe_div(_multiply(single_quarter_profit, 4), average_equity)


def _latest_quarter_result(quarter_split: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_period = _normalized_source_period(_latest_row(rows).get("report_period"))
    if latest_period is None:
        return {}
    for quarter in reversed(quarter_split.get("quarters", [])):
        if quarter.get("source_period") == latest_period:
            return quarter
    return {}


def _normalized_source_period(value: Any) -> str | None:
    period = _parse_period(value)
    if period is None:
        return None
    year, period_code = period
    return f"{year}{period_code}"


def _quarter_value(quarter: dict[str, Any], field: str) -> float | None:
    values = quarter.get("values", {}) if isinstance(quarter, dict) else {}
    return _to_float(values.get(_quarter_field_name(field)))


def _quarter_field_name(field: str) -> str:
    return f"{field}_QTR"


def _single_quarter_yoy(
    quarter_split: dict[str, Any],
    latest_quarter: dict[str, Any],
    field: str,
    metric_name: str,
) -> tuple[float | None, dict[str, Any]]:
    current_period = latest_quarter.get("qtr_period")
    base_period = _same_quarter_last_year_period(current_period)
    current = _quarter_value(latest_quarter, field)
    base_quarter = _quarter_by_qtr_period(quarter_split).get(base_period)
    base = _quarter_value(base_quarter or {}, field)
    if current is None or base is None:
        return None, _single_quarter_signal(metric_name, field, "missing", current_period, base_period, current, base)
    if base > 0:
        return current / base - 1, _single_quarter_signal(metric_name, field, "normal", current_period, base_period, current, base)
    if base == 0:
        return None, _single_quarter_signal(metric_name, field, "base_zero", current_period, base_period, current, base)
    if current > 0:
        return None, _single_quarter_signal(metric_name, field, "turnaround", current_period, base_period, current, base)
    if current < base:
        return None, _single_quarter_signal(metric_name, field, "loss_expanded", current_period, base_period, current, base)
    return None, _single_quarter_signal(metric_name, field, "loss_narrowed", current_period, base_period, current, base)


def _same_quarter_last_year_period(qtr_period: Any) -> str | None:
    match = re.fullmatch(r"(\d{4})Q([1-4])", str(qtr_period or ""))
    if not match:
        return None
    return f"{int(match.group(1)) - 1}Q{match.group(2)}"


def _quarter_by_qtr_period(quarter_split: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    return {quarter.get("qtr_period"): quarter for quarter in quarter_split.get("quarters", [])}


def _single_quarter_signal(
    metric_name: str,
    field: str,
    status: str,
    current_period: Any,
    base_period: Any,
    current: float | None,
    base: float | None,
) -> dict[str, Any]:
    return {
        "metric": metric_name,
        "field": field,
        "status": status,
        "current_period": current_period,
        "base_period": base_period,
        "current_value": current,
        "base_value": base,
        "message": _single_quarter_signal_message(status),
    }


def _single_quarter_signal_message(status: str) -> str:
    messages = {
        "normal": "去年同季度基数为正，单季度同比可按常规百分比计算。",
        "turnaround": "去年同季度为负，本期转正；本质是扭亏为盈，不输出同比百分比。",
        "loss_expanded": "去年同季度为负，本期亏损扩大；不输出同比百分比。",
        "loss_narrowed": "去年同季度为负，本期亏损收窄或持平；不输出同比百分比。",
        "base_zero": "去年同季度基数为 0，无法计算有意义的同比百分比。",
        "missing": "当前单季度值或去年同季度单季度值缺失。",
    }
    return messages.get(status, "单季度同比状态未知。")


def _previous_balance_for_single_quarter(rows: list[dict[str, Any]], latest_row: dict[str, Any]) -> dict[str, Any]:
    period = _parse_period(latest_row.get("report_period"))
    if period is None:
        return {}
    year, period_code = period
    previous_period = {"Q1": f"{year - 1}A", "H1": f"{year}Q1", "Q3": f"{year}H1", "A": f"{year}Q3"}[period_code]
    return _row_for_period(rows, previous_period)


def _average_same_period_balance(rows: list[dict[str, Any]], field: str) -> float | None:
    latest_row = _latest_row(rows)
    base_row = _same_period_last_year(rows, latest_row)
    if base_row is None:
        return None
    return _average_values(latest_row.get(field), base_row.get(field))


def _average_values(first: Any, second: Any) -> float | None:
    first_value, second_value = _to_float(first), _to_float(second)
    if first_value is None or second_value is None:
        return None
    return (first_value + second_value) / 2


def _multiply(value: Any, factor: float) -> float | None:
    numeric = _to_float(value)
    return None if numeric is None else numeric * factor


def _safe_div(numerator: Any, denominator: Any) -> float | None:
    num, den = _to_float(numerator), _to_float(denominator)
    if num is None or den in (None, 0):
        return None
    return num / den


def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _gross_profit(row: dict[str, Any]) -> float | None:
    gross = _to_float(row.get("毛利"))
    if gross is not None:
        return gross
    revenue, cost = _to_float(row.get("营业收入")), _to_float(row.get("营业成本"))
    return None if revenue is None or cost is None else revenue - cost


def _yoy(rows: list[dict[str, Any]], field: str) -> float | None:
    if len(rows) < 2:
        return None
    latest_row = rows[-1]
    base_row = _same_period_last_year(rows, latest_row)
    if base_row is None:
        return None
    latest, base = _to_float(latest_row.get(field)), _to_float(base_row.get(field))
    if latest is None or base in (None, 0):
        return None
    return latest / base - 1


def _same_period_last_year(rows: list[dict[str, Any]], latest_row: dict[str, Any]) -> dict[str, Any] | None:
    period = latest_row.get("report_period")
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|A)", str(period or ""))
    if not match:
        return None
    target_period = f"{int(match.group(1)) - 1}{match.group(2)}"
    for row in reversed(rows[:-1]):
        if row.get("report_period") == target_period:
            return row
    return None


def _ttm(rows: list[dict[str, Any]], field: str) -> float | None:
    latest_row = _latest_row(rows)
    period = _parse_period(latest_row.get("report_period"))
    if period is None:
        return None
    return _ttm_for_period(rows, field, period[0], period[1])


def _ttm_yoy(rows: list[dict[str, Any]], field: str) -> float | None:
    latest_row = _latest_row(rows)
    period = _parse_period(latest_row.get("report_period"))
    if period is None:
        return None
    latest_ttm = _ttm_for_period(rows, field, period[0], period[1])
    base_ttm = _ttm_for_period(rows, field, period[0] - 1, period[1])
    if latest_ttm is None or base_ttm in (None, 0):
        return None
    return latest_ttm / base_ttm - 1


def _ttm_for_period(rows: list[dict[str, Any]], field: str, year: int, period_code: str) -> float | None:
    current = _to_float(_row_for_period(rows, f"{year}{period_code}").get(field))
    if current is None:
        return None
    if period_code == "A":
        return current
    annual = _to_float(_row_for_period(rows, f"{year - 1}A").get(field))
    same_period_last_year = _to_float(_row_for_period(rows, f"{year - 1}{period_code}").get(field))
    if annual is None or same_period_last_year is None:
        return None
    return current + annual - same_period_last_year


def _row_for_period(rows: list[dict[str, Any]], period: str) -> dict[str, Any]:
    for row in reversed(rows):
        if row.get("report_period") == period:
            return row
    return {}


def _parse_period(value: Any) -> tuple[int, str] | None:
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|A)", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _free_cash_flow(row: dict[str, Any]) -> float | None:
    operating, capex = _to_float(row.get("经营活动现金流净额")), _to_float(row.get("购建固定资产、无形资产和其他长期资产支付的现金"))
    return None if operating is None or capex is None else operating - capex


def _short_debt(row: dict[str, Any]) -> float | None:
    values = [_to_float(row.get("短期借款")), _to_float(row.get("一年内到期非流动负债"))]
    if all(value is None for value in values):
        return None
    return sum(value or 0 for value in values)


def _interest_bearing_debt(row: dict[str, Any]) -> float | None:
    short_debt, long_debt = _short_debt(row), _to_float(row.get("长期借款"))
    if short_debt is None and long_debt is None:
        return None
    return (short_debt or 0) + (long_debt or 0)


def _pct_to_number(value: float | None) -> float | None:
    return None if value is None else value * 100
