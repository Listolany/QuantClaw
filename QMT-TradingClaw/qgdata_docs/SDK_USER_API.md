# qgdata 用户接口文档

本文档基于当前服务端已注册接口（`qgdata-crawler/pipeline/config/sources.yaml`）整理，面向使用 `qgdata` 的调用方。

## 1. 安装与初始化

```bash
pip install qgdata
```

```python
import qgdata as qg

qg.set_token("your-token")
pro = qg.pro_api(timeout=30.0)
```

## 2. 通用调用方式

### 2.1 统一入口 `query`

```python
df = pro.query(
    "daily",
    ts_code="000001.SZ",
    trade_date="20260217",
    fields="ts_code,trade_date,open,high,low,close",
    order_by="trade_date",
    sort="desc",
    limit=200,
    offset=0,
)
```

### 2.2 动态方法（推荐）

```python
df = pro.daily(
    ts_code="000001.SZ",
    trade_date="20260217",
    limit=200,
)
```

动态方法与 `pro.query("daily", ...)` 完全等价，方法名即 `api_name`。

### 2.3 查询可用接口

```python
apis = pro.list_apis(enabled_only=True)
print(apis)
```

## 3. 通用参数约定

SDK 和服务端支持以下通用参数：
- `fields`: 字段白名单，支持 `"a,b,c"` 或 `["a", "b", "c"]`
- `order_by`: 排序字段，支持单字段或多字段
- `sort`: 排序方向，`asc` / `desc`（默认 `desc`）
- `limit`: 返回条数（默认 5000，最终受服务端 `max_limit` 限制，且服务端全局最大 6000）
- `offset`: 分页偏移（默认 0）

业务过滤参数（如 `ts_code`、`trade_date`、`freq`）通过 `**kwargs` 直接传入，服务端按“字段=值”或“字段 IN 列表”处理：

```python
df = pro.daily(ts_code=["000001.SZ", "000002.SZ"], trade_date="20260217")
```

`stk_mins` 的时间范围参数补充说明（按服务端规则）：
- `start_date/end_date` 支持 `YYYYMMDD` 或 `YYYY-MM-DD`
- 当接口时间字段为 `trade_time` 时，服务端自动补齐边界时间：
  - `start_date` -> `09:30:00`
  - `end_date` -> `15:00:00`
- 最终按 `trade_time >= start_date`、`trade_time <= end_date` 做区间过滤

```python
df = pro.stk_mins(
    ts_code="000001.SZ",
    freq="1min",
    start_date="2025-01-02",
    end_date="2025-01-02",
    fields="ts_code,trade_time,open,close",
    order_by="trade_time",
    sort="asc",
    limit=500,
)
```

## 4. 接口文档目录

以下接口按 `sources.yaml` 整理，部分接口已拆分为“每接口单文档”，点击可查看参数与示例。未列链接的接口可通过 `pro.接口名(...)` 直接调用，参数规则与通用约定一致。

### 4.1 基础数据

- [`stock_basic` 股票基础信息](apis/stock_basic.md)
- `stk_premarket` 股本情况（盘前）
- `trade_cal` 交易日历
- `stock_st` ST股票列表
- `st` ST风险警示板股票
- `stock_hsgt` 沪深港通股票列表
- `namechange` 股票曾用名
- `stock_company` 上市公司基本信息
- `stk_managers` 上市公司管理层
- `stk_rewards` 管理层薪酬和持股
- `bse_mapping` 北交所新旧代码对照表
- `new_share` IPO新股列表
- `bak_basic` 股票历史列表

### 4.2 行情数据

- [`stk_mins` 股票分钟级行情](apis/stk_mins.md)
- [`daily` 股票日线行情](apis/daily.md)
- [`stk_weekly_monthly` 股票周/月线行情（统一接口）](apis/stk_weekly_monthly.md)
- [`stk_week_month_adj` 股票周/月线复权行情](apis/stk_week_month_adj.md)
- [`weekly` 股票周线行情](apis/weekly.md)
- [`monthly` 股票月线行情](apis/monthly.md)
- `adj_factor` 复权因子
- [`daily_basic` 股票每日指标](apis/daily_basic.md)
- [`stk_limit` 股票涨跌停价格信息](apis/stk_limit.md)
- [`suspend_d` 股票停复牌信息](apis/suspend_d.md)
- `stk_auction` 当日集合竞价
- `stk_auction_o` 股票开盘集合竞价数据
- `stk_auction_c` 股票收盘集合竞价数据

### 4.3 沪深港通

- [`hsgt_top10` 沪深股通十大成交股](apis/hsgt_top10.md)
- [`ggt_top10` 港股通十大成交股](apis/ggt_top10.md)
- [`ggt_daily` 港股通每日成交统计](apis/ggt_daily.md)
- [`ggt_monthly` 港股通每月成交统计](apis/ggt_monthly.md)

### 4.4 财务数据

