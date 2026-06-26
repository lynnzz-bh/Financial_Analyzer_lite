"""本模块负责从 AKShare 获取公司基础信息和三张财务报表。涉及东方财富网接口时先强制安装补丁，失败时返回可追踪错误而非静默吞掉。"""

from typing import Any
import pandas as pd
import requests
from src.utils.akshare_patch import ensure_akshare_patch
from src.utils.logger import get_logger

logger = get_logger(__name__)
STOCK_INFO_FIELDS = "f43,f57,f58,f84,f85,f116,f117,f127,f189"
STOCK_INFO_FIELD_NAMES = {
    "f57": "股票代码",
    "f58": "股票简称",
    "f84": "总股本",
    "f85": "流通股",
    "f116": "总市值",
    "f117": "流通市值",
    "f127": "行业",
    "f189": "上市时间",
    "f43": "最新",
}


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
    ensure_akshare_patch(required=True)
    info = _fetch_stock_info_from_push2(code)
    if not info:
        return {"股票代码": code, "error": "push2 stock get 返回空数据"}
    info.setdefault("股票代码", code)
    return info


def _fetch_stock_info_from_push2(code: str) -> dict[str, Any]:
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": STOCK_INFO_FIELDS,
        "secid": f"{_eastmoney_market_code(code)}.{code}",
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json().get("data") or {}
    except Exception as exc:
        logger.warning("东方财富基础信息接口调用失败：参数=%s 错误=%s", params, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {target: data.get(source) for source, target in STOCK_INFO_FIELD_NAMES.items() if data.get(source) is not None}


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


def _eastmoney_market_code(code: str) -> int:
    return 1 if str(code).strip().startswith(("6", "9")) else 0
