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
    operation: str
    numerator_fields: dict[str, list[str]]
    denominator_fields: dict[str, list[str]]
    helper_name: str | None
    expected_factor_key: str


SCHEMA_VERSION = "metric_provenance.v1.1"
REGISTRY_MODE = "description_only"
CALCULATION_SOURCE = "src.factors.financial_factors.compute_financial_factors"
FACTOR_META_KEYS = {"指标缺失数量", "指标总数量"}
# TODO(0.6.2): remove this allow-list after single-quarter factors are added to metric_registry contracts.
PENDING_061_FACTOR_KEYS = {
    "单季度营业收入",
    "单季度归母净利润",
    "单季度扣非净利润",
    "单季度经营现金流",
    "单季度同比信号",
}
META_FACTOR_KEYS = FACTOR_META_KEYS | PENDING_061_FACTOR_KEYS
ALLOWED_OPERATIONS = {"direct_market", "simple_ratio", "yoy", "ttm", "composite_helper"}


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
        "formula_text": "本期单季度营业收入 / 去年同季度单季度营业收入 - 1",
        "caliber_note": "使用季度拆分后的独立单季度营业收入；去年同季度基数小于等于 0 或缺失时不输出百分比，改由单季度同比信号说明状态。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["营业收入"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新单季度与去年同季度。",
    },
    "单季度扣非净利润同比": {
        "category": "成长",
        "formula_text": "本期单季度扣非归母净利润 / 去年同季度单季度扣非归母净利润 - 1",
        "caliber_note": "使用季度拆分后的独立单季度扣非归母净利润；去年同季度基数小于等于 0 或缺失时不输出百分比，改由单季度同比信号说明扭亏、亏损扩大或亏损收窄。",
        "source_reports": ["income_statement"],
        "source_fields": {"income_statement": ["扣非归母净利润"]},
        "unit": "ratio",
        "is_ttm": False,
        "period_note": "最新单季度与去年同季度。",
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


_SIMPLE_RATIO_CONTRACTS: dict[str, tuple[dict[str, list[str]], dict[str, list[str]]]] = {
    "毛利率": ({"income_statement": ["毛利", "营业收入", "营业成本"]}, {"income_statement": ["营业收入"]}),
    "净利率": ({"income_statement": ["归母净利润"]}, {"income_statement": ["营业收入"]}),
    "扣非净利率": ({"income_statement": ["扣非归母净利润"]}, {"income_statement": ["营业收入"]}),
    "研发费用率": ({"income_statement": ["研发费用"]}, {"income_statement": ["营业收入"]}),
    "经营现金流/归母净利润": ({"cash_flow": ["经营活动现金流净额"]}, {"income_statement": ["归母净利润"]}),
    "经营现金流/扣非归母净利润": ({"cash_flow": ["经营活动现金流净额"]}, {"income_statement": ["扣非归母净利润"]}),
    "销售收现比": ({"cash_flow": ["销售商品、提供劳务收到的现金"]}, {"income_statement": ["营业收入"]}),
    "资本开支/营业收入": ({"cash_flow": ["购建固定资产、无形资产和其他长期资产支付的现金"]}, {"income_statement": ["营业收入"]}),
    "资产负债率": ({"balance_sheet": ["总负债"]}, {"balance_sheet": ["总资产"]}),
    "商誉/净资产": ({"balance_sheet": ["商誉"]}, {"balance_sheet": ["股东权益"]}),
    "在建工程/固定资产": ({"balance_sheet": ["在建工程"]}, {"balance_sheet": ["固定资产"]}),
}
_YOY_CONTRACT_FIELDS = {
    "营收同比": {"income_statement": ["营业收入"]},
    "归母净利润同比": {"income_statement": ["归母净利润"]},
    "扣非归母净利润同比": {"income_statement": ["扣非归母净利润"]},
    "合同负债同比": {"balance_sheet": ["合同负债"]},
    "在建工程同比": {"balance_sheet": ["在建工程"]},
    "应收账款同比": {"balance_sheet": ["应收账款"]},
    "存货同比": {"balance_sheet": ["存货"]},
}
_SINGLE_QUARTER_YOY_CONTRACT_FIELDS = {
    "单季度营收同比": {"income_statement": ["营业收入"]},
    "单季度扣非净利润同比": {"income_statement": ["扣非归母净利润"]},
}
_TTM_CONTRACT_FIELDS = {
    "近四季度滚动营收": {"income_statement": ["营业收入"]},
    "近四季度滚动扣非净利润": {"income_statement": ["扣非归母净利润"]},
}
_DIRECT_MARKET_FIELDS = {
    "PE 动态": {"market_data": ["PE 动态"]},
    "行情源PEG": {"market_data": ["行情源PEG"]},
    "PB 行情源": {"market_data": ["PB 行情源"]},
    "行情源PS": {"market_data": ["行情源PS"]},
}


def _attach_contract_metadata(registry: dict[str, MetricDefinition]) -> None:
    for metric_name, definition in registry.items():
        if metric_name in _SIMPLE_RATIO_CONTRACTS:
            numerator_fields, denominator_fields = _SIMPLE_RATIO_CONTRACTS[metric_name]
            contract = {
                "operation": "simple_ratio",
                "numerator_fields": numerator_fields,
                "denominator_fields": denominator_fields,
                "helper_name": "gross_profit_or_reported" if metric_name == "毛利率" else None,
            }
        elif metric_name in _YOY_CONTRACT_FIELDS:
            contract = {
                "operation": "yoy",
                "numerator_fields": _YOY_CONTRACT_FIELDS[metric_name],
                "denominator_fields": _YOY_CONTRACT_FIELDS[metric_name],
                "helper_name": "_yoy",
            }
        elif metric_name in _SINGLE_QUARTER_YOY_CONTRACT_FIELDS:
            contract = {
                "operation": "composite_helper",
                "numerator_fields": _SINGLE_QUARTER_YOY_CONTRACT_FIELDS[metric_name],
                "denominator_fields": _SINGLE_QUARTER_YOY_CONTRACT_FIELDS[metric_name],
                "helper_name": "_single_quarter_yoy",
            }
        elif metric_name in _TTM_CONTRACT_FIELDS:
            contract = {
                "operation": "ttm",
                "numerator_fields": _TTM_CONTRACT_FIELDS[metric_name],
                "denominator_fields": {},
                "helper_name": "_ttm",
            }
        elif metric_name in _DIRECT_MARKET_FIELDS:
            contract = {
                "operation": "direct_market",
                "numerator_fields": _DIRECT_MARKET_FIELDS[metric_name],
                "denominator_fields": {},
                "helper_name": None,
            }
        else:
            contract = {
                "operation": "composite_helper",
                "numerator_fields": definition["source_fields"],
                "denominator_fields": {},
                "helper_name": f"compute_financial_factors.{metric_name}",
            }
        definition.update(contract)
        definition["expected_factor_key"] = metric_name


_attach_contract_metadata(METRIC_REGISTRY)


def registered_metric_names() -> set[str]:
    return set(METRIC_REGISTRY)


def get_metric_definition(metric_name: str) -> dict[str, Any] | None:
    definition = METRIC_REGISTRY.get(metric_name)
    return deepcopy(definition) if definition else None


def validate_metric_contracts(registry: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    registry = registry or METRIC_REGISTRY
    issues: list[dict[str, Any]] = []
    for metric_name, definition in registry.items():
        for field in ("operation", "numerator_fields", "denominator_fields", "helper_name", "expected_factor_key"):
            if field not in definition:
                issues.append(_contract_issue(metric_name, field, "missing_field", f"{field} is required"))
        operation = definition.get("operation")
        if operation is None:
            continue
        if operation not in ALLOWED_OPERATIONS:
            issues.append(_contract_issue(metric_name, "operation", "invalid_operation", f"unsupported operation: {operation}"))
            continue
        if definition.get("expected_factor_key") != metric_name:
            issues.append(_contract_issue(metric_name, "expected_factor_key", "key_mismatch", "expected_factor_key must match registry key"))
        if operation in {"simple_ratio", "yoy"}:
            if not definition.get("numerator_fields"):
                issues.append(_contract_issue(metric_name, "numerator_fields", "missing_formula_fields", f"{operation} requires numerator_fields"))
            if not definition.get("denominator_fields"):
                issues.append(_contract_issue(metric_name, "denominator_fields", "missing_formula_fields", f"{operation} requires denominator_fields"))
        if operation == "ttm" and not definition.get("numerator_fields"):
            issues.append(_contract_issue(metric_name, "numerator_fields", "missing_formula_fields", "ttm requires numerator_fields"))
        if operation == "direct_market" and not definition.get("numerator_fields"):
            issues.append(_contract_issue(metric_name, "numerator_fields", "missing_formula_fields", "direct_market requires market field declaration"))
        if operation == "composite_helper" and not definition.get("helper_name"):
            issues.append(_contract_issue(metric_name, "helper_name", "missing_helper", "composite_helper requires helper_name"))
    return issues


def shadow_validate_registry_against_factors(
    cleaned_reports: dict[str, list[dict[str, Any]]],
    market_data: dict[str, Any],
    factors: dict[str, Any],
    registry: dict[str, dict[str, Any]] | None = None,
    tolerance: float = 1e-9,
) -> list[dict[str, Any]]:
    registry = registry or METRIC_REGISTRY
    issues = [_shadow_contract_issue(issue) for issue in validate_metric_contracts(registry)]
    for metric_name, definition in registry.items():
        if metric_name not in factors:
            issues.append(_shadow_issue(metric_name, "missing_factor", None, None, "warning"))
            continue
        operation = definition.get("operation")
        if operation not in {"direct_market", "simple_ratio", "yoy"}:
            continue
        shadow_value = _shadow_metric_value(metric_name, definition, cleaned_reports, market_data)
        factor_value = factors.get(metric_name)
        if not _values_close(shadow_value, factor_value, tolerance):
            issues.append(_shadow_issue(metric_name, "value_mismatch", shadow_value, factor_value, "warning"))
    return issues


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


def _contract_issue(metric_name: str, field: str, issue_type: str, message: str) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "field": field,
        "issue_type": issue_type,
        "message": message,
    }


def _shadow_contract_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric_name": issue.get("metric_name"),
        "issue_type": issue.get("issue_type", "contract_issue"),
        "registry_value": issue.get("message"),
        "factor_value": None,
        "severity": "error",
    }


