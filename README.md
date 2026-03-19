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
4. **qgdata Token**（用于获取历史行情/财务等数据；未配置时自动使用内置共享试用Token，有每日额度限制）

> 如果你暂时不接 OpenClaw，也可以只用本仓库的 Python 脚本直接回测。未配置 `QGDATA_TOKEN` 时系统使用内置共享试用 Token，可免费体验（每日有限额度）。升级获取个人 Token：[https://quantgo.ai/data](https://quantgo.ai/data)
>
> **回测与实盘分离**：回测基于 vnpy 引擎，**任何平台**均可运行，不依赖 QMT。支持 CTA（单标的择时）和 Portfolio（多标的组合/轮动）两种策略模式，系统根据自然语言描述自动路由。支持多种 K 线周期（日线/5分钟/15分钟/30分钟/小时线/周线），分钟级回测内置 A 股 T+1 合规兜底（当日买入不可当日卖出）。模拟盘/实盘需要 QMT 交易端，运行 `qmt-check` 可一键检测环境是否就绪。

## 依赖与账户清单（建议逐项打勾）

- [ ] 已安装 `Python 3.10+`
- [ ] 已安装 `pip`
- [ ] 已安装 OpenClaw（用于加载 `skills/quant-strategy-assistant`）
- [ ] 已配置一个可用的 LLM API（OpenAI 兼容接口即可）
- [ ] 已获取 `QGDATA_TOKEN`（可选；未配置时使用内置共享试用Token）
- [ ] 有一个可公网访问的 IP/域名（云端部署需要；Windows 本地自用可走本地模式）
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

## 第三步：配置数据 Token（可选）

系统内置共享试用 Token，**无需配置即可免费体验**（每日有限额度）。超出额度或需要更多数据能力时：

1. 访问 [https://quantgo.ai/data](https://quantgo.ai/data) 注册/登录
2. 选择适合的套餐（Free/Pro/Ultra）
3. 在控制台获取个人 `token`
4. 配置为环境变量 `QGDATA_TOKEN`，或在 OpenClaw 对话中直接说"我的token是 xxx"

> 若首次需求被识别为 Portfolio（多标的轮动/组合）且未传 Token（将回落共享试用 Token）或正在使用共享试用 Token，第一轮确认会提前提示频率风险，避免回测中途受限。
>
> 若当天免费额度已用完，`submit` 会明确返回：`今日免费额度已用完（1次/天）。升级数据套餐可解除限制：https://quantgo.ai/data`。

## 第四步：配置环境变量

仓库自带 `.env.example` 模板，**3 步搞定**：

```bash
# 1. 复制模板
cp .env.example QMT-TradingClaw/.env

# 2. 编辑填入你的值（至少填 QGDATA_TOKEN；MONITOR_PUBLIC_BASE 视部署方式）
vim QMT-TradingClaw/.env

# 3. 一键诊断，确认全部 PASS
python3 QMT-TradingClaw/backtests/pipeline_orchestrator.py config-doctor
```

> `config-doctor` 会逐项检查 QUANTCLAW_ROOT、PYTHON_BIN、MONITOR_PUBLIC_BASE、端口连通性、QGDATA_TOKEN 等，FAIL 项会给出修复提示。  
> 本地模式说明：默认仅 Windows 自动识别为本地模式（可不填 `MONITOR_PUBLIC_BASE`，监控链接走 `127.0.0.1`）；Linux/macOS 若需本地模式请显式设置 `MONITOR_LOCAL_MODE=1`。全市场/大样本回测默认最多抽样 500 只股票，可用 `QC_POOL_MAX_STOCKS` 调整。

<details>
<summary>如果不想用 .env 文件，也可以直接 export（点击展开）</summary>

### Linux/macOS

```bash
export QUANTCLAW_ROOT="$(pwd)/QMT-TradingClaw"
export PYTHON_BIN="python3"
export QGDATA_TOKEN="你的qgdata_token"
export MONITOR_PUBLIC_BASE="http://你的公网IP或域名"
export ORCH_MONITOR_PORT_CANDIDATES="8767"
export QC_POOL_MAX_STOCKS="500"
# 本地自用（可选）：不走公网探测，直接返回 127.0.0.1 监控链接
# export MONITOR_LOCAL_MODE="1"
```

### Windows（PowerShell）

```powershell
$env:QUANTCLAW_ROOT = "$pwd\QMT-TradingClaw"
$env:PYTHON_BIN = "python"
$env:QGDATA_TOKEN = "你的qgdata_token"
$env:MONITOR_PUBLIC_BASE = "http://你的公网IP或域名"
$env:ORCH_MONITOR_PORT_CANDIDATES = "8767"
$env:QC_POOL_MAX_STOCKS = "500"
# Windows 本地自用可不填 MONITOR_PUBLIC_BASE；也可显式使用 localhost
# $env:MONITOR_PUBLIC_BASE = "http://127.0.0.1"
```

</details>

## 第五步：安装 OpenClaw Skill（一句话触发回测）

将仓库中的 Skill 文件复制到 OpenClaw 的 workspace 目录即可：

```bash
# 复制 quant-strategy-assistant 技能到 OpenClaw workspace
cp -r skills/quant-strategy-assistant ~/.openclaw/workspace/skills/
```

> **注意**：不要使用软链接（`ln -s`），OpenClaw 的安全机制会拒绝加载指向 workspace 外部的软链接。必须用 `cp -r` 复制实体文件。

安装后验证：

```bash
# 查看已安装技能列表，确认 quant-strategy-assistant 状态为 ✓ ready
openclaw skills list
```

输出中应能看到：

```
│ ✓ ready   │ 📦 quant-strategy-assistant │ 量化策略助手：自然语言→策略生成→回测→优化→... │ openclaw-workspace │
```

如果状态为 `✗ missing`，运行以下命令排查缺失项：

```bash
openclaw skills check
```

> **更新 Skill**：当开源包有新版本时，重新执行 `cp -r` 覆盖即可。

### 非 OpenClaw Agent 使用方式

如果你使用其他 AI Agent（MiniMax Agent、Claude Desktop 等），不需要安装 OpenClaw Skill，直接将 `skills/quant-strategy-assistant/SKILL.md` 作为 prompt 或参考文档提供给你的 Agent 即可。

前提条件：
- Agent 能读取本地文件
- Agent 能执行 `python` 命令并获取输出
- 已完成第一步到第四步的环境配置

Agent 需要执行的核心命令与 OpenClaw 完全一致：
- `python QMT-TradingClaw/backtests/pipeline_orchestrator.py submit --requirement "..." ...`
- `python QMT-TradingClaw/backtests/pipeline_orchestrator.py status --run-id "..."`

SKILL.md 中的三轮交互协议、策略生成规范、错误分流表对任何 Agent 通用。

## 第六步：执行一次自动编排回测（命令行方式）

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

## 第七步：查看结果摘要

如果你只想要文本摘要，可以按 `run_id` 查询：

```bash
"$PYTHON_BIN" "$QUANTCLAW_ROOT/backtests/pipeline_orchestrator.py" status --run-id "你的run_id"
```

## 常见问题

### 1）监控链接打不开

- 运行 `python3 QMT-TradingClaw/backtests/pipeline_orchestrator.py config-doctor` 一键诊断。
- 云端部署：确认 `MONITOR_PUBLIC_BASE` 是公网地址，不是 `localhost`/`0.0.0.0`/内网 IP。
- 本地部署：Windows 默认本地模式，可直接打开 `monitor_url_local`（`127.0.0.1`）；Linux/macOS 本地自用请设置 `MONITOR_LOCAL_MODE=1`。
- 确认安全组/防火墙放通白名单端口（默认 `8767`，通过 `ORCH_MONITOR_PORT_CANDIDATES` 配置）。
- 端口采用白名单策略：只使用你显式声明的端口，公网不可达时 submit 会立即失败并提示原因，不会出现"回测成功但监控页打不开"的情况。

### 2）提示 token 无效或无权限

- 检查 `QGDATA_TOKEN` 是否正确、是否过期。
- 检查 qgdata 账户是否已开通 Pro，且当前策略涉及的接口已授权。
- 如额度用尽或需要升级，前往 [https://quantgo.ai/data](https://quantgo.ai/data) 充值。
- 若共享免费额度已耗尽，submit 会返回：`今日免费额度已用完（1次/天）。升级数据套餐可解除限制：https://quantgo.ai/data`。
- 系统会在监控页显示⚠️警告并附带充值链接，点击即可跳转。

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

订单风控兜底（CTA/Portfolio 均生效）：
- 停牌检查：回测启动时预加载回测区间内停牌日历，停牌日下单直接废单（`suspended`）。
- 涨跌停检查：按交易日懒加载 `stk_limit`，当日首次下单才拉取一次，当日后续下单走内存缓存；命中涨跌停价格约束废单（`limit_up/limit_down`）。
- 降级策略：`stk_limit` 拉取失败不阻塞回测，仅输出 warn；有数据严格校验，无数据按原逻辑执行。
- 策略可感知：策略实例注入 `last_order_status`、`order_reject_log`、`order_reject_stats`，避免“以为下单成功”。

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

## 社区与支持
由祛魅量化(QuantGo)维护 一 致力于将量化投资的门槛一撸到底（只要你有交易想法）。
微信公众号/小红书 一 搜索“李斯托拉尼”
欢迎关注，我会不定期更新各种好用的AI量化工具。

