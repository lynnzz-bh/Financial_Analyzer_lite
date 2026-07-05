"""本模块负责日期和股票代码相关的基础校验，包括分析日期解析、股票代码合法性检查、报告期标准化和文件名日期格式处理。"""

from datetime import date, datetime
import re

SUPPORTED_MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002")


def parse_analysis_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"分析日期格式错误，应为 YYYY-MM-DD：{value}") from exc


def validate_stock_code(code: str) -> str:
    clean_code = code.strip()
    if not re.fullmatch(r"\d{6}", clean_code):
        raise ValueError(f"股票代码必须为 6 位数字：{code}")
    if not is_supported_main_board_stock(clean_code):
        raise ValueError(
            f"暂不支持该股票代码：{code}。当前仅支持 A 股主板普通股票，"
            "代码需以 600/601/603/605/000/001/002 开头。"
        )
    return clean_code


def is_supported_main_board_stock(code: str) -> bool:
    return any(code.startswith(prefix) for prefix in SUPPORTED_MAIN_BOARD_PREFIXES)


def normalize_report_period(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) < 8:
        return text or None
    year, month, day = digits[:4], digits[4:6], digits[6:8]
    if month == "03" and day == "31":
        return f"{year}Q1"
    if month == "06" and day == "30":
        return f"{year}H1"
    if month == "09" and day == "30":
        return f"{year}Q3"
    if month == "12" and day == "31":
        return f"{year}A"
    return f"{year}-{month}-{day}"


def parse_optional_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None
