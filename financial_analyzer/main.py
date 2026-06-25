"""本模块是命令行入口，负责解析股票代码、分析日期和分析目标，并串联抓取、清洗、指标、评分、LLM 审核和报告生成全流程。"""

from __future__ import annotations
import argparse
import sys
import pandas as pd
from config.settings import PROCESSED_DIR, PROJECT_VERSION, RAW_DIR
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
from src.utils.date_utils import parse_analysis_date, validate_stock_code
from src.utils.logger import get_logger
from src.utils.storage import save_dataframe, save_json

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Financial Analyzer {PROJECT_VERSION}")
    parser.add_argument("--code", required=True, help="6 位 A 股股票代码，例如 600519")
    parser.add_argument("--date", required=True, help="分析日期，格式 YYYY-MM-DD")
    parser.add_argument("--mode", required=True, help="分析目标，例如 买入前检查")
    return parser.parse_args()


def main() -> int:
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
        save_json(stock_info, RAW_DIR / f"{code}_stock_info.json")
        save_json(market_data, RAW_DIR / f"{code}_market_data.json")
        save_json(announcements, RAW_DIR / f"{code}_announcements.json")
        for report_name, df in reports.items():
            if isinstance(df, pd.DataFrame):
                save_dataframe(df, RAW_DIR / f"{code}_{report_name}.csv")
        cleaned_reports = clean_financial_reports(reports, analysis_date)
        factors = compute_financial_factors(cleaned_reports, market_data)
        risk_flags = generate_risk_flags(factors, cleaned_reports, announcements)
        financial_score = score_financials(factors)
        save_json(cleaned_reports, PROCESSED_DIR / f"{code}_cleaned_reports.json")
        save_json(factors, PROCESSED_DIR / f"{code}_financial_factors.json")
        save_json(risk_flags, PROCESSED_DIR / f"{code}_risk_flags.json")
        save_json(financial_score, PROCESSED_DIR / f"{code}_financial_score.json")
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
        }
        context["llm_results"] = run_llm_pipeline(context)
        save_json(context["llm_results"], PROCESSED_DIR / f"{code}_llm_results.json")
        report_path = generate_markdown_report(context)
        logger.info("报告已生成：%s", report_path)
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
