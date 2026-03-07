# Quant Claw（量化回测自动编排）

这是一个面向初学者也能上手的量化策略执行仓库：  
你只需要给一句自然语言需求（例如“贵州茅台 5 日线上穿 10 日线买入，下穿卖出”），系统会自动完成：

1. 数据能力检查（是否满足该策略的数据接口要求）
2. 自动判定策略类型（CTA 单标的 / Portfolio 多标的组合）
3. 策略代码生成（LLM 根据自然语言自动编写 vnpy 策略）
4. 回测执行（支持日线/5分钟/15分钟/30分钟/小时线/周线，内置 A 股 T+1 合规兜底）
5. 监控页实时展示（代码、进度、收益曲线动态增长、交易记录含标的、每日持仓变化）

## 适合谁用

- 想快速验证策略想法的量化研究者
- 想做“用户一句话 -> 自动回测”的 AI/Agent 集成开发者
- 希望把回测过程做成“全程透明监控页”的团队

## 仓库内容

```text
quant-claw/
├── README.md
├── skills/
│   └── quant-strategy-assistant/
│       ├── SKILL.md
│       └── qgdata-reference.md
└── QMT-TradingClaw/
    ├── backtests/
    │   ├── pipeline_orchestrator.py
    │   ├── data_capability_guard.py
    │   ├── backtest_runner.py
    │   └── monitor_server.py
    ├── qgdata_docs/
    ├── strategies/
    └── vnpy_qmt/
```

> 说明：仓库不包含临时回测结果（html/png/log/json）和缓存文件。

## 小白先看：你需要先准备什么

在运行前，请先准备下面 4 项：

1. **Python 环境**：建议 `Python 3.10+`
2. **OpenClaw 环境**（如果你要用 Skill 方式一句话触发）
3. **LLM API Key**（给 OpenClaw 用，用于理解需求和生成策略）
4. **qgdata Pro 权限 + Token**（用于稳定获取历史行情/财务等数据）

> 如果你暂时不接 OpenClaw，也可以只用本仓库的 Python 脚本直接回测；但要有 `QGDATA_TOKEN`。
>
> **回测与实盘分离**：回测基于 vnpy 引擎，**任何平台**均可运行，不依赖 QMT。支持 CTA（单标的择时）和 Portfolio（多标的组合/轮动）两种策略模式，系统根据自然语言描述自动路由。支持多种 K 线周期（日线/5分钟/15分钟/30分钟/小时线/周线），分钟级回测内置 A 股 T+1 合规兜底（当日买入不可当日卖出）。模拟盘/实盘需要 QMT 交易端，运行 `qmt-check` 可一键检测环境是否就绪。

## 依赖与账户清单（建议逐项打勾）

- [ ] 已安装 `Python 3.10+`
- [ ] 已安装 `pip`
- [ ] 已安装 OpenClaw（用于加载 `skills/quant-strategy-assistant`）
- [ ] 已配置一个可用的 LLM API（OpenAI 兼容接口即可）
- [ ] 已在 qgdata 平台开通 Pro 并拿到 `QGDATA_TOKEN`
- [ ] 有一个可公网访问的 IP/域名（用于监控链接）
- [ ] 安全组/防火墙放通监控白名单端口（默认 `8767`）
- [ ] 若要模拟盘/实盘，已安装并启动 QMT 交易端（系统自动检测可用性）

## 第一步：安装 Python 依赖

在仓库根目录执行：

```bash
pip install -U pip
pip install qgdata filelock vnpy_portfoliostrategy
pip install -e QMT-TradingClaw/vnpy_qmt
```

## 第二步：开通并配置 LLM API（给 OpenClaw 用）

如果你通过 OpenClaw 调用本 Skill，需要在 OpenClaw 的配置里填好 LLM API（常见是 OpenAI 兼容格式）：

- `LLM_API_KEY`
- `LLM_BASE_URL`（如果你用第三方兼容网关）
- `LLM_MODEL`

不同 OpenClaw 版本配置字段可能略有差异，但核心就是 **Key + Base URL + Model** 三项。

## 第三步：开通 qgdata Pro 并获取 Token

1. 访问 qgdata 官网并注册/登录  
2. 开通 Pro（或包含你所需接口权限的套餐）  
3. 在控制台获取 `token`  
4. 用下面命令配置为环境变量 `QGDATA_TOKEN`

> 没有 Pro 或权限不足时，常见报错会表现为数据拉取失败、接口无权限或 token 检查失败。

## 第四步：配置环境变量

仓库自带 `.env.example` 模板，**3 步搞定**：

```bash
# 1. 复制模板
cp .env.example QMT-TradingClaw/.env

# 2. 编辑填入你的值（至少填 QGDATA_TOKEN 和 MONITOR_PUBLIC_BASE）
vim QMT-TradingClaw/.env

# 3. 一键诊断，确认全部 PASS
python3 QMT-TradingClaw/backtests/pipeline_orchestrator.py config-doctor
```

> `config-doctor` 会逐项检查 QUANTCLAW_ROOT、PYTHON_BIN、MONITOR_PUBLIC_BASE、端口连通性、QGDATA_TOKEN 等，FAIL 项会给出修复提示。