- [`income` 利润表](apis/income.md)
- [`balancesheet` 资产负债表](apis/balancesheet.md)
- [`cashflow` 现金流量表](apis/cashflow.md)
- [`forecast` 业绩预告](apis/forecast.md)
- [`express` 业绩快报](apis/express.md)
- [`dividend` 分红送股](apis/dividend.md)
- [`fina_indicator` 财务指标数据](apis/fina_indicator.md)
- [`fina_audit` 财务审计意见](apis/fina_audit.md)
- [`fina_mainbz` 主营业务构成](apis/fina_mainbz.md)
- [`disclosure_date` 财报披露计划](apis/disclosure_date.md)

### 4.5 股东与机构

- `top10_holders` 前十大股东
- `top10_floatholders` 前十大流通股东
- `pledge_stat` 股权质押统计数据
- `pledge_detail` 股权质押明细数据
- `repurchase` 股票回购
- `share_float` 限售股解禁
- `block_trade` 大宗交易
- `stk_holdernumber` 股东人数
- `stk_holdertrade` 股东增减持
- `report_rc` 卖方盈利预测数据
- `ccass_hold` 中央结算系统持股汇总
- `ccass_hold_detail` 中央结算系统持股明细
- `hk_hold` 沪深港股通持股明细

### 4.6 技术指标与筹码

- `cyq_perf` 每日筹码及胜率
- `cyq_chips` 每日筹码分布
- `stk_factor_pro` 股票技术面因子（专业版）
- `stk_nineturn` 神奇九转指标
- `stk_ah_comparison` AH股比价

### 4.7 融资融券与资金流向

- `margin_detail` 融资融券交易明细
- `margin_secs` 融资融券标的（盘前更新）
- `margin` 融资融券交易汇总
- `slb_len` 转融资交易汇总
- `moneyflow` 个股资金流向
- `moneyflow_ths` 个股资金流向（THS）
- `moneyflow_dc` 个股资金流向（DC）
- `moneyflow_cnt_ths` 同花顺概念板块资金流向（THS）
- `moneyflow_ind_ths` 同花顺行业资金流向（THS）
- `moneyflow_ind_dc` 东财概念及行业板块资金流向（DC）
- `moneyflow_mkt_dc` 大盘资金流向（DC）
- `moneyflow_hsgt` 沪深港通资金流向

### 4.8 龙虎榜与涨跌停

- `top_list` 龙虎榜每日明细
- `top_inst` 龙虎榜机构明细
- `limit_list_ths` 涨跌停榜单（同花顺）
- `limit_list_d` 涨跌停列表（新）
- `limit_step` 连板天梯
- `limit_cpt_list` 最强板块统计

### 4.9 板块与指数

- `ths_index` 同花顺概念和行业指数
- `ths_daily` 同花顺板块指数行情
- `ths_member` 同花顺概念板块成分
- `dc_index` 东方财富概念板块
- `dc_member` 东方财富概念板块成分
- `dc_daily` 东财概念板块行情
- `tdx_index` 通达信板块信息
- `tdx_member` 通达信板块成分
- `tdx_daily` 通达信板块行情

### 4.10 其他

- `stk_surv` 机构调研表
- `broker_recommend` 券商月度金股
- `hm_list` 游资名录
- `hm_detail` 游资每日明细
- `ths_hot` 同花顺热榜
- `dc_hot` 东方财富热榜
- `kpl_list` 开盘啦榜单数据
- `kpl_concept_cons` 开盘啦题材成分

## 5. 接口文档使用说明

- 接口目录按功能分类，与 `sources.yaml` 中 `enabled: true` 的接口一一对应
- 已有单文档的接口包含：接口简介、动态方法、默认时间字段、典型过滤参数、主要字段、调用示例
- 对于分表接口 `stk_mins`，文档中已单独标注必填参数和调用注意事项
- 未建单文档的接口可通过 `pro.接口名(...)` 调用，通用参数（`fields`、`order_by`、`limit` 等）均适用
- 如需确认当前环境可用接口，请先执行 `pro.list_apis(enabled_only=True)`

## 6. 异常处理

SDK 请求失败或业务失败会抛出 `PipelineSDKError`：

```python
from qgdata import PipelineSDKError

try:
    df = pro.query("daily", ts_code="000001.SZ", limit=10)
except PipelineSDKError as exc:
    print("message:", str(exc))
    print("code:", exc.code)
    print("detail:", exc.detail)
```

常见错误：
- `401 unauthorized`: token 缺失或无效
- `unknown api_name`: 接口名未注册
- `order_by field not found`: 排序字段不存在
- `invalid query response format`: 返回数据格式不符合约定

## 7. 调用建议

- 先通过 `list_apis()` 获取当前环境可用接口，再按接口调用
- 尽量显式指定 `fields`，减少传输与 DataFrame 内存占用
- 大数据量场景使用 `limit + offset` 分页拉取
- 对 `stk_mins` 优先加时间范围（如 `start_date/end_date`），避免全量扫描
