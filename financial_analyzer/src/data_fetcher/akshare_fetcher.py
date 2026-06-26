"""本模块负责从 AKShare 获取公司基础信息和三张财务报表。涉及东方财富网接口时先强制安装补丁，失败时返回可追踪错误而非静默吞掉。"""

from typing import Any
import pandas as pd
from src.utils.akshare_patch import ensure_akshare_patch
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _akshare_with_eastmoney_patch() -> Any:
    ensure_akshare_patch(required=True)
    import akshare as ak
    return ak


def _safe_dataframe_call(func: Any, **kwargs: Any) -> pd.DataFrame:
    try:
        result = func(**kwargs)
        return result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
    except Exception as exc:
        logger.warning("AKShare 接口调用失败：%s 参数=%s 错误=%s", func.__name__, kwargs, exc)
        return pd.DataFrame()


def fetch_stock_info(code: str) -> dict[str, Any]:
    ak = _akshare_with_eastmoney_patch()
    df = _safe_dataframe_call(ak.stock_individual_info_em, symbol=code)
    if df.empty:
        return {"股票代码": code, "error": "stock_individual_info_em 返回空数据"}
    if {"item", "value"}.issubset(df.columns):
        info = dict(zip(df["item"], df["value"], strict=False))
    elif {"项目", "值"}.issubset(df.columns):
        info = dict(zip(df["项目"], df["值"], strict=False))
    else:
        info = df.iloc[0].dropna().to_dict()
    info.setdefault("股票代码", code)
    return info


def fetch_financial_reports(code: str) -> dict[str, pd.DataFrame]:
    ak = _akshare_with_eastmoney_patch()
    symbol = to_eastmoney_symbol(code)
    return {
        "income_statement": _safe_dataframe_call(ak.stock_profit_sheet_by_report_em, symbol=symbol),
        "balance_sheet": _safe_dataframe_call(ak.stock_balance_sheet_by_report_em, symbol=symbol),
        "cash_flow": _safe_dataframe_call(ak.stock_cash_flow_sheet_by_report_em, symbol=symbol),
    }


def to_eastmoney_symbol(code: str) -> str:
    clean_code = str(code).strip()
    if clean_code.startswith(("6", "9")):
        return f"SH{clean_code}"
    if clean_code.startswith(("0", "2", "3")):
        return f"SZ{clean_code}"
    if clean_code.startswith(("4", "8")):
        return f"BJ{clean_code}"
    return clean_code
