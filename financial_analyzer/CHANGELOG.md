# Changelog

## 0.6.0

- Anti-dependency Mode 调整为同次运行同时输出正常财务分析简报和 `_anti_dependency_review.md` 对比复盘，不再因为学习模式跳过普通报告。
- Anti-dependency 对比复盘记录新增普通报告路径，便于从复盘文件回跳到同次生成的完整财务分析简报。
- Anti-dependency 原始三张表改为 Markdown 表格展示，按最近报告期倒序排列，使用中文表头和亿元单位，避免 `1.2e+09` 等科学计数法降低可读性。
- 补充 Anti-dependency 双文件输出、先人工判断后普通 LLM/复盘、原始表格格式化的回归测试。
- 新增 `src/factors/quarterly_factors.py`，将财报数据源默认累计口径的 `Q1/H1/Q3/A` 报表值拆分为独立单季度 QTR 结果。
- 新增 `split_ytd_reports_to_quarters()`，输出 `status`、`quarters` 和 `warnings`，其中 QTR 指标键统一使用 `_QTR` 后缀，避免与原始累计字段混淆。
- Q1 直接取当期值，Q2 使用 H1-Q1，Q3 使用 Q3-H1，Q4 使用 A-Q3；输入顺序不作为质量问题，模块内部按报告期排序。
- 仅对无法解析报告期、重复报告期、缺少依赖期记录 warning；所有 status 统一为 `ok/warning/unavailable`。
- 本版本只新增独立季度拆分基础模块和测试，不接入 `compute_financial_factors()`，不修改 registry，不生成 trends JSON，不改报告展示；README 待 0.6.4 财务趋势全套能力完成后统一更新。

## 0.5.3

- registry 新增机器可读计算契约元信息，覆盖 `operation`、`numerator_fields`、`denominator_fields`、`helper_name` 和 `expected_factor_key`。
- 新增 `validate_metric_contracts()` 静态校验，检查 registry 契约字段完整性、operation 枚举和 helper 声明。
- 新增 `shadow_validate_registry_against_factors()` 只读试运行校验，对低风险指标复算并报告差异，不修正 factors。
- 将 0.5.3 测试拆为契约元信息、静态校验、shadow validation 和组装测试，确保全部通过后再整体验收。
- 本版本不替换 `compute_financial_factors()`，不改变评分、风险红旗、报告判断，也不处理历史 `data/output` 报告。

## 0.5.2

- `metric_provenance.json` schema 升级为 `metric_provenance.v1.1`，顶层新增 `source_audit`。
- 新增清洗字段审计能力，基于 `FIELD_ALIASES` 记录标准字段、原始字段别名、实际命中的原始字段、缺失状态和统一转元说明。
- 主流程新增来源审计信息，记录抓取函数、raw/processed 文件路径、分析日期和生成时间。
- metric source 新增 `audit_ref`，可从指标来源跳转到对应数据源审计块。
- Markdown 报告在“指标口径与来源追溯”中增加轻量来源审计摘要，不展开完整字段映射。
- 本版本不改变指标计算、评分、风险红旗、数据质量闸门，不处理历史 `data/output` 报告，也不新增数据源。

## 0.5.1

