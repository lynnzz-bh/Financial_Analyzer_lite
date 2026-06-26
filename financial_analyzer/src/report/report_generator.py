"""本模块负责把结构化结果生成 Markdown 财务分析简报。报告明确展示事实、推断和风险提示，并将最终文件保存到 data/output。"""

from pathlib import Path
from typing import Any
import re
from config.settings import OUTPUT_DIR, PROJECT_VERSION


def generate_markdown_report(context: dict[str, Any]) -> Path:
    stock_info, market_data, score = context.get("stock_info", {}), context.get("market_data", {}), context.get("financial_score", {})
    code = str(stock_info.get("股票代码") or context.get("code"))
    name = str(market_data.get("股票简称") or stock_info.get("股票简称") or "未知简称")
    content = _build_report(context, code, name, _rating(score.get("total_score")))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / _safe_filename(f"{code}_{name}_{context.get('analysis_date')}_财务分析简报.md")
    path.write_text(content, encoding="utf-8")
    return path


def _build_report(context: dict[str, Any], code: str, name: str, rating: str) -> str:
    score, factors, risks = context.get("financial_score", {}), context.get("financial_factors", {}), context.get("risk_flags", [])
    llm = context.get("llm_results", {})
    lines = [
        f"# {code} {name} 财务分析简报", "", f"版本：{PROJECT_VERSION}", f"分析日期：{context.get('analysis_date')}", f"分析目标：{context.get('mode')}", f"数据可信度：{score.get('score_confidence', 'unknown')}", f"综合评分：{score.get('total_score', 'missing')}/100", f"财务评级：{rating}",
        "", "## 数据质量警告", "", _data_quality_lines(context.get("data_quality_warnings", [])),
        "", "## 一、核心结论", "", llm.get("deepseek", {}).get("content", "LLM 分析不可用。"),
        "", "## 二、财务评分", "", "| 维度 | 分数 | 解释 |", "| --- | ---: | --- |",
        f"| 盈利能力 | {score.get('profitability_score', 0)}/20 | Python 规则评分 |",
        f"| 成长能力 | {score.get('growth_score', 0)}/20 | Python 规则评分 |",
        f"| 现金流质量 | {score.get('cashflow_score', 0)}/20 | Python 规则评分 |",
        f"| 资产安全 | {score.get('asset_safety_score', 0)}/20 | Python 规则评分 |",
        f"| 估值合理性 | {score.get('valuation_score', 0)}/20 | Python 规则评分 |",
        "", "## 三、盈利能力", "", _factor_lines(factors, ["毛利率", "净利率", "扣非净利率", "ROE", "ROA", "研发费用率"]),
        "", "## 四、成长兑现", "", _factor_lines(factors, ["营收同比", "归母净利润同比", "扣非归母净利润同比", "近四季度滚动营收", "近四季度滚动扣非净利润"]),
        "", "## 五、现金流质量", "", _factor_lines(factors, ["经营现金流/归母净利润", "经营现金流/扣非归母净利润", "销售收现比", "自由现金流", "资本开支/营业收入"]),
        "", "## 六、资产风险", "", _factor_lines(factors, ["资产负债率", "有息负债率", "短债/货币资金", "应收账款/营业收入", "存货/营业收入", "商誉/净资产"]),
        "", "## 七、估值压力", "", _factor_lines(factors, ["PE TTM", "PB", "PS", "PEG", "市值/扣非净利润", "市值/经营现金流"]),
        "", "## 八、公告与消息面", "", _announcement_lines(context.get("announcements", [])),
        "", "## 九、风险红旗", "", _risk_lines(risks),
        "", "## 十、审核结论", "", llm.get("qwen", {}).get("content", "Qwen 审核不可用。"),
        "", "## 十一、交易意义", "", _trade_meaning(score.get("total_score"), risks), "",
    ]
    return "\n".join(lines)


def _factor_lines(factors: dict[str, Any], keys: list[str]) -> str:
    return "\n".join(f"- {key}：{_fmt(factors.get(key))}" for key in keys)


def _announcement_lines(announcements: list[dict[str, Any]]) -> str:
    if not announcements:
        return "无可用公告。"
    return "\n".join(f"- {item.get('公告日期') or '日期缺失'} | {item.get('公告类型')} | {item.get('公告标题')}" for item in announcements[:20])


def _risk_lines(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return "未触发风险红旗。"
    return "\n".join(f"- {item['risk_level']} | {item['flag_name']}：{item['evidence']}。{item['explanation']}" for item in risks)


def _data_quality_lines(warnings: list[dict[str, Any]]) -> str:
    if not warnings:
        return "未发现数据质量警告。"
    return "\n".join(f"- {item.get('level', 'warning')} | {item.get('stage')} | {item.get('source')}：{item.get('message')}" for item in warnings)


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _rating(total_score: Any) -> str:
    if total_score is None:
        return "一般"
    if total_score >= 80:
        return "优秀"
    if total_score >= 65:
        return "良好"
    if total_score >= 50:
        return "一般"
    return "高风险"


def _trade_meaning(total_score: Any, risks: list[dict[str, Any]]) -> str:
    if any(item.get("risk_level") == "high" for item in risks) or (total_score is not None and total_score < 50):
        return "不建议进入候选池。"
    if total_score is not None and total_score >= 75:
        return "适合加入观察池。"
    if total_score is not None and total_score >= 60:
        return "仅适合继续跟踪。"
    return "财务风险偏高，需要降低优先级。"


def _safe_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", filename)
