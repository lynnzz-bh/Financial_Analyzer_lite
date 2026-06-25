"""本模块组织 DeepSeek 分析和 Qwen 审核的两阶段流程。输入均来自 Python 计算和公告摘要，模型结果会保留状态以便报告识别。"""

import json
from typing import Any
from src.llm.deepseek_client import call_deepseek
from src.llm.prompts import DEEPSEEK_FINANCIAL_ANALYSIS_PROMPT, QWEN_AUDIT_PROMPT
from src.llm.qwen_client import call_qwen


def run_llm_pipeline(context: dict[str, Any]) -> dict[str, dict[str, str]]:
    announcement_summary = _announcement_summary(context.get("announcements", []))
    deepseek_prompt = DEEPSEEK_FINANCIAL_ANALYSIS_PROMPT.format(
        stock_info=_to_json(context.get("stock_info", {})),
        analysis_date=context.get("analysis_date"),
        financial_factors=_to_json(context.get("financial_factors", {})),
        financial_score=_to_json(context.get("financial_score", {})),
        risk_flags=_to_json(context.get("risk_flags", [])),
        announcement_summary=announcement_summary,
        market_data=_to_json(context.get("market_data", {})),
    )
    deepseek_result = call_deepseek(deepseek_prompt)
    qwen_prompt = QWEN_AUDIT_PROMPT.format(
        raw_data_summary=_to_json({"stock_info": context.get("stock_info", {}), "financial_factors": context.get("financial_factors", {}), "financial_score": context.get("financial_score", {})}),
        deepseek_report=deepseek_result["content"],
        risk_flags=_to_json(context.get("risk_flags", [])),
        announcement_summary=announcement_summary,
    )
    return {"deepseek": deepseek_result, "qwen": call_qwen(qwen_prompt)}


def _announcement_summary(announcements: list[dict[str, Any]]) -> str:
    if not announcements:
        return "无可用公告摘要。"
    return "\n".join(f"- {item.get('公告日期') or '日期缺失'} | {item.get('公告类型')} | {item.get('公告标题')}" for item in announcements[:20])


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
