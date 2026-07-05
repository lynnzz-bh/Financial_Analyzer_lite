"""本模块抓取并整理公司主营业务、收入构成和行业分类上下文。"""

from datetime import date
from typing import Any

import pandas as pd

from src.data_fetcher.akshare_fetcher import to_eastmoney_symbol
from src.utils.akshare_patch import ensure_akshare_patch
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROFILE_FIELDS = ["公司名称", "所属行业", "主营业务", "经营范围"]
COMPOSITION_TYPES = {
    "按行业分类": "by_industry",
    "按产品分类": "by_product",
    "按地区分类": "by_region",
}
SW_STANDARD = "申银万国行业分类标准"
OLD_SW_STANDARD = "申银万国行业分类标准(旧)"


def fetch_business_source_tables(code: str, analysis_date: date) -> dict[str, pd.DataFrame]:
    ak = _akshare_with_patch()
    return {
        "company_profile": _safe_dataframe_call(ak.stock_profile_cninfo, symbol=code),
        "business_composition": _safe_dataframe_call(ak.stock_zygc_em, symbol=to_eastmoney_symbol(code)),
        "industry_change": _safe_dataframe_call(
            ak.stock_industry_change_cninfo,
            symbol=code,
            start_date="19900101",
            end_date=analysis_date.strftime("%Y%m%d"),
        ),
    }


def build_business_context(source_tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    profile = _company_profile_context(source_tables.get("company_profile", pd.DataFrame()))
    composition = _business_composition_context(source_tables.get("business_composition", pd.DataFrame()))
    sw_industry = _sw_industry_context(source_tables.get("industry_change", pd.DataFrame()))
    return {
        "company_profile": profile,
        "sw_industry": sw_industry,
        "business_composition": composition,
    }


def _akshare_with_patch() -> Any:
    ensure_akshare_patch(required=True)
    import akshare as ak

    return ak


def _safe_dataframe_call(func: Any, **kwargs: Any) -> pd.DataFrame:
    try:
        result = func(**kwargs)
        return result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
    except Exception as exc:
        logger.warning("主营/行业接口调用失败：%s 参数=%s 错误=%s", func.__name__, kwargs, exc)
        return pd.DataFrame()


def _company_profile_context(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    row = df.iloc[0].to_dict()
    return {
        "company_name": _clean_value(row.get("公司名称")),
        "base_industry": _clean_value(row.get("所属行业")),
        "main_business": _clean_value(row.get("主营业务")),
        "business_scope": _clean_value(row.get("经营范围")),
    }


def _business_composition_context(df: pd.DataFrame, limit: int = 5) -> dict[str, Any]:
    result = {"report_date": None, "by_industry": [], "by_product": [], "by_region": []}
    if df is None or df.empty or "报告日期" not in df.columns:
        return result
    data = df.copy()
    data["报告日期"] = data["报告日期"].astype(str)
    latest_report_date = max(data["报告日期"].dropna(), default=None)
    if not latest_report_date:
        return result
    result["report_date"] = latest_report_date
    latest = data[data["报告日期"] == latest_report_date]
    for source_type, target_key in COMPOSITION_TYPES.items():
        typed = latest[latest.get("分类类型") == source_type] if "分类类型" in latest.columns else pd.DataFrame()
        result[target_key] = _composition_rows(typed, limit)
    return result


def _composition_rows(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    data = df.copy()
    if "收入比例" in data.columns:
        data["_sort_ratio"] = pd.to_numeric(data["收入比例"], errors="coerce")
        data = data.sort_values("_sort_ratio", ascending=False, na_position="last")
    rows = []
    for _, row in data.head(limit).iterrows():
        rows.append(
            {
                "name": _clean_value(row.get("主营构成")),
                "revenue": _to_float(row.get("主营收入")),
                "revenue_ratio": _to_float(row.get("收入比例")),
                "cost": _to_float(row.get("主营成本")),
                "profit": _to_float(row.get("主营利润")),
                "gross_margin": _to_float(row.get("毛利率")),
            }
        )
    return rows


def _sw_industry_context(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or "分类标准" not in df.columns:
        return {}
    rows = df.copy()
    standard = rows["分类标准"].astype(str)
    preferred = rows[standard == SW_STANDARD]
    if preferred.empty:
        preferred = rows[standard == OLD_SW_STANDARD]
    if preferred.empty:
        preferred = rows[standard.str.contains("申银万国", na=False)]
    if preferred.empty:
        return {}
    if "变更日期" in preferred.columns:
        preferred = preferred.sort_values("变更日期")
    row = preferred.iloc[-1].to_dict()
    return {
        "standard": _clean_value(row.get("分类标准")),
        "change_date": _clean_value(row.get("变更日期")),
        "industry_code": _clean_value(row.get("行业编码")),
        "sector": _clean_value(row.get("行业门类")),
        "sub_sector": _clean_value(row.get("行业次类")),
        "industry": _clean_value(row.get("行业大类")),
        "sub_industry": _clean_value(row.get("行业中类")),
    }


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
