"""本模块负责清洗 AKShare 财务报表，将字段名、报告期、披露日期和金额单位统一。所有金额统一转为元，缺失值保留为空。"""

from datetime import date
from typing import Any
import numpy as np
import pandas as pd
from src.utils.date_utils import normalize_report_period, parse_optional_date

FIELD_ALIASES = {
    "营业收入": ["营业收入", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME"],
    "营业成本": ["营业成本", "OPERATE_COST", "TOTAL_OPERATE_COST"],
    "毛利": ["毛利"],
    "销售费用": ["销售费用", "SALE_EXPENSE"],
    "管理费用": ["管理费用", "MANAGE_EXPENSE"],
    "研发费用": ["研发费用", "RESEARCH_EXPENSE"],
    "财务费用": ["财务费用", "FINANCE_EXPENSE"],
    "营业利润": ["营业利润", "OPERATE_PROFIT"],
    "归母净利润": ["归母净利润", "PARENT_NETPROFIT", "NETPROFIT_PARENT_COMPANY"],
    "扣非归母净利润": ["扣非归母净利润", "DEDUCT_PARENT_NETPROFIT"],
    "总资产": ["总资产", "TOTAL_ASSETS"],
    "总负债": ["总负债", "TOTAL_LIABILITIES"],
    "股东权益": ["股东权益", "TOTAL_EQUITY", "PARENT_EQUITY"],
    "货币资金": ["货币资金", "MONETARYFUNDS"],
    "应收账款": ["应收账款", "ACCOUNTS_RECE"],
    "应收票据": ["应收票据", "NOTE_RECE"],
    "存货": ["存货", "INVENTORY"],
    "合同资产": ["合同资产", "CONTRACT_ASSET"],
    "合同负债": ["合同负债", "CONTRACT_LIAB"],
    "固定资产": ["固定资产", "FIXED_ASSET"],
    "在建工程": ["在建工程", "CIP"],
    "商誉": ["商誉", "GOODWILL"],
    "短期借款": ["短期借款", "SHORT_LOAN"],
    "一年内到期非流动负债": ["一年内到期非流动负债", "NONCURRENT_LIAB_1YEAR"],
    "长期借款": ["长期借款", "LONG_LOAN"],
    "应付账款": ["应付账款", "ACCOUNTS_PAYABLE"],
    "经营活动现金流净额": ["经营活动现金流净额", "NETCASH_OPERATE"],
    "投资活动现金流净额": ["投资活动现金流净额", "NETCASH_INVEST"],
    "筹资活动现金流净额": ["筹资活动现金流净额", "NETCASH_FINANCE"],
    "销售商品、提供劳务收到的现金": ["销售商品、提供劳务收到的现金", "SALES_SERVICES"],
    "购建固定资产、无形资产和其他长期资产支付的现金": ["购建固定资产、无形资产和其他长期资产支付的现金", "CONSTRUCT_LONG_ASSET"],
    "分配股利、利润或偿付利息支付的现金": ["分配股利、利润或偿付利息支付的现金", "ASSIGN_DIVIDEND_PORFIT"],
}
DATE_ALIASES = {
    "report_period": ["报告期", "REPORT_DATE", "报表日期", "截止日期"],
    "publish_date": ["公告日期", "公告时间", "NOTICE_DATE", "UPDATE_DATE", "披露日期"],
}


def clean_financial_reports(reports: dict[str, pd.DataFrame], analysis_date: date) -> dict[str, list[dict[str, Any]]]:
    return {name: normalize_financial_dataframe(df, analysis_date).to_dict("records") for name, df in reports.items()}


def build_financial_cleaning_audit(reports: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Build a read-only trace from standardized fields back to raw columns."""
    audit: dict[str, Any] = {}
    for report_name, df in reports.items():
        if df is None or df.empty:
            audit[report_name] = {
                "status": "missing",
                "field_mappings": {},
                "date_mappings": {},
            }
            continue
        field_mappings = {target: _field_mapping(df, target, aliases, is_amount=True) for target, aliases in FIELD_ALIASES.items()}
        date_mappings = {target: _field_mapping(df, target, aliases, is_amount=False) for target, aliases in DATE_ALIASES.items()}
        audit[report_name] = {
            "status": "ok" if any(item["status"] == "ok" for item in field_mappings.values()) else "missing",
            "field_mappings": field_mappings,
            "date_mappings": date_mappings,
        }
    return audit


def normalize_financial_dataframe(df: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    for target, aliases in FIELD_ALIASES.items():
        source = _find_column(df, aliases)
        result[target] = df[source].map(normalize_money_to_yuan) if source else None
    report_col = _find_column(df, DATE_ALIASES["report_period"])
    publish_col = _find_column(df, DATE_ALIASES["publish_date"])
    result["report_period"] = df[report_col].map(normalize_report_period) if report_col else None
    result["publish_date"] = df[publish_col].map(parse_optional_date) if publish_col else None
    result = result[result["publish_date"].isna() | (result["publish_date"] <= analysis_date)]
    result = result.dropna(how="all", subset=list(FIELD_ALIASES.keys()))
    result = result.sort_values(["report_period", "publish_date"], na_position="last")
    return result.tail(20).reset_index(drop=True)


def normalize_money_to_yuan(value: Any, source_unit: str | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace(",", "").replace("，", "").strip()
        if text in {"", "-", "--", "None", "nan"}:
            return None
        unit = source_unit or _detect_unit(text)
        text = text.replace("亿元", "").replace("万元", "").replace("元", "")
        try:
            number = float(text)
        except ValueError:
            return None
        return _convert_amount(number, unit)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(number):
        return None
    return _convert_amount(number, source_unit or "元")


def _detect_unit(text: str) -> str:
    if "亿元" in text:
        return "亿元"
    if "万元" in text:
        return "万元"
    return "元"


def _convert_amount(number: float, source_unit: str) -> float:
    if source_unit == "亿元":
        return number * 100000000
    if source_unit == "万元":
        return number * 10000
    return number


def _find_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    columns = {str(col).strip(): col for col in df.columns}
    upper_columns = {str(col).strip().upper(): col for col in df.columns}
    for alias in aliases:
        if alias in columns:
            return columns[alias]
        if alias.upper() in upper_columns:
            return upper_columns[alias.upper()]
    return None


def _field_mapping(df: pd.DataFrame, target: str, aliases: list[str], is_amount: bool) -> dict[str, Any]:
    source = _find_column(df, aliases)
    mapping: dict[str, Any] = {
        "standard_field": target,
        "aliases": aliases,
        "source_field": _string_or_none(source),
        "status": "ok" if source else "missing",
    }
    if is_amount:
        mapping["target_unit"] = "元"
        mapping["conversion"] = "normalize_money_to_yuan"
    return mapping


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)
