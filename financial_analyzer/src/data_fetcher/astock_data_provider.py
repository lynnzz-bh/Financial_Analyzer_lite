"""Supplemental A-share data fetchers adapted from simonlin1212/a-stock-data.

The functions in this module are intentionally not wired into the main
analysis pipeline yet. They provide direct Tencent/Eastmoney data access for
future enrichment while keeping the current AKShare-based flow unchanged.

Source: https://github.com/simonlin1212/a-stock-data
License: Apache-2.0
"""

from __future__ import annotations

import random
import re
import threading
import time
from typing import Any

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_MIN_INTERVAL = 1.0

_EM_SESSION = requests.Session()
_EM_SESSION.headers.update({"User-Agent": UA})
_EM_LOCK = threading.Lock()
_em_last_call = 0.0


def normalize_stock_code(code: str) -> str:
    """Normalize common ticker formats to a 6 digit A-share code."""
    raw = str(code).strip().upper()
    match = re.search(r"(\d{6})", raw)
    if not match:
        raise ValueError(f"股票代码格式错误：{code}")
    return match.group(1)


def market_prefix(code: str) -> str:
    """Return Tencent-style market prefix: sh/sz/bj."""
    normalized = normalize_stock_code(code)
    if normalized.startswith(("6", "9")):
        return "sh"
    if normalized.startswith("8"):
        return "bj"
    return "sz"


def eastmoney_market_code(code: str) -> int:
    """Return Eastmoney secid market code: 1=Shanghai, 0=Shenzhen/Beijing."""
    return 1 if normalize_stock_code(code).startswith(("6", "9")) else 0


def eastmoney_get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    """Eastmoney request entry with process-local serial throttling."""
    global _em_last_call
    with _EM_LOCK:
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            response = _EM_SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        finally:
            _em_last_call = time.time()


def eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict[str, Any]]:
    """Query Eastmoney datacenter reports used by follow-up supplemental fetchers."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        data = eastmoney_get(DATACENTER_URL, params=params).json()
    except Exception as exc:
        logger.warning("Eastmoney datacenter request failed: %s %s", report_name, exc)
        return []
    result = data.get("result") or {}
    rows = result.get("data") or []
    return rows if isinstance(rows, list) else []


def fetch_tencent_quote(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch Tencent real-time quote and valuation fields for stocks, indexes, or ETFs."""
    normalized = [normalize_stock_code(code) for code in codes]
    prefixed = [f"{market_prefix(code)}{code}" for code in normalized]
    if not prefixed:
        return {}

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    try:
        response = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        response.raise_for_status()
        payload = response.content.decode("gbk", errors="ignore")
    except Exception as exc:
        logger.warning("Tencent quote request failed: %s", exc)
        return {}
    return parse_tencent_quote_payload(payload)


def parse_tencent_quote_payload(payload: str) -> dict[str, dict[str, Any]]:
    """Parse Tencent quote payload into typed dictionaries."""
    result: dict[str, dict[str, Any]] = {}
    for line in payload.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=", 1)[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:] if key[:2] in {"sh", "sz", "bj"} else vals[2]
        result[code] = {
            "股票代码": code,
            "股票简称": vals[1],
            "最新价": _to_float(vals[3]),
            "昨收": _to_float(vals[4]),
            "今开": _to_float(vals[5]),
            "涨跌额": _to_float(vals[31]),
            "涨跌幅": _to_float(vals[32]),
            "最高价": _to_float(vals[33]),
            "最低价": _to_float(vals[34]),
            "成交额_万元": _to_float(vals[37]),
            "换手率": _to_float(vals[38]),
            "PE TTM": _to_float(vals[39]),
            "振幅": _to_float(vals[43]),
            "总市值_亿元": _to_float(vals[44]),
            "流通市值_亿元": _to_float(vals[45]),
            "PB": _to_float(vals[46]),
            "涨停价": _to_float(vals[47]),
            "跌停价": _to_float(vals[48]),
            "量比": _to_float(vals[49]),
            "静态PE": _to_float(vals[52]),
        }
    return result


