"""本模块是命令行入口，负责解析股票代码、分析日期和分析目标，并串联抓取、清洗、指标、评分、LLM 审核和报告生成全流程。"""

from __future__ import annotations
import argparse
from datetime import date
from pathlib import Path
import re
import sys
import pandas as pd
from config.settings import OUTPUT_DIR, PROCESSED_DIR, PROJECT_VERSION, RAW_DIR
from src.anti_dependency.anti_dependency_mode import run_anti_dependency_mode
from src.data_cleaner.financial_cleaner import clean_financial_reports
from src.data_fetcher.akshare_fetcher import fetch_financial_reports, fetch_stock_info
from src.data_fetcher.announcement_fetcher import fetch_announcements
from src.data_fetcher.market_fetcher import fetch_market_data
from src.factors.financial_factors import compute_financial_factors
from src.factors.risk_flags import generate_risk_flags
from src.llm.llm_pipeline import run_llm_pipeline
from src.report.report_generator import generate_markdown_report
from src.scoring.financial_score import score_financials
from src.utils.akshare_patch import AksharePatchRequiredError
from src.utils.data_quality import inspect_cleaned_reports_quality, inspect_raw_fetch_quality
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
        reports = fetch_financial_reports(code)
        announcements = fetch_announcements(code, analysis_date)
        data_quality_warnings = inspect_raw_fetch_quality(stock_info, market_data, reports)
        for warning in data_quality_warnings:
            logger.warning("数据质量警告：%s | %s | %s", warning["stage"], warning["source"], warning["message"])
        save_json(stock_info, RAW_DIR / f"{code}_stock_info.json")
        save_json(market_data, RAW_DIR / f"{code}_market_data.json")
        save_json(announcements, RAW_DIR / f"{code}_announcements.json")
        for report_name, df in reports.items():
            if isinstance(df, pd.DataFrame):
                save_dataframe(df, RAW_DIR / f"{code}_{report_name}.csv")
        if args.anti_dependency:
            save_json(data_quality_warnings, PROCESSED_DIR / f"{code}_data_quality_warnings.json")
            record = run_anti_dependency_mode(
                code=code,
                mode=args.mode,
                analysis_date=analysis_date,
                stock_info=stock_info,
                market_data=market_data,
                reports=reports,
                announcements=announcements,
                data_quality_warnings=data_quality_warnings,
            )
            logger.info("Anti-dependency 记录已生成：%s", PROCESSED_DIR / f"{code}_anti_dependency_record.json")
            logger.info("Anti-dependency 复盘已生成：%s", record.get("output_path"))
            return 0
        cleaned_reports = clean_financial_reports(reports, analysis_date)
        data_quality_warnings.extend(inspect_cleaned_reports_quality(cleaned_reports))
        for warning in data_quality_warnings:
            if warning["stage"] == "cleaned_data":
                logger.warning("数据质量警告：%s | %s | %s", warning["stage"], warning["source"], warning["message"])
        factors = compute_financial_factors(cleaned_reports, market_data)
        risk_flags = generate_risk_flags(factors, cleaned_reports, announcements)
        financial_score = score_financials(factors)
        save_json(cleaned_reports, PROCESSED_DIR / f"{code}_cleaned_reports.json")
        save_json(factors, PROCESSED_DIR / f"{code}_financial_factors.json")
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
            "risk_flags": risk_flags,
            "financial_score": financial_score,
            "announcements": announcements,
            "data_quality_warnings": data_quality_warnings,
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


if __name__ == "__main__":
    sys.exit(main())
