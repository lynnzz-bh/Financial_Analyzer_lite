"""本模块是命令行入口，负责解析股票代码、分析日期和分析目标，并串联抓取、清洗、指标、评分、LLM 审核和报告生成全流程。"""

from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sys
import pandas as pd
from config.settings import OUTPUT_DIR, PROCESSED_DIR, PROJECT_VERSION, RAW_DIR
from src.anti_dependency.anti_dependency_mode import run_anti_dependency_mode
from src.data_cleaner.financial_cleaner import build_financial_cleaning_audit, clean_financial_reports
from src.data_fetcher.akshare_fetcher import fetch_financial_reports, fetch_stock_info
from src.data_fetcher.announcement_fetcher import fetch_announcements
from src.data_fetcher.business_fetcher import build_business_context, fetch_business_source_tables
from src.data_fetcher.market_fetcher import fetch_market_data
from src.factors.financial_factors import compute_financial_factors, enrich_market_data_with_report_valuations
from src.factors.metric_registry import build_metric_provenance
from src.factors.risk_flags import generate_risk_flags
from src.llm.llm_pipeline import run_llm_pipeline
from src.report.report_generator import generate_data_failure_report, generate_markdown_report
from src.scoring.financial_score import score_financials
from src.utils.akshare_patch import AksharePatchRequiredError
from src.utils.data_quality import inspect_business_context_quality, inspect_cleaned_reports_quality, inspect_raw_fetch_quality, summarize_quality_status
from src.utils.date_utils import parse_analysis_date, validate_stock_code
from src.utils.logger import get_logger
from src.utils.storage import save_dataframe, save_json

logger = get_logger(__name__)
OUTPUT_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
KEEP_LATEST_OUTPUT_ONLY = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Financial Analyzer {PROJECT_VERSION}")
    parser.add_argument("--code", required=True, help="6 位 A 股股票代码，例如 600519")
    parser.add_argument("--date", required=True, help="分析日期，格式 YYYY-MM-DD")
    parser.add_argument("--mode", required=True, help="分析目标，例如 买入前检查")
    parser.add_argument("--anti-dependency", action="store_true", help="启用 Anti-dependency Mode：先人工判断，再解锁 Qwen 对比复盘")
    return parser.parse_args()


def cleanup_old_output_files(code: str, output_dir: Path = OUTPUT_DIR) -> list[Path]:
    if not output_dir.exists():
        return []

    code_prefix = f"{code}_"
    dated_files: list[tuple[date, Path]] = []
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        if not path.name.startswith(code_prefix):
            continue
        if "_anti_dependency_review" in path.stem:
            continue
        match = OUTPUT_DATE_PATTERN.search(path.name)
        if not match:
            continue
        try:
            output_date = date.fromisoformat(match.group(0))
        except ValueError:
            continue
        dated_files.append((output_date, path))

    if not dated_files:
        return []

    latest_date = max(output_date for output_date, _ in dated_files)
    deleted_paths: list[Path] = []
    for output_date, path in dated_files:
        if output_date >= latest_date:
            continue
        path.unlink()
        deleted_paths.append(path)
    return deleted_paths


def cleanup_output_if_requested(enabled: bool, code: str) -> None:
    if not enabled:
        return
    deleted_paths = cleanup_old_output_files(code)
    logger.info("已清理 data/output 中早于最新日期的文件：%s 个", len(deleted_paths))