def fetch_tencent_market_snapshot(code: str) -> dict[str, Any]:
    """Fetch one stock's Tencent snapshot using project-friendly field names."""
    normalized = normalize_stock_code(code)
    return fetch_tencent_quote([normalized]).get(normalized, {"股票代码": normalized})


def fetch_eastmoney_concept_blocks(code: str) -> dict[str, Any]:
    """Fetch mixed industry/concept/region boards for one stock from Eastmoney slist."""
    normalized = normalize_stock_code(code)
    params = {
        "fltt": "2",
        "invt": "2",
        "secid": f"{eastmoney_market_code(normalized)}.{normalized}",
        "spt": "3",
        "pi": "0",
        "pz": "200",
        "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        data = eastmoney_get(
            "https://push2.eastmoney.com/api/qt/slist/get",
            params=params,
            headers=headers,
        ).json()
    except Exception as exc:
        logger.warning("Eastmoney concept block request failed: %s %s", normalized, exc)
        return {"股票代码": normalized, "total": 0, "boards": [], "concept_tags": []}

    diff = (data.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = [
        {
            "name": item.get("f14", ""),
            "code": item.get("f12", ""),
            "change_pct": _to_float(item.get("f3")),
            "lead_stock": item.get("f128", ""),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return {
        "股票代码": normalized,
        "total": len(boards),
        "boards": boards,
        "concept_tags": [board["name"] for board in boards if board.get("name")],
    }


def fetch_eastmoney_industry_comparison(top_n: int = 20) -> dict[str, Any]:
    """Fetch Eastmoney industry board ranking with up/down stock counts."""
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f106,f128,f136,f140,f141,f207",
    }
    try:
        data = eastmoney_get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params=params,
            headers={"User-Agent": UA},
        ).json()
    except Exception as exc:
        logger.warning("Eastmoney industry comparison request failed: %s", exc)
        return {"top": [], "bottom": [], "total": 0}

    items = (data.get("data") or {}).get("diff") or []
    rows = [
        {
            "rank": index + 1,
            "name": item.get("f14", ""),
            "code": item.get("f12", ""),
            "change_pct": _to_float(item.get("f3")),
            "up_count": _to_int(item.get("f104")),
            "down_count": _to_int(item.get("f105")),
            "flat_count": _to_int(item.get("f106")),
            "leader_code": item.get("f128", ""),
            "leader_name": item.get("f140", ""),
            "leader_change": _to_float(item.get("f136")),
        }
        for index, item in enumerate(items)
        if isinstance(item, dict)
    ]
    return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}


def fetch_eastmoney_stock_fund_flow_120d(code: str) -> list[dict[str, Any]]:
    """Fetch daily stock fund-flow rows for the latest 120 trading days."""
    normalized = normalize_stock_code(code)
    params = {
        "secid": f"{eastmoney_market_code(normalized)}.{normalized}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        data = eastmoney_get(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params=params,
            headers=headers,
        ).json()
    except Exception as exc:
        logger.warning("Eastmoney stock fund-flow request failed: %s %s", normalized, exc)
        return []

    klines = (data.get("data") or {}).get("klines") or []
    return parse_eastmoney_fund_flow_klines(klines)


def parse_eastmoney_fund_flow_klines(klines: list[str]) -> list[dict[str, Any]]:
    """Parse Eastmoney fund-flow kline strings."""
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append(
            {
                "date": parts[0],
                "main_net": _to_float(parts[1]),
                "small_net": _to_float(parts[2]),
                "mid_net": _to_float(parts[3]),
                "large_net": _to_float(parts[4]),
                "super_net": _to_float(parts[5]),
            }
        )
    return rows


def fetch_supplemental_stock_data(code: str) -> dict[str, Any]:
    """Collect optional supplemental data without mutating the main pipeline context."""
    normalized = normalize_stock_code(code)
    return {
        "股票代码": normalized,
        "tencent_market_snapshot": fetch_tencent_market_snapshot(normalized),
        "eastmoney_concept_blocks": fetch_eastmoney_concept_blocks(normalized),
        "eastmoney_fund_flow_120d": fetch_eastmoney_stock_fund_flow_120d(normalized),
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in {"", "-", "--", "None"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None