def _shadow_issue(metric_name: str, issue_type: str, registry_value: Any, factor_value: Any, severity: str) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "issue_type": issue_type,
        "registry_value": registry_value,
        "factor_value": factor_value,
        "severity": severity,
    }


def _shadow_metric_value(
    metric_name: str,
    definition: dict[str, Any],
    cleaned_reports: dict[str, list[dict[str, Any]]],
    market_data: dict[str, Any],
) -> float | None:
    operation = definition.get("operation")
    if operation == "direct_market":
        report, field = _first_declared_field(definition.get("numerator_fields", {}))
        return _to_float(market_data.get(field)) if report == "market_data" else None
    if operation == "simple_ratio":
        numerator = _shadow_numerator(metric_name, definition, cleaned_reports)
        denominator = _shadow_declared_value(definition.get("denominator_fields", {}), definition, cleaned_reports)
        return _safe_div(numerator, denominator)
    if operation == "yoy":
        report, field = _first_declared_field(definition.get("numerator_fields", {}))
        return _shadow_yoy(cleaned_reports.get(report, []), field)
    return None


def _shadow_numerator(metric_name: str, definition: dict[str, Any], cleaned_reports: dict[str, list[dict[str, Any]]]) -> float | None:
    if metric_name == "毛利率":
        rows = cleaned_reports.get("income_statement", [])
        row = rows[-1] if rows else {}
        gross_profit = _to_float(row.get("毛利"))
        if gross_profit is not None:
            return gross_profit
        revenue = _to_float(row.get("营业收入"))
        cost = _to_float(row.get("营业成本"))
        return None if revenue is None or cost is None else revenue - cost
    return _shadow_declared_value(definition.get("numerator_fields", {}), definition, cleaned_reports)


