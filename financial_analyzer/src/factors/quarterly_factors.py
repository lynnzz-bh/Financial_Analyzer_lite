"""将财报累计口径报告期拆分为独立单季度 QTR 结果。"""

from typing import Any
import math
import re

PERIOD_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "A": 4}
QTR_PERIOD_CODE = {"Q1": "Q1", "H1": "Q2", "Q3": "Q3", "A": "Q4"}
PREVIOUS_YTD_PERIOD = {"Q1": None, "H1": "Q1", "Q3": "H1", "A": "Q3"}
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_UNAVAILABLE = "unavailable"


def split_ytd_reports_to_quarters(rows: list[dict[str, Any]], fields: list[str], report_name: str = "financial_report") -> dict[str, Any]:
    """Split cumulative Q1/H1/Q3/A report rows into independent quarter values."""
    valid_rows, warnings = _dedupe_and_sort_rows(rows, report_name)
    row_by_period = {item["report_period"]: item["row"] for item in valid_rows}
    quarters = [_build_quarter_result(item["row"], item["year"], item["period_code"], fields, row_by_period, report_name) for item in valid_rows]

    all_warnings = warnings + [warning for quarter in quarters for warning in quarter["warnings"]]
    status = _overall_status(quarters, all_warnings)
    return {
        "status": status,
        "quarters": quarters,
        "warnings": all_warnings,
    }


def _dedupe_and_sort_rows(rows: list[dict[str, Any]], report_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    by_period: dict[str, dict[str, Any]] = {}
    duplicate_periods: set[str] = set()
    for row in rows or []:
        raw_period = row.get("report_period")
        parsed = _parse_period(raw_period)
        if parsed is None:
            warnings.append(_warning("invalid_period", report_name, raw_period, f"无法解析报告期：{raw_period}"))
            continue
        year, period_code = parsed
        report_period = f"{year}{period_code}"
        if report_period in by_period:
            duplicate_periods.add(report_period)
        by_period[report_period] = {
            "row": row,
            "report_period": report_period,
            "year": year,
            "period_code": period_code,
            "sort_key": (year, PERIOD_ORDER[period_code]),
        }

    for report_period in sorted(duplicate_periods, key=_period_sort_key_from_text):
        warnings.append(_warning("duplicate_period", report_name, report_period, f"报告期重复，使用最后一条：{report_period}"))
    return sorted(by_period.values(), key=lambda item: item["sort_key"]), warnings


def _build_quarter_result(
    row: dict[str, Any],
    year: int,
    period_code: str,
    fields: list[str],
    row_by_period: dict[str, dict[str, Any]],
    report_name: str,
) -> dict[str, Any]:
    source_period = f"{year}{period_code}"
    qtr_period = f"{year}{QTR_PERIOD_CODE[period_code]}"
    previous_code = PREVIOUS_YTD_PERIOD[period_code]
    previous_period = f"{year}{previous_code}" if previous_code else None
    depends_on = [source_period] if previous_period is None else [source_period, previous_period]
    quarter_warnings: list[dict[str, Any]] = []

    if previous_period is not None and previous_period not in row_by_period:
        values = {_qtr_field_name(field): None for field in fields}
        quarter_warnings.append(
            _missing_dependency_warning(report_name, source_period, qtr_period, previous_period)
        )
        return {
            "source_period": source_period,
            "qtr_period": qtr_period,
            "depends_on": depends_on,
            "values": values,
            "status": STATUS_UNAVAILABLE,
            "warnings": quarter_warnings,
        }

    previous_row = row_by_period.get(previous_period, {}) if previous_period else {}
    values = {_qtr_field_name(field): _qtr_value(row, previous_row, field, previous_period) for field in fields}
    status = _quarter_status(values, quarter_warnings)
    return {
        "source_period": source_period,
        "qtr_period": qtr_period,
        "depends_on": depends_on,
        "values": values,
        "status": status,
        "warnings": quarter_warnings,
    }


def _qtr_value(row: dict[str, Any], previous_row: dict[str, Any], field: str, previous_period: str | None) -> float | None:
    current = _to_float(row.get(field))
    if current is None:
        return None
    if previous_period is None:
        return current
    previous = _to_float(previous_row.get(field))
    if previous is None:
        return None
    return current - previous


def _quarter_status(values: dict[str, float | None], warnings: list[dict[str, Any]]) -> str:
    if not values or all(value is None for value in values.values()):
        return STATUS_UNAVAILABLE
    if warnings or any(value is None for value in values.values()):
        return STATUS_WARNING
    return STATUS_OK


def _overall_status(quarters: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    has_computable_quarter = any(any(value is not None for value in quarter["values"].values()) for quarter in quarters)
    if not has_computable_quarter:
        return STATUS_UNAVAILABLE
    if warnings or any(quarter["status"] != STATUS_OK for quarter in quarters):
        return STATUS_WARNING
    return STATUS_OK


def _parse_period(value: Any) -> tuple[int, str] | None:
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|A)", str(value or "").strip())
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _period_sort_key_from_text(period: str) -> tuple[int, int]:
    parsed = _parse_period(period)
    if parsed is None:
        return (9999, 99)
    year, period_code = parsed
    return (year, PERIOD_ORDER[period_code])


def _qtr_field_name(field: str) -> str:
    return f"{field}_QTR"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _warning(issue_type: str, report_name: str, source_period: Any, message: str) -> dict[str, Any]:
    return {
        "level": STATUS_WARNING,
        "issue_type": issue_type,
        "report_name": report_name,
        "source_period": source_period,
        "message": message,
    }


def _missing_dependency_warning(report_name: str, source_period: str, qtr_period: str, missing_period: str) -> dict[str, Any]:
    warning = _warning(
        "missing_dependency",
        report_name,
        source_period,
        f"{source_period} 拆分 {qtr_period} 缺少依赖期：{missing_period}",
    )
    warning["qtr_period"] = qtr_period
    warning["missing_period"] = missing_period
    return warning
