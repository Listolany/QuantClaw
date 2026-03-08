# qgdata 数据能力参考

## 初始化

```python
import qgdata as qg
qg.set_token("token")
pro = qg.pro_api(timeout=30.0)
```

调用：`pro.接口名(参数...)` → `pd.DataFrame`。完整文档：`${QUANTCLAW_ROOT}/qgdata_docs/`

## 代码格式转换

qgdata `.SZ/.SH/.BJ` ↔ vnpy `.SZSE/.SSE/.BSE`：

```python
QG2VN = {"SZ": "SZSE", "SH": "SSE", "BJ": "BSE"}
VN2QG = {v: k for k, v in QG2VN.items()}
def qg2vnpy(c): s,e = c.split("."); return f"{s}.{QG2VN[e]}"
def vnpy2qg(c): s,e = c.split("."); return f"{s}.{VN2QG[e]}"
```

---

## 数据需求→能力映射表

**收到用户需求后，对照此表判断所需数据是否可获取。能查的查，不能查的必须告知用户。**

### ✅ 支持的数据类型

| 用户需求关键词 | 数据类型 | qgdata API | 用法要点 |
|---|---|---|---|
| 板块/概念/行业/题材 | 板块成分 | `ths_index` + `ths_member` | 先搜板块名→取ts_code→查成分con_code |
| 东财板块 | 板块成分 | `dc_index` + `dc_member` | 需传trade_date |
| 通达信板块 | 板块成分 | `tdx_index` + `tdx_member` | 需传trade_date |
| PE/PB/市值/估值/换手率 | 每日指标 | `daily_basic` | ts_code+trade_date |
| 营收/利润/ROE/财务 | 财务指标 | `fina_indicator` | period=季度末YYYYMMDD |
| 利润表/资产负债/现金流 | 财报 | `income`/`balancesheet`/`cashflow` | period+report_type |
| 资金流入/主力/北向 | 资金流向 | `moneyflow`/`moneyflow_ths`/`moneyflow_dc` | ts_code+trade_date |
| 北向/沪港通 | 北向资金 | `moneyflow_hsgt`/`hsgt_top10` | trade_date |
| 筹码/套牢盘/获利比例 | 筹码分布 | `cyq_chips`/`cyq_perf` | ts_code+trade_date |
| 龙虎榜/游资 | 龙虎榜 | `top_list`/`top_inst`/`hm_detail` | trade_date |
| 涨停/跌停/连板 | 涨跌停 | `limit_list_d`/`limit_step`/`limit_cpt_list` | trade_date |
| 融资融券/两融 | 融资融券 | `margin`/`margin_detail` | trade_date |
| 大宗交易 | 大宗 | `block_trade` | ts_code+trade_date |
| 股东/十大股东/股东人数 | 股东 | `top10_holders`/`stk_holdernumber` | ts_code+period |
| 股权质押 | 质押 | `pledge_stat`/`pledge_detail` | ts_code |
| 分红/送转 | 分红 | `dividend` | ts_code |
| 日K/周K/月K/分钟线 | 行情 | `daily`/`weekly`/`monthly`/`stk_mins` | ts_code+日期 |
| 交易日历/节假日/是否交易日 | 日历 | `trade_cal` | exchange(SSE/SZSE)+start_date+end_date，返回cal_date+is_open |
| 复权因子/前复权/后复权 | 复权 | `adj_factor` | ts_code+trade_date，用于长周期价格修正 |
| 停牌/复牌/是否可交易 | 停复牌 | `suspend_d` | ts_code+trade_date，suspend_type=S停/R复 |
| 涨停价/跌停价/一字板 | 涨跌停价 | `stk_limit` | ts_code+trade_date，返回up_limit/down_limit |
| 技术因子/MACD/RSI | 因子 | `stk_factor_pro` | ts_code+日期范围 |
| 热门股/人气排名 | 热榜 | `ths_hot`/`dc_hot` | trade_date |
| 券商金股/机构推荐 | 研报 | `broker_recommend` | month |
| 机构调研 | 调研 | `stk_surv` | ts_code |
| 业绩预告/快报 | 业绩 | `forecast`/`express` | ts_code+period |
| ST/风险警示 | 风控 | `stock_st`/`st` | - |

