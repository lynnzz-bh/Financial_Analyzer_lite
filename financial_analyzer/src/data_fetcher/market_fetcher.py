"""本模块负责获取单只股票行情、估值和历史涨跌幅。东方财富网行情接口必须经过补丁，历史行情如来自东方财富也按强制补丁处理。"""

from datetime import date, timedelta
from typing import Any
import pandas as pd
from src.utils.akshare_patch import ensure_akshare_patch
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _akshare_with_eastmoney_patch() -> Any:
    ensure_akshare_patch(required=True)
    import akshare as ak
    return ak


def fetch_market_data(code: str, analysis_date: date) -> dict[str, Any]:
    ak = _akshare_with_eastmoney_patch()
    spot = _safe_dataframe_call(ak.stock_zh_a_spot_em)
    row = _select_spot_row(spot, code)
    market = _map_market_row(row, code)
    market.update(_calculate_recent_returns(ak, code, analysis_date))
    return market


def _safe_dataframe_call(func: Any, **kwargs: Any) -> pd.DataFrame:
    try:
        result = func(**kwargs)
        return result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
    except Exception as exc:
        logger.warning("AKShare 行情接口调用失败：%s 参数=%s 错误=%s", func.__name__, kwargs, exc)
        return pd.DataFrame()


def _select_spot_row(df: pd.DataFrame, code: str) -> dict[str, Any]:
    if df.empty:
        return {}
    for col in ("代码", "股票代码", "symbol"):
        if col in df.columns:
            matched = df[df[col].astype(str).str.zfill(6) == code]
            if not matched.empty:
                return matched.iloc[0].to_dict()
    return {}


def _first_present(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _map_market_row(row: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "股票代码": code,
        "股票简称": _first_present(row, ["名称", "股票简称"]),
        "最新收盘价": _first_present(row, ["最新价", "收盘", "最新收盘价"]),
        "总市值": _first_present(row, ["总市值"]),
        "流通市值": _first_present(row, ["流通市值"]),
        "PE 动态": _first_present(row, ["市盈率-动态", "PE 动态"]),
        "PE TTM": _first_present(row, ["市盈率TTM", "PE TTM"]),
        "行情源PEG": _first_present(row, ["PEG", "行情源PEG"]),
        "PB 行情源": _first_present(row, ["市净率", "PB 行情源"]),
        "PB": _first_present(row, ["PB"]),
        "行情源PS": _first_present(row, ["市销率", "行情源PS", "PS"]),
        "PS": None,
        "成交额": _first_present(row, ["成交额"]),
        "换手率": _first_present(row, ["换手率"]),
    }


def _calculate_recent_returns(ak: Any, code: str, analysis_date: date) -> dict[str, Any]:
    hist = _safe_dataframe_call(
        ak.stock_zh_a_hist,
        symbol=code,
        period="daily",
        start_date=(analysis_date - timedelta(days=160)).strftime("%Y%m%d"),
        end_date=analysis_date.strftime("%Y%m%d"),
        adjust="",
    )
    if hist.empty or "收盘" not in hist.columns:
        return {"近20日涨跌幅": None, "近60日涨跌幅": None}
    hist = hist.sort_values(by="日期") if "日期" in hist.columns else hist
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    return {"近20日涨跌幅": _period_return(close, 20), "近60日涨跌幅": _period_return(close, 60)}


def _period_return(close: pd.Series, periods: int) -> float | None:
    if len(close) <= periods:
        return None
    base, latest = close.iloc[-periods - 1], close.iloc[-1]
    if base == 0 or pd.isna(base) or pd.isna(latest):
        return None
    return float(latest / base - 1)
