"""本模块负责根据财务指标、清洗报表和公告标题生成风险红旗。所有规则均为可复现的 Python 判断，输出证据和解释供报告引用。"""

from typing import Any

RISK_ANNOUNCEMENT_KEYWORDS = ["问询函", "监管函", "减持", "质押", "资产减值"]


def generate_risk_flags(factors: dict[str, Any], cleaned_reports: dict[str, list[dict[str, Any]]], announcements: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    income_rows, balance_rows, cash_rows = cleaned_reports.get("income_statement", []), cleaned_reports.get("balance_sheet", []), cleaned_reports.get("cash_flow", [])
    if _last_two_cashflow_weak(cash_rows, income_rows):
        flags.append(_flag("利润现金流质量弱", "high", "经营现金流连续两期低于净利润 50%", "利润兑现到现金的质量偏弱。"))
    if _spread_above(factors.get("应收账款同比"), factors.get("营收同比"), 0.2):
        flags.append(_flag("回款压力上升", "medium", "应收账款增速高于营收增速 20 个百分点以上", "收入增长可能伴随更高赊销。"))
    if _spread_above(factors.get("存货同比"), factors.get("营收同比"), 0.2):
        flags.append(_flag("库存压力上升", "medium", "存货增速高于营收增速 20 个百分点以上", "库存消化压力需要继续跟踪。"))
    if _ratio_below(factors.get("扣非净利率"), factors.get("净利率"), 0.7):
        flags.append(_flag("利润依赖非经常损益", "medium", "扣非净利率显著低于净利率", "核心利润质量可能弱于表观利润。"))
    if _gt(factors.get("短债/货币资金"), 1):
        flags.append(_flag("短期偿债压力", "high", "短债大于货币资金", "短期债务覆盖不足。"))
    if _gt(factors.get("商誉/净资产"), 0.3):
        flags.append(_flag("商誉减值风险", "medium", "商誉占净资产比例超过 30%", "需关注并购资产减值压力。"))
    if _last_two_gross_margin_decline(income_rows):
        flags.append(_flag("盈利能力下滑", "medium", "毛利率连续两个报告期下滑", "产品或成本端压力可能上升。"))
    if _gt(factors.get("资产负债率"), 0.7):
        flags.append(_flag("杠杆偏高", "medium", "资产负债率高于默认阈值 70%", "行业阈值 0.0.0 使用默认配置。"))
    if _negative_cash_positive_profit(cash_rows, income_rows):
        flags.append(_flag("利润质量异常", "high", "经营现金流为负但净利润为正", "利润未同步转化为经营现金流。"))
    hits = _risk_announcements(announcements)
    if hits:
        flags.append(_flag("公告风险", "medium", "；".join(hits[:5]), "公告标题包含监管、减持、质押或减值等风险关键词。"))
    return flags


def _flag(name: str, level: str, evidence: str, explanation: str) -> dict[str, str]:
    return {"flag_name": name, "risk_level": level, "evidence": evidence, "explanation": explanation}


def _gt(value: Any, threshold: float) -> bool:
    return value is not None and value > threshold


def _spread_above(left: Any, right: Any, threshold: float) -> bool:
    return left is not None and right is not None and left - right > threshold


def _ratio_below(left: Any, right: Any, threshold: float) -> bool:
    return left is not None and right not in (None, 0) and left / right < threshold


def _last_two_cashflow_weak(cash_rows: list[dict[str, Any]], income_rows: list[dict[str, Any]]) -> bool:
    if len(cash_rows) < 2 or len(income_rows) < 2:
        return False
    checks = []
    for cash, income in zip(cash_rows[-2:], income_rows[-2:], strict=False):
        ocf, profit = cash.get("经营活动现金流净额"), income.get("归母净利润")
        checks.append(ocf is not None and profit not in (None, 0) and ocf < profit * 0.5)
    return all(checks)


def _last_two_gross_margin_decline(rows: list[dict[str, Any]]) -> bool:
    values = [_gross_margin(row) for row in rows[-3:]]
    if len(values) < 3 or any(value is None for value in values):
        return False
    return values[2] < values[1] < values[0]


def _gross_margin(row: dict[str, Any]) -> float | None:
    revenue, gross, cost = row.get("营业收入"), row.get("毛利"), row.get("营业成本")
    if gross is None and revenue is not None and cost is not None:
        gross = revenue - cost
    if revenue in (None, 0) or gross is None:
        return None
    return gross / revenue


def _negative_cash_positive_profit(cash_rows: list[dict[str, Any]], income_rows: list[dict[str, Any]]) -> bool:
    return bool(cash_rows and income_rows and (cash_rows[-1].get("经营活动现金流净额") or 0) < 0 and (income_rows[-1].get("归母净利润") or 0) > 0)


def _risk_announcements(announcements: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("公告标题") or "") for item in announcements if any(key in str(item.get("公告标题") or "") for key in RISK_ANNOUNCEMENT_KEYWORDS)]
