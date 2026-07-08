"""本模块实现 Anti-dependency Mode：先人工判断，再解锁 Qwen 对比复盘。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd

from config.settings import OUTPUT_DIR, PROCESSED_DIR
from src.data_cleaner.financial_cleaner import clean_financial_reports
from src.factors.financial_factors import compute_financial_factors
from src.factors.risk_flags import generate_risk_flags
from src.llm.prompts import QWEN_ANTI_DEPENDENCY_PROMPT
from src.llm.qwen_client import call_qwen
from src.scoring.financial_score import score_financials
from src.utils.data_quality import inspect_cleaned_reports_quality
from src.utils.storage import save_json

InputFunc = Callable[[str], str]
OutputFunc = Callable[[str], None]
DisplayKind = Literal["date", "money_yi", "text"]
RAW_PREVIEW_COLUMNS = {
    "income_statement": [
        ("REPORT_DATE", "报告期", "date"),
        ("NOTICE_DATE", "披露日", "date"),
        ("TOTAL_OPERATE_INCOME", "营业收入", "money_yi"),
        ("TOTAL_OPERATE_COST", "营业成本", "money_yi"),
        ("OPERATE_PROFIT", "营业利润", "money_yi"),
        ("PARENT_NETPROFIT", "归母净利润", "money_yi"),
        ("DEDUCT_PARENT_NETPROFIT", "扣非归母净利润", "money_yi"),
    ],
    "balance_sheet": [
        ("REPORT_DATE", "报告期", "date"),
        ("NOTICE_DATE", "披露日", "date"),
        ("TOTAL_ASSETS", "总资产", "money_yi"),
        ("TOTAL_LIABILITIES", "总负债", "money_yi"),
        ("PARENT_EQUITY", "归母权益", "money_yi"),
        ("MONETARYFUNDS", "货币资金", "money_yi"),
        ("ACCOUNTS_RECE", "应收账款", "money_yi"),
        ("INVENTORY", "存货", "money_yi"),
        ("SHORT_LOAN", "短期借款", "money_yi"),
        ("LONG_LOAN", "长期借款", "money_yi"),
    ],
    "cash_flow": [
        ("REPORT_DATE", "报告期", "date"),
        ("NOTICE_DATE", "披露日", "date"),
        ("NETCASH_OPERATE", "经营现金流净额", "money_yi"),
        ("SALES_SERVICES", "销售收现", "money_yi"),
        ("CONSTRUCT_LONG_ASSET", "购建长期资产支出", "money_yi"),
        ("NETCASH_INVEST", "投资现金流净额", "money_yi"),
        ("NETCASH_FINANCE", "筹资现金流净额", "money_yi"),
    ],
}


def start_anti_dependency_mode(
    *,
    stock_info: dict[str, Any],
    market_data: dict[str, Any],
    reports: dict[str, pd.DataFrame],
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> dict[str, str]:
    raw_snapshot = build_raw_data_snapshot(stock_info, market_data, reports)
    output_func(raw_snapshot)
    human_judgment = collect_human_judgment(input_func=input_func, output_func=output_func)
    return {"raw_data_snapshot": raw_snapshot, "human_judgment": human_judgment}


def run_anti_dependency_mode(
    *,
    code: str,
    mode: str,
    analysis_date: date,
    stock_info: dict[str, Any],
    market_data: dict[str, Any],
    reports: dict[str, pd.DataFrame],
    announcements: list[dict[str, Any]],
    data_quality_warnings: list[dict[str, str]],
    normal_report_path: str | Path | None = None,
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> dict[str, Any]:
    session = start_anti_dependency_mode(
        stock_info=stock_info,
        market_data=market_data,
        reports=reports,
        input_func=input_func,
        output_func=output_func,
    )

    cleaned_reports = clean_financial_reports(reports, analysis_date)
    if any(item.get("stage") == "cleaned_data" for item in data_quality_warnings):
        all_warnings = list(data_quality_warnings)
    else:
        all_warnings = [*data_quality_warnings, *inspect_cleaned_reports_quality(cleaned_reports)]
    factors = compute_financial_factors(cleaned_reports, market_data)
    risk_flags = generate_risk_flags(factors, cleaned_reports, announcements)
    financial_score = score_financials(factors)
    context = {
        "code": code,
        "mode": mode,
        "analysis_date": analysis_date.isoformat(),
        "stock_info": stock_info,
        "market_data": market_data,
        "cleaned_reports": cleaned_reports,
        "financial_factors": factors,
        "risk_flags": risk_flags,
        "financial_score": financial_score,
        "announcements": announcements,
        "data_quality_warnings": all_warnings,
    }
    return generate_anti_dependency_review(
        code=code,
        mode=mode,
        analysis_date=analysis_date,
        raw_data_snapshot=session["raw_data_snapshot"],
        human_judgment=session["human_judgment"],
        context=context,
        normal_report_path=normal_report_path,
    )


def generate_anti_dependency_review(
    *,
    code: str,
    mode: str,
    analysis_date: date | str,
    raw_data_snapshot: str,
    human_judgment: str,
    context: dict[str, Any],
    normal_report_path: str | Path | None = None,
) -> dict[str, Any]:
    analysis_date_text = analysis_date.isoformat() if isinstance(analysis_date, date) else str(analysis_date)
    qwen_prompt = QWEN_ANTI_DEPENDENCY_PROMPT.format(
        code=code,
        analysis_date=analysis_date_text,
        mode=mode,
        human_judgment=human_judgment,
        raw_data_snapshot=raw_data_snapshot,
        financial_factors=_to_json(context.get("financial_factors", {})),
        financial_score=_to_json(context.get("financial_score", {})),
        risk_flags=_to_json(context.get("risk_flags", [])),
        data_quality_warnings=_to_json(context.get("data_quality_warnings", [])),
    )
    qwen_comparison = call_qwen(qwen_prompt)
    record = {
        "code": code,
        "mode": mode,
        "analysis_date": analysis_date_text,
        "anti_dependency_mode": True,
        "human_judgment": human_judgment,
        "raw_data_snapshot": raw_data_snapshot,
        "normal_report_path": str(normal_report_path) if normal_report_path else None,
        "cleaned_reports": context.get("cleaned_reports", {}),
        "financial_factors": context.get("financial_factors", {}),
        "risk_flags": context.get("risk_flags", []),
        "financial_score": context.get("financial_score", {}),
        "data_quality_warnings": context.get("data_quality_warnings", []),
        "qwen_comparison": qwen_comparison,
    }
    output_path = save_anti_dependency_markdown(record)
    record["output_path"] = str(output_path)
    save_json(record, PROCESSED_DIR / f"{code}_anti_dependency_record.json")
    return record


def collect_human_judgment(input_func: InputFunc = input, output_func: OutputFunc = print) -> str:
    output_func("")
    output_func("请先写下你的人工判断。可多行输入，单独输入 END 提交。")
    lines: list[str] = []
    while True:
        line = input_func("> ")
        if line.strip().upper() == "END":
            judgment = "\n".join(lines).strip()
            if judgment:
                return judgment
            output_func("人工判断不能为空。请先写判断，再输入 END。")
            continue
        lines.append(line)


def build_raw_data_snapshot(
    stock_info: dict[str, Any],
    market_data: dict[str, Any],
    reports: dict[str, pd.DataFrame],
    max_rows: int = 5,
) -> str:
    lines = [
        "# Anti-dependency Mode 原始数据摘要",
        "",
        "以下只展示原始抓取数据摘要。请先独立写判断，提交后才会解锁系统指标、评分和 Qwen 对比。",
        "",
        "## 股票信息",
        _dict_lines(stock_info, ["股票代码", "股票简称", "行业", "上市时间", "总股本", "流通股", "error"]),
        "",
        "## 行情数据",
        _dict_lines(market_data, ["股票代码", "股票简称", "最新收盘价", "总市值", "流通市值", "PE TTM", "行情源PEG", "PEG", "PB", "行情源PS", "PS", "近20日涨跌幅", "近60日涨跌幅"]),
    ]
    for name, df in reports.items():
        lines.extend(["", f"## 原始财报：{name}", _dataframe_preview(name, df, max_rows)])
    return "\n".join(lines)


def save_anti_dependency_markdown(record: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    code = str(record.get("code"))
    path = OUTPUT_DIR / f"{code}_{record.get('analysis_date')}_anti_dependency_review.md"
    qwen = record.get("qwen_comparison", {})
    content = "\n".join([
        f"# {code} Anti-dependency Review",
        "",
        f"分析日期：{record.get('analysis_date')}",
        f"分析目标：{record.get('mode')}",
        f"综合评分：{record.get('financial_score', {}).get('total_score', 'missing')}/100",
        f"数据可信度：{record.get('financial_score', {}).get('score_confidence', 'unknown')}",
        f"正常报告：{record.get('normal_report_path') or 'missing'}",
        "",
        "## 人工判断前原始数据摘要",
        "",
        _demote_markdown_headings(str(record.get("raw_data_snapshot", ""))),
        "",
        "## 人工判断",
        "",
        str(record.get("human_judgment", "")),
        "",
        "## Qwen 对比复盘",
        "",
        str(qwen.get("content", "")),
        "",
        "## 数据质量警告",
        "",
        _warning_lines(record.get("data_quality_warnings", [])),
        "",
    ])
    path.write_text(content, encoding="utf-8")
    return path


def _dict_lines(data: dict[str, Any], keys: list[str]) -> str:
    rows = [f"- {key}：{_format_dict_value(key, data.get(key, 'missing'))}" for key in keys if key in data or key == "error"]
    return "\n".join(rows) if rows else "无可展示字段。"


def _dataframe_preview(name: str, df: pd.DataFrame, max_rows: int) -> str:
    if df is None or df.empty:
        return "原始数据为空。"
    preview = _sort_preview_rows(df).head(max_rows)
    configured_columns = RAW_PREVIEW_COLUMNS.get(name, [])
    columns = [column for column in configured_columns if column[0] in preview.columns]
    if not columns:
        columns = [(str(column), str(column), "text") for column in preview.columns[:8]]
    return _markdown_table(preview, columns)


def _sort_preview_rows(df: pd.DataFrame) -> pd.DataFrame:
    preview = df.copy()
    if "REPORT_DATE" not in preview.columns:
        return preview
    preview["_anti_dependency_sort_date"] = pd.to_datetime(preview["REPORT_DATE"], errors="coerce")
    return preview.sort_values("_anti_dependency_sort_date", ascending=False, na_position="last").drop(columns=["_anti_dependency_sort_date"])


def _markdown_table(df: pd.DataFrame, columns: list[tuple[str, str, DisplayKind]]) -> str:
    headers = [label for _, label, _ in columns]
    alignments = ["---:" if kind == "money_yi" else "---" for _, _, kind in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(alignments) + " |",
    ]
    for _, row in df.iterrows():
        cells = [_escape_table_cell(_format_cell(row.get(source), kind)) for source, _, kind in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _format_cell(value: Any, kind: DisplayKind) -> str:
    if _is_missing(value):
        return "missing"
    if kind == "money_yi":
        return _fmt_yi_yuan(value)
    if kind == "date":
        return _fmt_date(value)
    return _fmt_plain(value)


def _format_dict_value(key: str, value: Any) -> str:
    if _is_missing(value):
        return "missing"
    if key in {"总股本", "流通股", "总市值", "流通市值"}:
        return _fmt_yi_yuan(value)
    return _fmt_plain(value)


def _fmt_yi_yuan(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return _fmt_plain(value)
    return f"{number / 100000000:.2f}亿元"


def _fmt_date(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if not pd.isna(parsed):
        return parsed.date().isoformat()
    return _fmt_plain(value)


def _fmt_plain(value: Any) -> str:
    if _is_missing(value):
        return "missing"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _demote_markdown_headings(content: str) -> str:
    lines = []
    for line in content.splitlines():
        if line.startswith("#"):
            lines.append(f"##{line}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _warning_lines(warnings: list[dict[str, Any]]) -> str:
    if not warnings:
        return "未发现数据质量警告。"
    return "\n".join(f"- {item.get('level', 'warning')} | {item.get('stage')} | {item.get('source')}：{item.get('message')}" for item in warnings)


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
