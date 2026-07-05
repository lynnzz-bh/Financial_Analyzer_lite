"""本模块负责将财务指标转换为五维 100 分制评分。评分完全由 Python 规则产生，LLM 只允许解释分数高低，不能直接修改结果。"""

from typing import Any


def score_financials(factors: dict[str, Any]) -> dict[str, Any]:
    scores = {
        "profitability_score": _score_profitability(factors),
        "growth_score": _score_growth(factors),
        "cashflow_score": _score_cashflow(factors),
        "asset_safety_score": _score_asset_safety(factors),
        "valuation_score": _score_valuation(factors),
    }
    scores["total_score"] = sum(scores.values())
    scores["score_confidence"] = _confidence(factors)
    return scores


def _score_profitability(factors: dict[str, Any]) -> int:
    return _points([(factors.get("毛利率"), 0.3, 5), (factors.get("净利率"), 0.1, 5), (factors.get("扣非净利率"), 0.08, 5), (factors.get("年度ROE", factors.get("ROE")), 0.12, 5)])


def _score_growth(factors: dict[str, Any]) -> int:
    return _points([(factors.get("营收同比"), 0.1, 5), (factors.get("归母净利润同比"), 0.1, 5), (factors.get("扣非归母净利润同比"), 0.1, 5), (factors.get("近四季度滚动营收"), 0, 5)])


def _score_cashflow(factors: dict[str, Any]) -> int:
    return _points([(factors.get("经营现金流/归母净利润"), 1, 6), (factors.get("销售收现比"), 1, 5), (factors.get("自由现金流"), 0, 5), (factors.get("资本开支/营业收入"), 0.3, 4, "lte")])


def _score_asset_safety(factors: dict[str, Any]) -> int:
    return _points([(factors.get("资产负债率"), 0.6, 5, "lte"), (factors.get("有息负债率"), 0.35, 5, "lte"), (factors.get("短债/货币资金"), 1, 5, "lte"), (factors.get("商誉/净资产"), 0.3, 5, "lte")])


def _score_valuation(factors: dict[str, Any]) -> int:
    return _points([(factors.get("PE TTM"), 35, 5, "lte"), (factors.get("PB"), 5, 5, "lte"), (factors.get("PS"), 8, 5, "lte"), (factors.get("PEG"), 2, 5, "lte")])


def _points(rules: list[tuple]) -> int:
    total = 0
    for rule in rules:
        value, threshold, score = rule[:3]
        direction = rule[3] if len(rule) > 3 else "gte"
        if value is None:
            continue
        if direction == "gte" and value >= threshold:
            total += score
        if direction == "lte" and value <= threshold:
            total += score
    return min(20, int(total))


def _confidence(factors: dict[str, Any]) -> str:
    missing, total = factors.get("指标缺失数量") or 0, factors.get("指标总数量") or 1
    ratio = missing / total
    if ratio <= 0.25:
        return "high"
    if ratio <= 0.5:
        return "medium"
    return "low"
