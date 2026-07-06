"""Metric formula descriptions and provenance helpers.

The registry is a description layer only in 0.5.0. It documents the fields
used by ``financial_factors.compute_financial_factors`` but does not calculate
or correct any metric values.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict
import re


class MetricDefinition(TypedDict):
    category: str
    formula_text: str
    caliber_note: str
    source_reports: list[str]
    source_fields: dict[str, list[str]]
    unit: str
    is_ttm: bool
    period_note: str


SCHEMA_VERSION = "metric_provenance.v1.1"
REGISTRY_MODE = "description_only"
CALCULATION_SOURCE = "src.factors.financial_factors.compute_financial_factors"
META_FACTOR_KEYS = {"指标缺失数量", "指标总数量"}


METRIC_REGISTRY: dict[str, MetricDefinition] = {
    "毛利率": {
        "category": "盈利",
        "formula_text": "毛利 / 营业收入",
        "caliber_note": "沿用现有 factors 口径；毛利缺失时由营业收入减营业成本得到。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["毛利", "营业收入", "营业成本"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "净利率": {
        "category": "盈利",
        "formula_text": "归母净利润 / 营业收入",
        "caliber_note": "归母净利润相对营业收入的比例。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["归母净利润", "营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "扣非净利率": {
        "category": "盈利",
        "formula_text": "扣非归母净利润 / 营业收入",
        "caliber_note": "扣除非经常性损益后的归母净利润率。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["扣非归母净利润", "营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "年度ROE": {
        "category": "盈利",
        "formula_text": "年报归母净利润 / 年报股东权益",
        "caliber_note": "使用最新年报归母净利润和最新年报股东权益，避免把季度利润误当全年 ROE。",
        "source_reports": ["income_statement", "balance_sheet"],
        "source_fields": {"income_statement": ["归母净利润"], "balance_sheet": ["股东权益"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新年报利润表与最新年报资产负债表。",
    },
    "季度ROE": {
        "category": "盈利",
        "formula_text": "最新非年报报告期归母净利润 / 最新非年报报告期股东权益",
        "caliber_note": "使用最新非年报报告期累计利润和期末股东权益；保留为东财 ROEJQ 近似对照口径。",
        "source_reports": ["income_statement", "balance_sheet"],
        "source_fields": {"income_statement": ["归母净利润"], "balance_sheet": ["股东权益"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新非年报利润表与最新非年报资产负债表。",
    },
    "单季度年化ROE": {
        "category": "盈利",
        "formula_text": "单季度归母净利润 × 4 / 平均股东权益",
        "caliber_note": "将最新单季度归母净利润年化，平均股东权益使用本季期末和上一报告期期末股东权益均值；适合观察单季回报率强度。",
        "source_reports": ["income_statement", "balance_sheet"],
        "source_fields": {"income_statement": ["归母净利润"], "balance_sheet": ["股东权益"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新单季度利润与相邻两期资产负债表。",
    },
    "ROE": {
        "category": "盈利",
        "formula_text": "年报归母净利润 / 年报股东权益",
        "caliber_note": "兼容字段，等同于年度ROE；后续使用时优先读取年度ROE或季度ROE。",
        "source_reports": ["income_statement", "balance_sheet"],
        "source_fields": {"income_statement": ["归母净利润"], "balance_sheet": ["股东权益"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新年报利润表与最新年报资产负债表。",
    },
    "ROA": {
        "category": "盈利",
        "formula_text": "TTM 归母净利润 / 平均总资产",
        "caliber_note": "使用近四季度滚动归母净利润除以最新报告期和去年同期总资产均值，避免季度利润未年化导致 ROA 偏低。",
        "source_reports": ["income_statement", "balance_sheet"],
        "source_fields": {"income_statement": ["归母净利润"], "balance_sheet": ["总资产"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "利润为 TTM；总资产为最新报告期和去年同期均值。",
    },
    "研发费用率": {
        "category": "盈利",
        "formula_text": "研发费用 / 营业收入",
        "caliber_note": "用于观察研发投入强度。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["研发费用", "营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "营收同比": {
        "category": "成长",
        "formula_text": "本期营业收入 / 去年同期营业收入 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "归母净利润同比": {
        "category": "成长",
        "formula_text": "本期归母净利润 / 去年同期归母净利润 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "扣非归母净利润同比": {
        "category": "成长",
        "formula_text": "本期扣非归母净利润 / 去年同期扣非归母净利润 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["扣非归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "单季度营收同比": {
        "category": "成长",
        "formula_text": "当前版本沿用营收同比",
        "caliber_note": "0.5.0 只追溯现有结果，不修正单季度口径；严格单季拆分留到 0.6.0。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "当前版本沿用最新报告期与去年同类报告期。",
    },
    "单季度扣非净利润同比": {
        "category": "成长",
        "formula_text": "当前版本沿用扣非归母净利润同比",
        "caliber_note": "0.5.0 只追溯现有结果，不修正单季度口径；严格单季拆分留到 0.6.0。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["扣非归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "当前版本沿用最新报告期与去年同类报告期。",
    },
    "近四季度滚动营收": {
        "category": "成长",
        "formula_text": "最新累计收入 + 上年年报收入 - 上年同期累计收入",
        "caliber_note": "年报时直接使用年报值，其他报告期使用现有 TTM 推算。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["营业收入"]},
        "unit": "yuan",
        "is_ttm": True,
        "period_note": "最新报告期、上年年报和上年同期。",
    },
    "近四季度滚动扣非净利润": {
        "category": "成长",
        "formula_text": "最新累计扣非归母净利润 + 上年年报扣非归母净利润 - 上年同期累计扣非归母净利润",
        "caliber_note": "年报时直接使用年报值，其他报告期使用现有 TTM 推算。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["扣非归母净利润"]},
        "unit": "yuan",
        "is_ttm": True,
        "period_note": "最新报告期、上年年报和上年同期。",
    },
    "合同负债同比": {
        "category": "资产安全",
        "formula_text": "本期合同负债 / 去年同期合同负债 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["合同负债"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "在建工程同比": {
        "category": "资产安全",
        "formula_text": "本期在建工程 / 去年同期在建工程 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["在建工程"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "应收账款同比": {
        "category": "资产安全",
        "formula_text": "本期应收账款 / 去年同期应收账款 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["应收账款"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "存货同比": {
        "category": "资产安全",
        "formula_text": "本期存货 / 去年同期存货 - 1",
        "caliber_note": "按同类报告期跨年比较。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["存货"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新报告期与去年同类报告期。",
    },
    "经营现金流/归母净利润": {
        "category": "现金流",
        "formula_text": "经营活动现金流净额 / 归母净利润",
        "caliber_note": "观察利润现金含量。",
        "source_reports": ["cash_flow", "income_statement"],
        "source_fields": {"cash_flow": ["经营活动现金流净额"], "income_statement": ["归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新现金流量表与最新利润表。",
    },
    "经营现金流/扣非归母净利润": {
        "category": "现金流",
        "formula_text": "经营活动现金流净额 / 扣非归母净利润",
        "caliber_note": "观察扣非利润现金含量。",
        "source_reports": ["cash_flow", "income_statement"],
        "source_fields": {"cash_flow": ["经营活动现金流净额"], "income_statement": ["扣非归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新现金流量表与最新利润表。",
    },
    "销售收现比": {
        "category": "现金流",
        "formula_text": "销售商品、提供劳务收到的现金 / 营业收入",
        "caliber_note": "观察收入收现质量。",
        "source_reports": ["cash_flow", "income_statement"],
        "source_fields": {"cash_flow": ["销售商品、提供劳务收到的现金"], "income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新现金流量表与最新利润表。",
    },
    "自由现金流": {
        "category": "现金流",
        "formula_text": "经营活动现金流净额 - 资本开支",
        "caliber_note": "资本开支使用购建固定资产、无形资产和其他长期资产支付的现金。",
        "source_reports": ["cash_flow"],
        "source_fields": {"cash_flow": ["经营活动现金流净额", "购建固定资产、无形资产和其他长期资产支付的现金"]},
        "unit": "yuan",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "资本开支/营业收入": {
        "category": "现金流",
        "formula_text": "资本开支 / 营业收入",
        "caliber_note": "资本开支使用购建固定资产、无形资产和其他长期资产支付的现金。",
        "source_reports": ["cash_flow", "income_statement"],
        "source_fields": {"cash_flow": ["购建固定资产、无形资产和其他长期资产支付的现金"], "income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新现金流量表与最新利润表。",
    },
    "资产负债率": {
        "category": "资产安全",
        "formula_text": "总负债 / 总资产",
        "caliber_note": "观察整体杠杆水平。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["总负债", "总资产"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "有息负债": {
        "category": "资产安全",
        "formula_text": "短期借款 + 一年内到期非流动负债 + 长期借款",
        "caliber_note": "现有口径仅覆盖已清洗的主要有息负债字段。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["短期借款", "一年内到期非流动负债", "长期借款"]},
        "unit": "yuan",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "有息负债率": {
        "category": "资产安全",
        "formula_text": "有息负债 / 总资产",
        "caliber_note": "有息负债沿用当前主要债务字段合计口径。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["短期借款", "一年内到期非流动负债", "长期借款", "总资产"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "短债/货币资金": {
        "category": "资产安全",
        "formula_text": "短债 / 货币资金",
        "caliber_note": "短债为短期借款和一年内到期非流动负债合计。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["短期借款", "一年内到期非流动负债", "货币资金"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "应收账款/营业收入": {
        "category": "资产安全",
        "formula_text": "期末应收账款 / TTM 营业收入",
        "caliber_note": "观察应收账款相对近四季度收入规模的占用压力，避免一季报直接除以 Q1 收入导致比例失真。",
        "source_reports": ["balance_sheet", "income_statement"],
        "source_fields": {"balance_sheet": ["应收账款"], "income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "应收账款为最新期末数；营业收入为 TTM。",
    },
    "存货/营业收入": {
        "category": "资产安全",
        "formula_text": "期末存货 / TTM 营业收入",
        "caliber_note": "观察存货相对近四季度收入规模的占用压力，避免一季报直接除以 Q1 收入导致比例失真。",
        "source_reports": ["balance_sheet", "income_statement"],
        "source_fields": {"balance_sheet": ["存货"], "income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "存货为最新期末数；营业收入为 TTM。",
    },
    "商誉/净资产": {
        "category": "资产安全",
        "formula_text": "商誉 / 股东权益",
        "caliber_note": "观察商誉相对净资产的风险暴露。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["商誉", "股东权益"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "在建工程/固定资产": {
        "category": "资产安全",
        "formula_text": "在建工程 / 固定资产",
        "caliber_note": "观察扩产或资本投入强度。",
        "source_reports": ["balance_sheet"],
        "source_fields": {"balance_sheet": ["在建工程", "固定资产"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新可用报告期。",
    },
    "PE 动态": {
        "category": "估值",
        "formula_text": "行情源提供的动态市盈率",
        "caliber_note": "东方财富/AKShare 的市盈率-动态，通常以当年已披露的归母净利润倍增为全年预测利润后计算，不等同于 PE TTM。",
        "source_reports": ["market_data"],
        "source_fields": {"market_data": ["PE 动态"]},
        "unit": "multiple",
        "is_ttm": False,
        "period_note": "行情源最新可用口径。",
    },
    "PE TTM": {
        "category": "估值",
        "formula_text": "总市值 / 近四季度滚动归母净利润",
        "caliber_note": "由本项目基于行情总市值和利润表 TTM 归母净利润计算，不再把动态市盈率冒充为 TTM PE。",
        "source_reports": ["market_data", "income_statement"],
        "source_fields": {"market_data": ["总市值"], "income_statement": ["归母净利润"]},
        "unit": "multiple",
        "is_ttm": True,
        "period_note": "总市值为行情源最新口径；归母净利润为 TTM。",
    },
    "行情源PEG": {
        "category": "估值",
        "formula_text": "行情源提供的 PEG",
        "caliber_note": "东方财富 PEG 采用市盈率 TTM / 公司未来 3 年每股收益复合增长率，增长率来自其分析师预测 EPS；保留用于对照，不作为主 PEG。",
        "source_reports": ["market_data"],
        "source_fields": {"market_data": ["行情源PEG"]},
        "unit": "multiple",
        "is_ttm": False,
        "period_note": "行情源最新可用口径。",
    },
    "PB": {
        "category": "估值",
        "formula_text": "总市值 / 最新股东权益",
        "caliber_note": "由本项目基于行情总市值和最新资产负债表股东权益计算，避免直接沿用口径不透明的行情源 PB。",
        "source_reports": ["market_data", "balance_sheet"],
        "source_fields": {"market_data": ["总市值"], "balance_sheet": ["股东权益"]},
        "unit": "multiple",
        "is_ttm": False,
        "period_note": "总市值为行情源最新口径；股东权益为最新资产负债表。",
    },
    "PB 行情源": {
        "category": "估值",
        "formula_text": "行情源提供的市净率",
        "caliber_note": "东方财富/AKShare 的市净率字段，保留用于对照；主 PB 使用项目内部计算口径。",
        "source_reports": ["market_data"],
        "source_fields": {"market_data": ["PB 行情源"]},
        "unit": "multiple",
        "is_ttm": False,
        "period_note": "行情源最新可用口径。",
    },
    "行情源PS": {
        "category": "估值",
        "formula_text": "行情源提供的市销率",
        "caliber_note": "东方财富/AKShare 的市销率字段，保留用于对照；主 PS 使用项目内部计算口径。",
        "source_reports": ["market_data"],
        "source_fields": {"market_data": ["行情源PS"]},
        "unit": "multiple",
        "is_ttm": False,
        "period_note": "行情源最新可用口径。",
    },
    "PS": {
        "category": "估值",
        "formula_text": "总市值 / 近四季度滚动营业收入",
        "caliber_note": "由本项目基于行情总市值和利润表 TTM 营业收入计算，避免直接沿用口径不透明的行情源 PS。",
        "source_reports": ["market_data", "income_statement"],
        "source_fields": {"market_data": ["总市值"], "income_statement": ["营业收入"]},
        "unit": "multiple",
        "is_ttm": True,
        "period_note": "总市值为行情源最新口径；营业收入为 TTM。",
    },
    "PEG": {
        "category": "估值",
        "formula_text": "PE TTM / TTM 归母净利润同比百分数",
        "caliber_note": "PE TTM 和增长率均使用归母净利润 TTM 口径；行情源预测/动态口径另以“行情源PEG”保留。",
        "source_reports": ["market_data", "income_statement"],
        "source_fields": {"market_data": ["总市值"], "income_statement": ["归母净利润"]},
        "unit": "multiple",
        "is_ttm": True,
        "period_note": "PE 和增长率均使用最新报告期对应的 TTM 归母净利润。",
    },
    "市值/扣非净利润": {
        "category": "估值",
        "formula_text": "总市值 / 近四季度滚动扣非归母净利润",
        "caliber_note": "总市值来自 market_data，分母沿用现有 TTM 口径。",
        "source_reports": ["market_data", "income_statement"],
        "source_fields": {"market_data": ["总市值"], "income_statement": ["扣非归母净利润"]},
        "unit": "multiple",
        "is_ttm": True,
        "period_note": "总市值为行情源最新口径；扣非净利润为 TTM。",
    },
    "市值/经营现金流": {
        "category": "估值",
        "formula_text": "总市值 / 近四季度滚动经营活动现金流净额",
        "caliber_note": "总市值来自 market_data，分母沿用现有 TTM 口径。",
        "source_reports": ["market_data", "cash_flow"],
        "source_fields": {"market_data": ["总市值"], "cash_flow": ["经营活动现金流净额"]},
        "unit": "multiple",
        "is_ttm": True,
        "period_note": "总市值为行情源最新口径；经营现金流为 TTM。",
    },
}


def registered_metric_names() -> set[str]:
    return set(METRIC_REGISTRY)


def get_metric_definition(metric_name: str) -> dict[str, Any] | None:
    definition = METRIC_REGISTRY.get(metric_name)
    return deepcopy(definition) if definition else None


def build_metric_provenance(
    cleaned_reports: dict[str, list[dict[str, Any]]],
    market_data: dict[str, Any],
    factors: dict[str, Any],
    source_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric_name in sorted(key for key in factors if key not in META_FACTOR_KEYS):
        definition = METRIC_REGISTRY.get(metric_name)
        if definition is None:
            metrics[metric_name] = _unknown_metric(metric_name, factors.get(metric_name))
            continue
        sources = _metric_sources(definition, cleaned_reports, market_data)
        metrics[metric_name] = {
            "value": factors.get(metric_name),
            "category": definition["category"],
            "formula_text": definition["formula_text"],
            "caliber_note": definition["caliber_note"],
            "unit": definition["unit"],
            "is_ttm": definition["is_ttm"],
            "period_note": definition["period_note"],
            "status": _metric_status(factors.get(metric_name), sources),
            "sources": sources,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "registry_mode": REGISTRY_MODE,
        "calculation_source": CALCULATION_SOURCE,
        "source_audit": source_audit or _missing_source_audit(),
        "metrics": metrics,
    }


def _unknown_metric(metric_name: str, value: Any) -> dict[str, Any]:
    return {
        "value": value,
        "category": "未登记",
        "formula_text": "registry 未登记",
        "caliber_note": "该指标尚未进入 0.5.0 说明注册表。",
        "unit": "unknown",
        "is_ttm": False,
        "period_note": "unknown",
        "status": "missing" if value is None else "partial",
        "sources": [],
    }


def _metric_sources(
    definition: MetricDefinition,
    cleaned_reports: dict[str, list[dict[str, Any]]],
    market_data: dict[str, Any],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for report_name in definition["source_reports"]:
        fields = definition["source_fields"].get(report_name, [])
        if report_name == "market_data":
            sources.append(_market_source(fields, market_data))
            continue
        rows = _rows_for_definition(report_name, definition, cleaned_reports)
        if not rows:
            sources.append(_report_source(report_name, fields, {}))
            continue
        for row in rows:
            sources.append(_report_source(report_name, fields, row))
    return sources


def _rows_for_definition(
    report_name: str,
    definition: MetricDefinition,
    cleaned_reports: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows = cleaned_reports.get(report_name, [])
    if not rows:
        return []
    if "单季度" in definition["formula_text"]:
        return _single_quarter_trace_rows(rows) if report_name == "income_statement" else _single_quarter_balance_trace_rows(rows)
    if "最新年报" in definition["period_note"]:
        return [_latest_annual_trace_row(rows)]
    if "最新非年报" in definition["period_note"]:
        return [_latest_quarterly_trace_row(rows)]
    if report_name == "balance_sheet" and "去年同期均值" in definition["period_note"]:
        return _latest_and_same_period_last_year(rows)
    if report_name == "balance_sheet" and "期末数" in definition["period_note"]:
        return [rows[-1]]
    if report_name == "income_statement" and "TTM" in definition["period_note"]:
        return _ttm_trace_rows(rows)
    if definition["is_ttm"] and report_name != "market_data":
        return _ttm_trace_rows(rows)
    if "去年同期" in definition["period_note"] or "同比" in definition["formula_text"]:
        return _latest_and_same_period_last_year(rows)
    return [rows[-1]]


def _latest_annual_trace_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in reversed(rows):
        if str(row.get("report_period") or "").endswith("A"):
            return row
    return rows[-1]


def _latest_quarterly_trace_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in reversed(rows):
        period = str(row.get("report_period") or "")
        if period and not period.endswith("A"):
            return row
    return rows[-1]


def _latest_and_same_period_last_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = rows[-1]
    base = _same_period_last_year(rows, latest)
    return [row for row in (latest, base) if row]


def _single_quarter_trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = rows[-1]
    period = _parse_period(latest.get("report_period"))
    if period is None:
        return [latest]
    year, period_code = period
    previous_period = {"Q1": None, "H1": "Q1", "Q3": "H1", "A": "Q3"}[period_code]
    if previous_period is None:
        return [latest]
    previous = _row_for_period(rows, f"{year}{previous_period}")
    return [row for row in (latest, previous) if row]


def _single_quarter_balance_trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = rows[-1]
    period = _parse_period(latest.get("report_period"))
    if period is None:
        return [latest]
    year, period_code = period
    previous_period = {"Q1": f"{year - 1}A", "H1": f"{year}Q1", "Q3": f"{year}H1", "A": f"{year}Q3"}[period_code]
    previous = _row_for_period(rows, previous_period)
    return [row for row in (latest, previous) if row]


def _ttm_trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = rows[-1]
    period = _parse_period(latest.get("report_period"))
    if period is None:
        return [latest]
    year, period_code = period
    if period_code == "A":
        return [latest]
    wanted = [f"{year}{period_code}", f"{year - 1}A", f"{year - 1}{period_code}"]
    trace_rows = [_row_for_period(rows, report_period) for report_period in wanted]
    return [row for row in trace_rows if row]


def _market_source(fields: list[str], market_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": "market_data",
        "fields": fields,
        "available_fields": [field for field in fields if market_data.get(field) is not None],
        "report_period": None,
        "publish_date": None,
        "unit": "market_data",
        "audit_ref": "data_sources.market_data",
    }


def _report_source(report_name: str, fields: list[str], row: dict[str, Any]) -> dict[str, Any]:
    report_period = row.get("report_period")
    period_type, period_prefix = _period_type_and_prefix(report_period)
    return {
        "report": report_name,
        "fields": fields,
        "available_fields": [field for field in fields if row.get(field) is not None],
        "report_period": report_period,
        "period_type": period_type,
        "period_prefix": period_prefix,
        "publish_date": _string_or_none(row.get("publish_date")),
        "unit": "元",
        "audit_ref": f"data_sources.{report_name}",
    }


def _metric_status(value: Any, sources: list[dict[str, Any]]) -> str:
    if value is None:
        return "missing"
    if not sources:
        return "partial"
    if any(source.get("available_fields") for source in sources):
        return "ok"
    return "partial"


def _same_period_last_year(rows: list[dict[str, Any]], latest_row: dict[str, Any]) -> dict[str, Any] | None:
    period = latest_row.get("report_period")
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|A)", str(period or ""))
    if not match:
        return None
    target_period = f"{int(match.group(1)) - 1}{match.group(2)}"
    return _row_for_period(rows[:-1], target_period)


def _row_for_period(rows: list[dict[str, Any]], period: str) -> dict[str, Any] | None:
    for row in reversed(rows):
        if row.get("report_period") == period:
            return row
    return None


def _parse_period(value: Any) -> tuple[int, str] | None:
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|A)", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _period_type_and_prefix(report_period: Any) -> tuple[str | None, str | None]:
    period = str(report_period or "")
    if period.endswith("A"):
        return "annual", "年度"
    if period.endswith("H1"):
        return "half_year", "半年度"
    if re.fullmatch(r"\d{4}Q[1-4]", period):
        return "quarter", "季度"
    return None, None


def _missing_source_audit() -> dict[str, Any]:
    return {
        "status": "missing",
        "analysis_date": None,
        "generated_at": None,
        "data_sources": {},
        "file_paths": {},
    }
