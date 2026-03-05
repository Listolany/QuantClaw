# VeighNa框架的QMT数据服务与交易接口

<p align="center">
  <img src ="https://vnpy.oss-cn-shanghai.aliyuncs.com/vnpy-logo.png"/>
</p>

<p align="center">
    <img src ="https://img.shields.io/badge/version-2.0.0-blueviolet.svg"/>
    <img src ="https://img.shields.io/badge/platform-windows|linux-yellow.svg"/>
    <img src ="https://img.shields.io/badge/python-3.10|3.11|3.12-blue.svg" />
    <img src ="https://img.shields.io/github/license/vnpy/vnpy.svg?color=orange"/>
</p>

## 说明

基于迅投XtQuant和qgdata封装开发的数据服务与交易接口，提供双数据源支持：

* **qgdata数据源（回测首选）**：A股日线/分钟线/周线行情，跨平台支持
* **迅投研(XT)数据源**：实时行情、Tick数据、期货/期权市场，Windows平台

支持以下中国金融市场：

* 股票、基金、债券、ETF期权：
  * SSE：上海证券交易所
  * SZSE：深圳证券交易所
  * BSE：北京证券交易所
* 期货、期货期权（仅XT数据源）：
  * CFFEX：中国金融期货交易所
  * SHFE：上海期货交易所
  * DCE：大连商品交易所
  * CZCE：郑州商品交易所
  * INE：上海国际能源交易中心
  * GFEX：广州期货交易所


## 安装