def _shadow_declared_value(
    fields_by_report: dict[str, list[str]],
    definition: dict[str, Any],
    cleaned_reports: dict[str, list[dict[str, Any]]],
) -> float | None:
    report, field = _first_declared_field(fields_by_report)
    if not report or not field:
        return None
    rows = _rows_for_definition(report, definition, cleaned_reports)
    row = rows[0] if rows else {}
    return _to_float(row.get(field))


def _first_declared_field(fields_by_report: dict[str, list[str]]) -> tuple[str | None, str | None]:
    for report, fields in fields_by_report.items():
        if fields:
            return report, fields[0]
    return None, None


def _shadow_yoy(rows: list[dict[str, Any]], field: str | None) -> float | None:
    if not field or len(rows) < 2:
        return None
    latest_row = rows[-1]
    base_row = _same_period_last_year(rows, latest_row)
    if base_row is None:
        return None
    latest, base = _to_float(latest_row.get(field)), _to_float(base_row.get(field))
    if latest is None or base in (None, 0):
        return None
    return latest / base - 1


def _safe_div(numerator: Any, denominator: Any) -> float | None:
    numerator_value, denominator_value = _to_float(numerator), _to_float(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return numerator_value / denominator_value


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _values_close(first: Any, second: Any, tolerance: float) -> bool:
    first_value, second_value = _to_float(first), _to_float(second)
    if first_value is None or second_value is None:
        return first_value is None and second_value is None
    return abs(first_value - second_value) <= tolerance


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
