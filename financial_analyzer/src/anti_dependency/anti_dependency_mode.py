"""本模块实现 Anti-dependency Mode：先人工判断，再解锁 Qwen 对比复盘。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

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
RAW_PREVIEW_COLUMNS = {
    "income_statement": [
        "SECURITY_CODE",
        "SECURITY_NAME_ABBR",
        "REPORT_DATE",
        "NOTICE_DATE",
        "TOTAL_OPERATE_INCOME",
        "TOTAL_OPERATE_COST",
        "OPERATE_PROFIT",
        "PARENT_NETPROFIT",
        "DEDUCT_PARENT_NETPROFIT",
    ],
    "balance_sheet": [
        "SECURITY_CODE",
        "SECURITY_NAME_ABBR",
        "REPORT_DATE",
        "NOTICE_DATE",
        "TOTAL_ASSETS",
        "TOTAL_LIABILITIES",
        "PARENT_EQUITY",
        "MONETARYFUNDS",
        "ACCOUNTS_RECE",
        "INVENTORY",
        "SHORT_LOAN",
        "LONG_LOAN",
    ],
    "cash_flow": [
        "SECURITY_CODE",
        "SECURITY_NAME_ABBR",
        "REPORT_DATE",
        "NOTICE_DATE",
        "NETCASH_OPERATE",
        "SALES_SERVICES",
        "CONSTRUCT_LONG_ASSET",
        "NETCASH_INVEST",
        "NETCASH_FINANCE",
    ],
}


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
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> dict[str, Any]:
    raw_snapshot = build_raw_data_snapshot(stock_info, market_data, reports)
    output_func(raw_snapshot)
    human_judgment = collect_human_judgment(input_func=input_func, output_func=output_func)

    cleaned_reports = clean_financial_reports(reports, analysis_date)
    if any(item.get("stage") == "cleaned_data" for item in data_quality_warnings):
        all_warnings = list(data_quality_warnings)
    else:
        all_warnings = [*data_quality_warnings, *inspect_cleaned_reports_quality(cleaned_reports)]
    factors = compute_financial_factors(cleaned_reports, market_data)
    risk_flags = generate_risk_flags(factors, cleaned_reports, announcements)
    financial_score = score_financials(factors)
    qwen_prompt = QWEN_ANTI_DEPENDENCY_PROMPT.format(
        code=code,
        analysis_date=analysis_date.isoformat(),
        mode=mode,
        human_judgment=human_judgment,
        raw_data_snapshot=raw_snapshot,
        financial_factors=_to_json(factors),
        financial_score=_to_json(financial_score),
        risk_flags=_to_json(risk_flags),
        data_quality_warnings=_to_json(all_warnings),
    )
    qwen_comparison = call_qwen(qwen_prompt)
    record = {
        "code": code,
        "mode": mode,
        "analysis_date": analysis_date.isoformat(),
        "anti_dependency_mode": True,
        "human_judgment": human_judgment,
        "raw_data_snapshot": raw_snapshot,
        "cleaned_reports": cleaned_reports,
        "financial_factors": factors,
        "risk_flags": risk_flags,
        "financial_score": financial_score,
        "data_quality_warnings": all_warnings,
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
        _dict_lines(market_data, ["股票代码", "股票简称", "最新收盘价", "总市值", "流通市值", "PE TTM", "PB", "PS", "近20日涨跌幅", "近60日涨跌幅"]),
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
    rows = [f"- {key}：{data.get(key, 'missing')}" for key in keys if key in data or key == "error"]
    return "\n".join(rows) if rows else "无可展示字段。"


def _dataframe_preview(name: str, df: pd.DataFrame, max_rows: int) -> str:
    if df is None or df.empty:
        return "原始数据为空。"
    columns = [col for col in RAW_PREVIEW_COLUMNS.get(name, []) if col in df.columns]
    preview = df.loc[:, columns].head(max_rows).copy() if columns else df.head(max_rows).copy()
    return preview.to_string(index=False)


def _warning_lines(warnings: list[dict[str, Any]]) -> str:
    if not warnings:
        return "未发现数据质量警告。"
    return "\n".join(f"- {item.get('level', 'warning')} | {item.get('stage')} | {item.get('source')}：{item.get('message')}" for item in warnings)


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