安装环境推荐基于3.9.0版本以上的【[**VeighNa Studio**](https://www.vnpy.com/)】。

直接使用pip命令：

```
pip install vnpy_xt qgdata
```

完成基础安装后，克隆本项目代码并替换官方文件：
```bash
git clone https://gitee.com/GuojinQuant/vnpy_qmt.git

# 将 vnpy_qmt/vnpy_xt/ 目录内文件覆盖至官方安装路径：
#   Linux/Mac: /usr/local/lib/python3.x/site-packages/vnpy_xt/
#   Windows:   %PYTHON_HOME%\Lib\site-packages\vnpy_xt\
#   提示：可通过 pip show vnpy_xt 查询确切安装路径
```

## 使用

### qgdata数据源连接（回测首选）

qgdata为回测默认数据源，支持A股日线、分钟线、周线行情查询，无需启动本地客户端，跨平台可用。

1. 安装qgdata：`pip install qgdata`
2. 获取token：访问 [**quantgo.ai/data**](https://quantgo.ai/data) 注册获取数据服务token
3. 在VeighNa Trader的【全局配置】处进行数据服务配置：
    * datafeed.name：qg
    * datafeed.username：留空
    * datafeed.password：填写您的qgdata token（请勿将token提交到版本控制）
4. 支持的数据周期：1分钟(MINUTE)、1小时(HOUR)、日线(DAILY)、周线(WEEKLY)
5. 支持的市场：**仅A股** — 上交所(SSE)、深交所(SZSE)、北交所(BSE)
6. 注意事项：
    * qgdata暂不支持Tick数据，如需Tick请切换至迅投研(XT)数据源
    * 期货/期权市场（CFFEX/SHFE/DCE/CZCE/INE/GFEX）不在qgdata覆盖范围，请使用迅投研(XT)数据源

若需切换数据源，修改 `vnpy_xt/__init__.py` 中的导入：
```python
# 切换为迅投研数据源
from .xt_datafeed import XtDatafeed as Datafeed
# 切换为qgdata数据源（默认）
# from .qg_datafeed import QgDatafeed as Datafeed
```

### 迅投研(XT)数据源连接

**Token连接**

- 请使用官方版本

**客户端连接**

- 请使用官方版本

**券商miniQMT连接**

1. 连接请先登录迅投极速交易终端，同时确保xtquant模块可以正常加载（点击【下载Python库】-【Python库下载】，下载完成后拷贝"Python库路径"下Lib\site-packages文件夹中的xtquant包到自己使用的Python环境的site_packages文件夹下）。
2. 在VeighNa Trader的【全局配置】处进行数据服务配置：
    * datafeed.name：xt
    * datafeed.username：client
    * datafeed.password：留空
3. 连接XT中配置：
    * token：留空
    * QMT路径：C:\国金QMT交易端模拟
    * 资金账户：填写您在券商开户的资金账号
4. 请注意以客户端方式连接时，需要保持迅投客户端的运行。

---

## OpenClaw量化策略助手

本项目集成了OpenClaw Skill，实现**一句话生成策略 -> 自动回测 -> 自动调优 -> 自动实盘**的全流程。

### 功能概览

| 步骤 | 说明 |
|------|------|
| 需求解析 | 一句话描述策略意图，自动提取标的/周期/信号 |
| 智能澄清 | 需求模糊时给出选项式问题 |
| 策略生成 | 自动选择CTA(单标的)或Portfolio(多标的)框架 |
| 自动回测 | 使用qgdata数据，生成净值曲线+核心指标 |
| 结果展示 | 可点击曲线链接（交互版/回放版/PNG）+沪深300基准对比 |
| 实盘运行 | 自动检测miniQMT，连接XtGateway运行策略 |

### 执行协议

- **状态机**：每次执行携带唯一`run_id`，每阶段输出`[run_id][阶段N/总数][状态]`格式的进度
- **心跳**：长时间任务每20-30秒自动汇报进度
- **防重入**：通过`backtests/.run_lock`锁文件防止重复执行
- **幂等重试**：自动修复最多3轮，超限交由用户决策
- **失败快照**：错误时附带阶段+错误类型+最后20行日志

### 实盘风控熔断

无需二次确认下单，但以下阈值强制生效：

| 阈值 | 默认值 | 触发动作 |
|------|--------|---------|
| 单笔最大金额 | 总资金20% | 拒绝下单 |
| 单日最大亏损 | 总资金5% | 自动停止策略 |
| 单日最大交易次数 | 50次 | 停止下单 |
| 连续亏损次数 | 5次 | 暂停策略 |
| 异常价格偏离 | 涨跌停价外 | 拒绝下单 |

可通过 `backtests/risk_config.json` 自定义阈值覆盖默认值。

### 回测执行 + 实时监控

回测使用通用执行器，支持实时监控页面：

```powershell
# 前台执行（等待完成）
py backtests\backtest_runner.py --strategy 模块名 --class 类名 --symbols "标的" --mode cta|portfolio

# 后台执行 + 实时监控页（推荐，立即返回监控链接）
Start-Process py -ArgumentList "backtests\backtest_runner.py --strategy 模块名 --class 类名 --symbols 标的 --mode cta --monitor-port 8765 --run-id 自定义ID" -RedirectStandardOutput "backtests\run.log" -NoNewWindow
# 浏览器打开 http://127.0.0.1:8765/runs/自定义ID 即可看到：
#   - 实时进度条
#   - 每10根K线更新的估算净值曲线（CTA模式）
#   - 完成后自动替换为精确净值+沪深300基准
#   - 统计指标卡片 + 日志流
```

执行器内置：防重入锁、token预检、本地缓存优先、monitor自动启停、HTML+PNG曲线（含沪深300基准）、摘要JSON。

### 文件结构

```
d:\AGIclass\QMT-TradingClaw\
├── vnpy_qmt/               # vnpy_qmt源码
├── strategies/              # 生成的策略文件
├── backtests/               # 回测结果(PNG/HTML)
│   ├── backtest_runner.py   # 通用回测执行器（含monitor集成）
│   ├── monitor_server.py    # 实时监控HTTP服务（SSE推送+ECharts页面）
│   ├── .run_lock            # 防重入锁（运行时自动生成/清除）
│   └── risk_config.json     # 实盘风控阈值（可选自定义）
└── README.md                # 本文档
```