- 将 ROE 拆分为 `年度ROE` 和 `季度ROE`：年度口径使用最新年报归母净利润和年报股东权益，季度口径保留最新非年报报告期利润和股东权益；兼容字段 `ROE` 暂时等同于 `年度ROE`。
- 新增 `单季度年化ROE`：公式为 `最新单季度归母净利润 * 4 / 相邻两期平均股东权益`，补充观察单季回报强度。
- 修正 `ROA` 口径：由 `最新累计归母净利润 / 期末总资产` 改为 `TTM 归母净利润 / 最新报告期与去年同期平均总资产`。
- 修正 `应收账款/营业收入` 和 `存货/营业收入` 口径：分别改为 `期末应收账款 / TTM 营业收入`、`期末存货 / TTM 营业收入`，避免一季报直接除以 Q1 收入导致比例异常放大。
- `metric_provenance` 的财报来源新增 `period_type/period_prefix`，报告中展示 `年度/半年度/季度` 前缀，避免混淆利润表和资产负债表指标口径。
- 修正 PE 口径：东方财富/AKShare 的 `市盈率-动态` 单独保存为 `PE 动态`，不再冒充 `PE TTM`；项目内 `PE TTM` 改为 `总市值 / TTM 归母净利润`。
- 补充 `PE 动态` 口径说明：行情源动态 PE 通常以当年已披露归母净利润倍增为全年预测利润后计算。
- 修正 PEG 口径：行情源 PEG 单独保存为 `行情源PEG`，并说明东方财富口径为 `市盈率 TTM / 未来 3 年预测 EPS 复合增长率`；项目内 `PEG` 改为 `PE TTM / TTM 归母净利润同比百分数`，不再混用行情源预测 EPS 口径或扣非增长率。
- 修正 PB 口径：东方财富/AKShare 的市净率字段单独保存为 `PB 行情源`，项目内 `PB` 改为 `总市值 / 最新资产负债表股东权益`。
- 修正 PS 口径：行情源市销率字段单独保存为 `行情源PS`，项目内 `PS` 改为 `总市值 / TTM 营业收入`。
- 报告估值章节同时展示 `PE 动态`、`PE TTM`、`行情源PEG`、项目计算 `PEG`、`PB 行情源`、项目计算 `PB`、`行情源PS` 和项目计算 `PS`，便于对照行情源字段与财报口径。
- provenance 同步更新估值来源说明：`PE TTM` 追溯到 `market_data: 总市值` 和 TTM 归母净利润，`PEG` 追溯到项目计算 `PE TTM` 与 TTM 归母净利润同比，`PB` 追溯到 `market_data: 总市值` 和最新资产负债表股东权益，`PS` 追溯到 `market_data: 总市值` 和 TTM 营业收入。
- 主流程在财报清洗后会将项目计算的 `PE TTM`、`PB`、`PS`、`PEG` 和计算明细写入 processed `market_data`，供后续 LLM 和报告上下文使用。
- raw_fetch 估值质量检查改为检查行情源可直接提供的 `PE 动态`、`PE TTM`、`行情源PEG`、`PB 行情源`、`PB`、`行情源PS`，避免因项目计算口径字段初始为空而误报。
- 增加行情字段映射测试、年度/季度/单季度年化 ROE 测试、半年度前缀测试、PE/PB/PS/PEG 项目计算口径测试、ROA 与营运资本收入比口径测试，防止再次把动态、行情源或预测字段误标为 TTM 或主指标。

## 0.5.0

- 新增 `metric_registry.py` 指标说明注册表，覆盖盈利、成长、现金流、资产安全、估值五类核心指标。
- 新增 `metric_provenance.json`，追溯现有指标结果使用的清洗字段、市场字段、报告期和披露日期。
- 报告新增“指标口径与来源追溯”章节，并在关键指标旁展示公式/来源摘要。
- 增加 registry 与 factors 字段一致性测试、provenance schema 快照测试和主流程落盘测试。
- 本版本 registry 仅做文字说明，不参与计算，也不修正现有指标结果。

## 0.4.1

- 增加了 `business_fetcher.py`，在交易简报里面提供了主营构成和行业介绍。

## 0.4.0

- 新增 A 股主板普通股票支持范围校验，非支持代码会在抓取前清晰拒绝。
- 数据质量检查升级为 `fatal/warning/info` 分级，并新增整体质量状态汇总。
- `fatal` 数据只输出数据失败报告，不生成指标、评分、LLM 分析或使用建议。
- `warning` 数据继续输出正常报告，但顶部标记为“降级分析”并展示质量影响。

## 0.3.1

- 进化到0.4.0之前的备份。

## 0.3.0

- 优化财务分析记录保留策略：普通分析输出按同一股票代码只保留最新日期记录，避免历史简报堆积。
- 学习模式 / Anti-dependency Mode 输出不参与清理，保留历史复盘记录用于后续对照学习。
- 调整 TTM 指标口径：近四季度滚动营收、近四季度滚动扣非净利润改为按最新报告期推算 TTM。
- 优化估值指标口径：PEG 改用 TTM 扣非归母净利润同比，市值/扣非净利润、市值/经营现金流改用 TTM 分母。
- 补充输出清理和 TTM 估值口径测试，覆盖同代码清理、跨标的不误删、学习模式记录保留等场景。

## 0.2.2

- 完成数据口径调整，修改同比比较逻辑，改为同类报告期跨年比较。

## 0.2.1

- 修复东方财富基础信息接口解析问题，避免 `stock_individual_info_em` 因返回字段变化导致空数据。
- 调整 akshare-proxy-patch 初始化参数，显式使用代理补丁支持的 `auth_ip` / `auth_token` 配置。

## 0.2.0

- 新增 Anti-dependency Mode 人机摩擦层：先展示原始财务数据，要求用户提交人工判断后，才解锁 Qwen 对比复盘。
- 新增漏判、误判、过度判断记录，帮助用户复盘人工判断与系统判断的差异。
- 调整代码结构，拆分 Anti-dependency 流程和数据质量检测模块，减少主流程耦合。

## 0.1.0

- 接入了 a-stock-data（[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)）补充数据源模块。
- 新增腾讯行情、东方财富板块/行业/资金流等独立抓取函数，暂未接入主分析流程或 prompt。

## 0.0.0

- 搭建了基础框架，实现api接入
