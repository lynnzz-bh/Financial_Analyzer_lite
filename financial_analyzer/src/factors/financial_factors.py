"""本模块负责基于清洗后的三张财务报表和市场数据计算财务指标。所有比率、同比和估值指标均由 Python 完成，并处理缺失值与除零。"""

from typing import Any
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
        "近四季度滚动营收": _rolling_sum(income_rows, "营业收入", 4),
        "近四季度滚动扣非净利润": _rolling_sum(income_rows, "扣非归母净利润", 4),
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
        "PEG": _safe_div(_to_float(market_data.get("PE TTM")), _pct_to_number(_yoy(income_rows, "扣非归母净利润"))),
        "市值/扣非净利润": _safe_div(_to_float(market_data.get("总市值")), latest_income.get("扣非归母净利润")),
        "市值/经营现金流": _safe_div(_to_float(market_data.get("总市值")), latest_cash.get("经营活动现金流净额")),
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
    latest, base = _to_float(rows[-1].get(field)), _to_float(rows[-2].get(field))
    if latest is None or base in (None, 0):
        return None
    return latest / base - 1


def _rolling_sum(rows: list[dict[str, Any]], field: str, window: int) -> float | None:
    values = [_to_float(row.get(field)) for row in rows[-window:]]
    if len(values) < window or any(value is None for value in values):
        return None
    return float(sum(value for value in values if value is not None))


def _free_cash_flow(row: dict[str, Any]) -> float | None:
    operating, capex = _to_float(row.get("经营活动现金流净额")), _to_float(row.get("购建固定资产、无形资产和其他长期资产支付的现金"))
    return None if operating is None or capex is None else operating - capex


def _short_debt(row: dict[str, Any]) -> float | None:
    return (_to_float(row.get("短期借款")) or 0) + (_to_float(row.get("一年内到期非流动负债")) or 0)


def _interest_bearing_debt(row: dict[str, Any]) -> float | None:
    return _short_debt(row) + (_to_float(row.get("长期借款")) or 0)


def _pct_to_number(value: float | None) -> float | None:
    return None if value is None else value * 100
