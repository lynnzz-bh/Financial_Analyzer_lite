# Financial Analyzer 0.4.0

A 股单股财务分析工作流系统。输入股票代码、分析日期和分析目标后，系统抓取 AKShare 数据、清洗财报、计算指标、生成风险红旗和评分，并输出 Markdown 简报。

## 安装

```bash
cd F:\codex_code\Financial-Analyzer\financial_analyzer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env` 后填写：

- `AKSHARE_PROXY_TOKEN`：调用东方财富网相关 AKShare 接口时必须填写。
- `DEEPSEEK_API_KEY` / `QWEN_API_KEY`：为空时跳过 LLM 调用，并在报告中明确标记。

## 运行

```bash
python main.py --code 600519 --date 2026-06-24 --mode "买入前检查"
```

Anti-dependency Mode 会先展示原始财务数据摘要，要求用户提交人工判断后，才解锁系统评分和 Qwen 对比复盘：

```bash
python main.py --code 600519 --date 2026-06-24 --mode "买入前检查" --anti-dependency
```

输入人工判断时可多行输入，单独输入 `END` 提交。

输出位置：

- `data/raw/`：原始抓取数据。
- `data/processed/`：清洗数据、指标、评分、风险红旗和 LLM 中间结果。
- `data/output/`：最终 Markdown 简报。

## 数据源补充

- `src/data_fetcher/astock_data_provider.py` 已加入 a-stock-data 补充数据源封装，来源：[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)。
- 当前补充数据源仅作为独立可调用模块存在，尚未接入主分析流程、评分、报告或 LLM prompt。

## 数据质量闸门

- 当前仅支持 A 股主板普通股票，默认接受 `600/601/603/605/000/001/002` 开头的 6 位代码。
- 数据质量分为 `fatal/warning/info`。`fatal` 时只输出数据失败报告，不生成财务评分、LLM 分析或使用建议。
- `warning` 时继续输出报告，但顶部会标记为“降级分析”，并展示具体数据质量影响。

## 原则

- LLM 不参与原始财务计算，只负责解释、摘要和审核。
- 金额字段在清洗阶段统一标准化为“元”，与 AKShare 行情市值字段保持一致。
- 缺失数据保留为 `None` 或 `missing`，不随意填 0。
- 只使用 `publish_date <= analysis_date` 的财务数据和公告。
- 东方财富网相关 AKShare 接口必须先启用 `akshare-proxy-patch`。
