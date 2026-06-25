"""本模块负责抓取巨潮等官方公告信息，第一版只保留标题、日期、链接、来源和分类。公告按分析日期过滤，正文解析留待后续扩展。"""

from datetime import date, timedelta
from typing import Any
import pandas as pd
from src.utils.akshare_patch import ensure_akshare_patch
from src.utils.date_utils import parse_optional_date
from src.utils.logger import get_logger

logger = get_logger(__name__)
RISK_KEYWORDS = ["问询函", "监管函", "减持", "质押", "资产减值", "诉讼", "担保"]
ANNOUNCEMENT_TYPES = ["年报", "半年报", "季报", "业绩预告", "业绩快报", "重大合同", "投资者关系", "问询函", "监管函", "减持", "股权质押", "限售股解禁", "定增", "可转债", "资产减值", "诉讼仲裁", "对外担保", "关联交易", "股权激励"]


def fetch_announcements(code: str, analysis_date: date) -> list[dict[str, Any]]:
    ensure_akshare_patch(required=False)
    import akshare as ak
    df = _call_cninfo(ak, code, (analysis_date - timedelta(days=365 * 3)).strftime("%Y%m%d"), analysis_date.strftime("%Y%m%d"))
    records = []
    for row in df.to_dict("records") if not df.empty else []:
        item = _normalize_announcement(code, row, analysis_date)
        if item["是否在分析日期之前披露"]:
            records.append(item)
    return records


def _call_cninfo(ak: Any, code: str, start_date: str, end_date: str) -> pd.DataFrame:
    func = ak.stock_zh_a_disclosure_report_cninfo
    options = [
        {"symbol": code, "market": "沪深京", "keyword": "", "category": "", "start_date": start_date, "end_date": end_date},
        {"symbol": "全部", "market": "沪深京", "keyword": code, "category": "", "start_date": start_date, "end_date": end_date},
        {"symbol": code, "start_date": start_date, "end_date": end_date},
    ]
    for kwargs in options:
        try:
            result = func(**kwargs)
            df = result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
            if not df.empty:
                return df
        except Exception as exc:
            logger.info("巨潮公告接口参数尝试失败：%s 错误=%s", kwargs, exc)
    return pd.DataFrame()


def _normalize_announcement(code: str, row: dict[str, Any], analysis_date: date) -> dict[str, Any]:
    title = _first_present(row, ["公告标题", "公告名称", "标题", "announcementTitle"]) or ""
    ann_date = parse_optional_date(_first_present(row, ["公告时间", "公告日期", "披露日期", "announcementTime"]))
    risk_level = "medium" if any(key in str(title) for key in RISK_KEYWORDS) else "low"
    return {
        "股票代码": code,
        "公告标题": title,
        "公告日期": ann_date.isoformat() if ann_date else None,
        "公告类型": _classify_type(str(title)),
        "公告来源": "巨潮资讯",
        "公告链接": _first_present(row, ["公告链接", "链接", "adjunctUrl", "url"]),
        "是否官方来源": True,
        "是否在分析日期之前披露": ann_date is None or ann_date <= analysis_date,
        "摘要": None,
        "风险等级": risk_level,
    }


def _first_present(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _classify_type(title: str) -> str:
    return next((item for item in ANNOUNCEMENT_TYPES if item in title), "其他公告")
