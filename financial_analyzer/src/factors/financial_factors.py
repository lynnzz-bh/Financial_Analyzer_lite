"""本模块负责基于清洗后的三张财务报表和市场数据计算财务指标。所有比率、同比和估值指标均由 Python 完成，并处理缺失值与除零。"""

from typing import Any
import re

import pandas as pd


def compute_financial_factors(cleaned_reports: dict[str, list[dict[str, Any]]], market_data: dict[str, Any]) -> dict[str, Any]:
    income_rows = cleaned_reports.get("income_statement", [])
    balance_rows = cleaned_reports.get("balance_sheet", [])
    cash_rows = cleaned_reports.get("cash_flow", [])
    latest_income, latest_balance, latest_cash = _latest_row(income_rows), _latest_row(balance_rows), _latest_row(cash_rows)
    factors = {
        "毛利率": _safe_div(_gross_profit(latest_income), latest_income.get("营业收入")),
        "净利率": _safe_div(latest_income.get("归母净利润"), latest_income.get("营业收入")),
        "扣非净利率": _safe_div(latest_income.get("扣非归母净利润"), latest_income.get("营业收入")),
        "ROE": _safe_div(latest_income.get("归母净利润"), latest_balance.get("股东权益")),
        "ROA": _safe_div(latest_income.get("归母净利润"), latest_balance.get("总资产")),
        "研发费用率": _safe_div(latest_income.get("研发费用"), latest_income.get("营业收入")),
        "营收同比": _yoy(income_rows, "营业收入"),
        "归母净利润同比": _yoy(income_rows, "归母净利润"),
        "扣非归母净利润同比": _yoy(income_rows, "扣非归母净利润"),
        "单季度营收同比": _yoy(income_rows, "营业收入"),
        "单季度扣非净利润同比": _yoy(income_rows, "扣非归母净利润"),
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
        "应收账款/营业收入": _safe_div(latest_balance.get("应收账款"), latest_income.get("营业收入")),
        "存货/营业收入": _safe_div(latest_balance.get("存货"), latest_income.get("营业收入")),
        "商誉/净资产": _safe_div(latest_balance.get("商誉"), latest_balance.get("股东权益")),
        "在建工程/固定资产": _safe_div(latest_balance.get("在建工程"), latest_balance.get("固定资产")),
        "PE TTM": _to_float(market_data.get("PE TTM")),
        "PB": _to_float(market_data.get("PB")),
        "PS": _to_float(market_data.get("PS")),
        # PEG 采用财务分析口径：PE TTM / TTM 扣非归母净利润同比。
        # 东方财富等行情页可能使用最近年报归母净利润同比，因此展示值可能不同。
        "PEG": _safe_div(_to_float(market_data.get("PE TTM")), _pct_to_number(_ttm_yoy(income_rows, "扣非归母净利润"))),
        "市值/扣非净利润": _safe_div(_to_float(market_data.get("总市值")), _ttm(income_rows, "扣非归母净利润")),
        "市值/经营现金流": _safe_div(_to_float(market_data.get("总市值")), _ttm(cash_rows, "经营活动现金流净额")),
    }
    factors["指标缺失数量"] = sum(1 for value in factors.values() if value is None)
    factors["指标总数量"] = len(factors) - 2
    return factors


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[-1] if rows else {}


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