def main() -> int:
    # 终端输入格式：先进入 financial_analyzer 目录，再执行 python main.py --code <6位A股代码> --date <YYYY-MM-DD> --mode "<分析内容>" [--anti-dependency]
    args = parse_args()
    try:
        code = validate_stock_code(args.code)
        analysis_date = parse_analysis_date(args.date)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    try:
        logger.info("开始分析 %s，分析日期 %s，目标：%s", code, analysis_date, args.mode)
        stock_info = fetch_stock_info(code)
        market_data = fetch_market_data(code, analysis_date)
        raw_market_data = dict(market_data)
        reports = fetch_financial_reports(code)
        announcements = fetch_announcements(code, analysis_date)
        data_quality_warnings = inspect_raw_fetch_quality(stock_info, market_data, reports)
        for warning in data_quality_warnings:
            logger.warning("数据质量警告：%s | %s | %s", warning["stage"], warning["source"], warning["message"])
        raw_file_paths = {
            "stock_info": str(save_json(stock_info, RAW_DIR / f"{code}_stock_info.json")),
            "market_data": str(save_json(market_data, RAW_DIR / f"{code}_market_data.json")),
            "announcements": str(save_json(announcements, RAW_DIR / f"{code}_announcements.json")),
        }
        raw_report_paths: dict[str, str] = {}
        for report_name, df in reports.items():
            if isinstance(df, pd.DataFrame):
                raw_report_paths[report_name] = str(save_dataframe(df, RAW_DIR / f"{code}_{report_name}.csv"))
        data_quality_status = summarize_quality_status(data_quality_warnings)
        if data_quality_status == "fatal":
            save_json(data_quality_warnings, PROCESSED_DIR / f"{code}_data_quality_warnings.json")
            report_path = generate_data_failure_report(_failure_context(code, args.mode, analysis_date, stock_info, market_data, data_quality_warnings, data_quality_status))
            logger.error("数据质量 fatal，已生成失败报告：%s", report_path)
            cleanup_output_if_requested(KEEP_LATEST_OUTPUT_ONLY, code)
            return 0
        cleaning_audit = build_financial_cleaning_audit(reports)
        cleaned_reports = clean_financial_reports(reports, analysis_date)
        data_quality_warnings.extend(inspect_cleaned_reports_quality(cleaned_reports))
        for warning in data_quality_warnings:
            if warning["stage"] == "cleaned_data":
                logger.warning("数据质量警告：%s | %s | %s", warning["stage"], warning["source"], warning["message"])
        market_data = enrich_market_data_with_report_valuations(market_data, cleaned_reports)
        data_quality_status = summarize_quality_status(data_quality_warnings)
        processed_cleaned_reports_path = PROCESSED_DIR / f"{code}_cleaned_reports.json"
        processed_market_data_path = PROCESSED_DIR / f"{code}_market_data.json"
        save_json(cleaned_reports, processed_cleaned_reports_path)
        save_json(market_data, processed_market_data_path)
        if data_quality_status == "fatal":
            save_json(data_quality_warnings, PROCESSED_DIR / f"{code}_data_quality_warnings.json")
            report_path = generate_data_failure_report(_failure_context(code, args.mode, analysis_date, stock_info, market_data, data_quality_warnings, data_quality_status))
            logger.error("数据质量 fatal，已生成失败报告：%s", report_path)
            cleanup_output_if_requested(KEEP_LATEST_OUTPUT_ONLY, code)
            return 0
        business_source_tables = fetch_business_source_tables(code, analysis_date)
        for table_name, df in business_source_tables.items():
            if isinstance(df, pd.DataFrame):
                save_dataframe(df, RAW_DIR / f"{code}_{table_name}.csv")
        business_context = build_business_context(business_source_tables)
        data_quality_warnings.extend(inspect_business_context_quality(business_context))
        save_json(business_context, PROCESSED_DIR / f"{code}_business_context.json")
        data_quality_status = summarize_quality_status(data_quality_warnings)
        if args.anti_dependency:
            save_json(data_quality_warnings, PROCESSED_DIR / f"{code}_data_quality_warnings.json")
            record = run_anti_dependency_mode(
                code=code,
                mode=args.mode,
                analysis_date=analysis_date,
                stock_info=stock_info,
                market_data=raw_market_data,
                reports=reports,
                announcements=announcements,
                data_quality_warnings=data_quality_warnings,
            )
            logger.info("Anti-dependency 记录已生成：%s", PROCESSED_DIR / f"{code}_anti_dependency_record.json")
            logger.info("Anti-dependency 复盘已生成：%s", record.get("output_path"))
            return 0
        factors = compute_financial_factors(cleaned_reports, market_data)
        financial_factors_path = PROCESSED_DIR / f"{code}_financial_factors.json"
        metric_provenance_path = PROCESSED_DIR / f"{code}_metric_provenance.json"
        source_audit = _build_source_audit(
            code=code,
            analysis_date=analysis_date,
            cleaning_audit=cleaning_audit,
            market_data=market_data,
            raw_file_paths=raw_file_paths,
            raw_report_paths=raw_report_paths,
            processed_cleaned_reports_path=processed_cleaned_reports_path,
            processed_market_data_path=processed_market_data_path,
            financial_factors_path=financial_factors_path,
            metric_provenance_path=metric_provenance_path,
        )
        metric_provenance = build_metric_provenance(cleaned_reports, market_data, factors, source_audit=source_audit)
        risk_flags = generate_risk_flags(factors, cleaned_reports, announcements)
        financial_score = score_financials(factors)
        save_json(factors, financial_factors_path)
        save_json(metric_provenance, metric_provenance_path)
        save_json(risk_flags, PROCESSED_DIR / f"{code}_risk_flags.json")
        save_json(financial_score, PROCESSED_DIR / f"{code}_financial_score.json")
        save_json(data_quality_warnings, PROCESSED_DIR / f"{code}_data_quality_warnings.json")
        context = {
            "code": code,
            "mode": args.mode,
            "analysis_date": analysis_date.isoformat(),
            "stock_info": stock_info,
            "market_data": market_data,
            "cleaned_reports": cleaned_reports,
            "financial_factors": factors,
            "metric_provenance": metric_provenance,
            "risk_flags": risk_flags,
            "financial_score": financial_score,
            "announcements": announcements,
            "data_quality_warnings": data_quality_warnings,
            "data_quality_status": data_quality_status,
            "business_context": business_context,
        }
        context["llm_results"] = run_llm_pipeline(context)
        save_json(context["llm_results"], PROCESSED_DIR / f"{code}_llm_results.json")
        report_path = generate_markdown_report(context)
        logger.info("报告已生成：%s", report_path)
        cleanup_output_if_requested(KEEP_LATEST_OUTPUT_ONLY, code)
        logger.info("核心结果：综合评分 %s/100，可信度 %s，风险红旗 %s 条", financial_score.get("total_score"), financial_score.get("score_confidence"), len(risk_flags))
        return 0
    except AksharePatchRequiredError as exc:
        logger.error("%s", exc)
        logger.error("请复制 .env.example 为 .env，并填写 AKSHARE_PROXY_TOKEN 后重试。")
        return 2
    except Exception as exc:
        logger.exception("流程执行失败：%s", exc)
        return 3


