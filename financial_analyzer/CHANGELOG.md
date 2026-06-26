# Changelog

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