### ❌ 不支持的数据类型

| 用户需求 | 原因 | 建议处理 |
|---|---|---|
| 实时行情/盘口/Level2 | qgdata为历史数据，实时需XT数据源 | 告知"回测可用qgdata，实盘行情由QMT提供" |
| 新闻/舆情/社交媒体情绪 | 无此类API | 坦诚告知，建议用技术面/资金面替代 |
| 宏观经济/GDP/CPI | 无宏观数据 | 告知不支持 |
| 期货/期权行情 | qgdata仅覆盖A股 | 告知需要XT数据源 |
| ETF/LOF/基金净值与行情 | 当前接口集合无`fund_daily/fund_basic`可用 | 告知改用股票标的回测，或使用XT/其他基金数据源 |
| 基金/债券净值 | 无此类数据 | 告知不支持 |
| 自定义另类数据 | 无接口 | 告知需要用户自行提供数据文件 |
| 实时资金流/实时筹码 | 仅盘后数据 | 告知数据为T+1 |

---

## 查询模板

### 板块成分查询

```python
# 同花顺：搜板块→取成分
idx = pro.ths_index(exchange='A', type='N') #N=概念 I=行业
hit = idx[idx['name'].str.contains('关键词', na=False)]
if hit.empty: print("未找到匹配板块"); # → 告知用户
else:
    members = pro.ths_member(ts_code=hit.iloc[0]['ts_code'])
    codes = members[members['is_new']=='Y']['con_code'].tolist()
    vt_symbols = [qg2vnpy(c) for c in codes]
```

### 财务筛选（如"PE最低的N只"）

```python
df = pro.daily_basic(trade_date='最近交易日', fields='ts_code,pe,pb,total_mv,turnover_rate')
df = df.dropna(subset=['pe'])
df = df[df['pe'] > 0] #排除负PE
top = df.nsmallest(20, 'pe')['ts_code'].tolist()
vt_symbols = [qg2vnpy(c) for c in top]
```

### 资金流选股（如"主力净流入最大"）

```python
df = pro.moneyflow(trade_date='最近交易日')
top = df.nlargest(10, 'net_mf_amount')['ts_code'].tolist() #主力净流入前10
vt_symbols = [qg2vnpy(c) for c in top]
```

### 涨停股/连板股

```python
df = pro.limit_list_d(trade_date='最近交易日', limit_type='U') #U=涨停
codes = df['ts_code'].tolist()
```

### 交易日历（判断交易日/取前后N个交易日）

```python
cal = pro.trade_cal(exchange='SSE', start_date='20260101', end_date='20261231', is_open='1')
trade_dates = cal['cal_date'].tolist()  # 全年交易日列表
# 判断某日是否交易日：date_str in trade_dates
```

### 成分股数量预筛

成分股超过30只时应预筛，减少回测数据下载量：

```python
# 按市值取前N只
basics = pro.daily_basic(trade_date='最近交易日')
filtered = basics[basics['ts_code'].isin(codes)].nlargest(20, 'total_mv')
codes = filtered['ts_code'].tolist()
```

---

## 数据能力评估流程（agent必须遵守）

```
用户需求 → 提取所需数据类型 → 查映射表
    ├─ 全部支持 → 继续，记录查询方案
    ├─ 部分支持 → 告知用户：
    │    "您的需求涉及A和B两类数据，A可以通过qgdata获取，B（具体说明）当前数据源不支持。
    │     建议方案：1) 仅用A数据实现（降级） 2) 您自行提供B数据 3) 换一个思路"
    └─ 完全不支持 → 坦诚告知：
         "当前数据源不支持xxx类数据。建议：1) 换一个可实现的策略方向 2) ..."
```

**核心原则：能力边界内尽力而为，能力边界外坦诚告知，绝不虚构数据。**