<details>
<summary>如果不想用 .env 文件，也可以直接 export（点击展开）</summary>

### Linux/macOS

```bash
export QUANTCLAW_ROOT="$(pwd)/QMT-TradingClaw"
export PYTHON_BIN="python3"
export QGDATA_TOKEN="你的qgdata_token"
export MONITOR_PUBLIC_BASE="http://你的公网IP或域名"
export ORCH_MONITOR_PORT_CANDIDATES="8767"
```

### Windows（PowerShell）

```powershell
$env:QUANTCLAW_ROOT = "$pwd\QMT-TradingClaw"
$env:PYTHON_BIN = "python"
$env:QGDATA_TOKEN = "你的qgdata_token"
$env:MONITOR_PUBLIC_BASE = "http://你的公网IP或域名"
$env:ORCH_MONITOR_PORT_CANDIDATES = "8767"
```

</details>

## 第五步：执行一次自动编排回测

先做能力闸门检查：

```bash
"$PYTHON_BIN" "$QUANTCLAW_ROOT/backtests/data_capability_guard.py" \
  --requirement "海天味业，5日上穿10日金叉买入，死叉卖出"
```

再提交编排任务：

```bash
"$PYTHON_BIN" "$QUANTCLAW_ROOT/backtests/pipeline_orchestrator.py" submit \
  --requirement "海天味业，5日上穿10日金叉买入，死叉卖出" \
  --monitor-public-base "$MONITOR_PUBLIC_BASE" \
  --monitor-port-candidates "${ORCH_MONITOR_PORT_CANDIDATES:-8767}" \
  --timeout-sec 1200
```

你会立即拿到：

- `run_id`
- `monitor_url`

打开 `monitor_url` 即可实时查看整个执行过程。

## 第六步：查看结果摘要

如果你只想要文本摘要，可以按 `run_id` 查询：

```bash
"$PYTHON_BIN" "$QUANTCLAW_ROOT/backtests/pipeline_orchestrator.py" status --run-id "你的run_id"
```

## 常见问题

### 1）监控链接打不开

- 运行 `python3 QMT-TradingClaw/backtests/pipeline_orchestrator.py config-doctor` 一键诊断。
- 确认 `MONITOR_PUBLIC_BASE` 是公网地址，不是 `localhost`/`0.0.0.0`/内网 IP。
- 确认安全组/防火墙放通白名单端口（默认 `8767`，通过 `ORCH_MONITOR_PORT_CANDIDATES` 配置）。
- 端口采用白名单策略：只使用你显式声明的端口，公网不可达时 submit 会立即失败并提示原因，不会出现"回测成功但监控页打不开"的情况。

### 2）提示 token 无效或无权限

- 检查 `QGDATA_TOKEN` 是否正确、是否过期。
- 检查 qgdata 账户是否已开通 Pro，且当前策略涉及的接口已授权。

### 3）为什么策略没跑起来，提示 LLM 相关错误

- 检查 OpenClaw 的 LLM 配置是否完整（API Key / Base URL / Model）。
- 检查模型账户余额、速率限制、模型名是否拼写正确。

### 4）为什么不自动在聊天窗口二次推送摘要

- 当前流程优先保证“首响立即返回监控链接”。  
- 回测完成后，请主动执行 `status --run-id` 或在监控页查看结果。

### 5）回测需要 QMT 吗

- **不需要。** 回测基于 vnpy 引擎，任何平台均可运行。
- 模拟盘/实盘依赖 QMT 交易端，可通过 `qmt-check` 命令检测环境是否就绪：

```bash
python3 QMT-TradingClaw/backtests/pipeline_orchestrator.py qmt-check
```

需配置 `QMT_PATH`（QMT 安装目录）和 `QMT_ACCOUNT_ID`（资金账号），详见 `.env.example`。

### 6）支持哪些 K 线周期

| 周期 | 参数 | 说明 |
|------|------|------|
| 日线 | `DAILY` | 默认周期 |
| 5 分钟 | `5MIN` | A 股最常用分钟级别，数据源 qgdata 直接提供 |
| 15 分钟 | `15MIN` | |
| 30 分钟 | `30MIN` | |
| 小时线 | `HOUR` | 60 分钟 |
| 周线 | `WEEKLY` | |

分钟级回测自动启用 A 股 T+1 合规兜底：当日买入的股数标记"锁定"，当日卖出信号自动扣减锁定部分，仅可卖出昨日及以前的持仓。

### 7）监控页有哪些面板

- 📋 策略描述 — 需求参数确认
- 💻 策略代码 — 语法高亮展示
- 📈 收益曲线 — 从左到右动态增长 + 沪深300基准同步对比
- 📊 每日收益 — 柱状图
- 📉 回测统计 — 核心指标表
- 📝 交易记录 — 含标的列、分页
- 📦 每日持仓变化 — 逐日持仓快照

## 安全建议

- `.env` 已在 `.gitignore` 中，不会被提交；`.env.example` 不含真实密钥，可以提交。
- 上云部署时，建议使用环境变量注入密钥，不要硬编码在脚本中。
- 部署后运行 `config-doctor` 确认配置无误再使用。