def _failure_context(
    code: str,
    mode: str,
    analysis_date: date,
    stock_info: dict,
    market_data: dict,
    data_quality_warnings: list[dict[str, str]],
    data_quality_status: str,
) -> dict:
    return {
        "code": code,
        "mode": mode,
        "analysis_date": analysis_date.isoformat(),
        "stock_info": stock_info,
        "market_data": market_data,
        "data_quality_warnings": data_quality_warnings,
        "data_quality_status": data_quality_status,
    }


def _build_source_audit(
    code: str,
    analysis_date: date,
    cleaning_audit: dict[str, dict[str, object]],
    market_data: dict,
    raw_file_paths: dict[str, str],
    raw_report_paths: dict[str, str],
    processed_cleaned_reports_path: Path,
    processed_market_data_path: Path,
    financial_factors_path: Path,
    metric_provenance_path: Path,
) -> dict[str, object]:
    data_sources: dict[str, object] = {
        "stock_info": {
            "status": "ok" if raw_file_paths.get("stock_info") else "missing",
            "fetcher_function": "akshare_fetcher.fetch_stock_info",
            "raw_path": raw_file_paths.get("stock_info"),
            "processed_path": None,
            "field_mappings": {},
        },
        "market_data": {
            "status": "ok" if market_data else "missing",
            "fetcher_function": "market_fetcher.fetch_market_data",
            "raw_path": raw_file_paths.get("market_data"),
            "processed_path": str(processed_market_data_path),
            "field_mappings": _market_field_mappings(market_data),
        },
    }
    for report_name in ("income_statement", "balance_sheet", "cash_flow"):
        report_audit = cleaning_audit.get(report_name, {})
        data_sources[report_name] = {
            "status": report_audit.get("status", "missing"),
            "fetcher_function": "akshare_fetcher.fetch_financial_reports",
            "raw_path": raw_report_paths.get(report_name),
            "processed_path": str(processed_cleaned_reports_path),
            "field_mappings": report_audit.get("field_mappings", {}),
        }
    return {
        "status": "ok" if any(source.get("status") == "ok" for source in data_sources.values() if isinstance(source, dict)) else "missing",
        "code": code,
        "analysis_date": analysis_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": data_sources,
        "file_paths": {
            "raw": raw_file_paths | {"financial_reports": raw_report_paths},
            "processed": {
                "cleaned_reports": str(processed_cleaned_reports_path),
                "market_data": str(processed_market_data_path),
                "financial_factors": str(financial_factors_path),
                "metric_provenance": str(metric_provenance_path),
            },
        },
    }


def _market_field_mappings(market_data: dict) -> dict[str, dict[str, object]]:
    return {
        str(field): {
            "standard_field": str(field),
            "aliases": [str(field)],
            "source_field": str(field),
            "status": "ok" if value is not None else "missing",
        }
        for field, value in market_data.items()
    }


if __name__ == "__main__":
    sys.exit(main())
