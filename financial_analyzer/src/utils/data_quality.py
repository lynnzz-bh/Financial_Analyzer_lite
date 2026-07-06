"""本模块负责对抓取和清洗后的数据做轻量质量检查，并输出可记录、可展示的结构化警告。"""

from typing import Any

import pandas as pd

QualityItem = dict[str, str]
WarningItem = QualityItem

REPORT_NAMES = {
    "income_statement": "利润表",
    "balance_sheet": "资产负债表",
    "cash_flow": "现金流量表",
}
MARKET_REQUIRED_FIELDS = ["股票简称", "最新收盘价", "总市值"]
MARKET_RAW_VALUATION_FIELDS = ["PE 动态", "PE TTM", "行情源PEG", "PB 行情源", "PB", "行情源PS"]


def inspect_raw_fetch_quality(
    stock_info: dict[str, Any],
    market_data: dict[str, Any],
    reports: dict[str, pd.DataFrame],
) -> list[QualityItem]:
    warnings: list[QualityItem] = []
    if stock_info.get("error"):
        warnings.append(_warning("raw_fetch", "stock_info", str(stock_info["error"])))
    for field in MARKET_REQUIRED_FIELDS:
        if _is_missing(market_data.get(field)):
            warnings.append(_warning("raw_fetch", "market_data", f"行情字段缺失：{field}"))
    if all(_is_missing(market_data.get(field)) for field in MARKET_RAW_VALUATION_FIELDS):
        warnings.append(_warning("raw_fetch", "market_data", "行情估值字段缺失：PE 动态、PE TTM、行情源PEG、PB 行情源、PB、行情源PS 均为空"))
    empty_report_names = []
    for name, label in REPORT_NAMES.items():
        df = reports.get(name)
        if df is None or df.empty:
            empty_report_names.append(label)
            warnings.append(_warning("raw_fetch", name, f"{label}原始数据为空"))
    if len(empty_report_names) >= 2:
        warnings.append(_fatal("raw_fetch", "financial_reports", f"三张财报中 {len(empty_report_names)} 张为空：{'、'.join(empty_report_names)}"))
    return warnings


def inspect_cleaned_reports_quality(cleaned_reports: dict[str, list[dict[str, Any]]]) -> list[QualityItem]:
    warnings: list[QualityItem] = []
    empty_report_names = []
    for name, label in REPORT_NAMES.items():
        rows = cleaned_reports.get(name, [])
        if not rows:
            empty_report_names.append(label)
            warnings.append(_warning("cleaned_data", name, f"{label}清洗后数据为空"))
            continue
        latest_row = rows[-1]
        if _is_missing(latest_row.get("publish_date")):
            warnings.append(_warning("cleaned_data", name, f"{label}最新财报披露日期未知"))
    if len(empty_report_names) >= 2:
        warnings.append(_fatal("cleaned_data", "financial_reports", f"三张财报中 {len(empty_report_names)} 张清洗后为空：{'、'.join(empty_report_names)}"))
    return warnings


def inspect_business_context_quality(business_context: dict[str, Any]) -> list[QualityItem]:
    items: list[QualityItem] = []
    profile = business_context.get("company_profile", {})
    composition = business_context.get("business_composition", {})
    sw_industry = business_context.get("sw_industry", {})
    if not profile.get("main_business"):
        items.append(_info("business_context", "company_profile", "主营业务信息缺失"))
    if not sw_industry:
        items.append(_info("business_context", "sw_industry", "申万行业分类缺失"))
    if not composition.get("by_industry") and not composition.get("by_product"):
        items.append(_info("business_context", "business_composition", "主营收入构成缺失"))
    return items


def summarize_quality_status(items: list[QualityItem]) -> str:
    levels = {item.get("level") for item in items}
    if "fatal" in levels:
        return "fatal"
    if "warning" in levels:
        return "warning"
    return "ok"


def _info(stage: str, source: str, message: str) -> QualityItem:
    return _item("info", stage, source, message)


def _fatal(stage: str, source: str, message: str) -> QualityItem:
    return _item("fatal", stage, source, message)


def _warning(stage: str, source: str, message: str) -> QualityItem:
    return _item("warning", stage, source, message)


def _item(level: str, stage: str, source: str, message: str) -> QualityItem:
    return {"level": level, "stage": stage, "source": source, "message": message}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
