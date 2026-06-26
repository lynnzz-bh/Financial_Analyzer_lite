"""本模块负责对抓取和清洗后的数据做轻量质量检查，并输出可记录、可展示的结构化警告。"""

from typing import Any

import pandas as pd

WarningItem = dict[str, str]

REPORT_NAMES = {
    "income_statement": "利润表",
    "balance_sheet": "资产负债表",
    "cash_flow": "现金流量表",
}
MARKET_REQUIRED_FIELDS = ["股票简称", "最新收盘价", "总市值"]
MARKET_VALUATION_FIELDS = ["PE TTM", "PB", "PS"]


def inspect_raw_fetch_quality(
    stock_info: dict[str, Any],
    market_data: dict[str, Any],
    reports: dict[str, pd.DataFrame],
) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    if stock_info.get("error"):
        warnings.append(_warning("raw_fetch", "stock_info", str(stock_info["error"])))
    for field in MARKET_REQUIRED_FIELDS:
        if _is_missing(market_data.get(field)):
            warnings.append(_warning("raw_fetch", "market_data", f"行情字段缺失：{field}"))
    if all(_is_missing(market_data.get(field)) for field in MARKET_VALUATION_FIELDS):
        warnings.append(_warning("raw_fetch", "market_data", "估值字段缺失：PE TTM、PB、PS 均为空"))
    for name, label in REPORT_NAMES.items():
        df = reports.get(name)
        if df is None or df.empty:
            warnings.append(_warning("raw_fetch", name, f"{label}原始数据为空"))
    return warnings


def inspect_cleaned_reports_quality(cleaned_reports: dict[str, list[dict[str, Any]]]) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    for name, label in REPORT_NAMES.items():
        rows = cleaned_reports.get(name, [])
        if not rows:
            warnings.append(_warning("cleaned_data", name, f"{label}清洗后数据为空"))
    return warnings


def _warning(stage: str, source: str, message: str) -> WarningItem:
    return {"level": "warning", "stage": stage, "source": source, "message": message}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
