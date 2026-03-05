# Quant Claw（量化回测自动编排）

这是一个面向初学者也能上手的量化策略执行仓库：  
你只需要给一句自然语言需求（例如“贵州茅台 5 日线上穿 10 日线买入，下穿卖出”），系统会自动完成：

1. 数据能力检查（是否满足该策略的数据接口要求）
2. 策略生成
3. 回测执行
4. 监控页实时展示（代码、进度、资金曲线、交易记录）

## 适合谁用

- 想快速验证策略想法的量化研究者
- 想做“用户一句话 -> 自动回测”的 AI/Agent 集成开发者
- 希望把回测过程做成“全程透明监控页”的团队

## 仓库内容（已去除临时测试产物）

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

## 环境要求

- Python 3.10 及以上
- 可用的 `QGDATA_TOKEN`（用于历史数据）
- Linux 或 Windows（均可）

## 第一步：安装依赖

在仓库根目录执行：

```bash
pip install -U pip
pip install qgdata filelock
pip install -e QMT-TradingClaw/vnpy_qmt
```

## 第二步：配置环境变量

### Linux/macOS

```bash
export QMT_PROJECT_ROOT="$(pwd)/QMT-TradingClaw"
export PYTHON_BIN="python3"
export QGDATA_TOKEN="你的qgdata_token"
export MONITOR_PUBLIC_BASE="http://你的公网IP或域名"
export ORCH_MONITOR_PORT_CANDIDATES="8761,8767"
```

### Windows（PowerShell）

```powershell
$env:QMT_PROJECT_ROOT = "$pwd\QMT-TradingClaw"
$env:PYTHON_BIN = "python"
$env:QGDATA_TOKEN = "你的qgdata_token"
$env:MONITOR_PUBLIC_BASE = "http://你的公网IP或域名"
$env:ORCH_MONITOR_PORT_CANDIDATES = "8761,8767"
```

## 第三步：执行一次自动编排回测

先做能力闸门检查：

```bash
"$PYTHON_BIN" "$QMT_PROJECT_ROOT/backtests/data_capability_guard.py" \
  --requirement "海天味业，5日上穿10日金叉买入，死叉卖出"
```

再提交编排任务：

```bash
"$PYTHON_BIN" "$QMT_PROJECT_ROOT/backtests/pipeline_orchestrator.py" submit \
  --requirement "海天味业，5日上穿10日金叉买入，死叉卖出" \
  --monitor-public-base "$MONITOR_PUBLIC_BASE" \
  --monitor-port-candidates "${ORCH_MONITOR_PORT_CANDIDATES:-8761,8767}" \
  --timeout-sec 1200
```

你会立即拿到：

- `run_id`
- `monitor_url`

打开 `monitor_url` 即可实时查看整个执行过程。

## 查看结果摘要

如果你只想要文本摘要，可以按 `run_id` 查询：

```bash
"$PYTHON_BIN" "$QMT_PROJECT_ROOT/backtests/pipeline_orchestrator.py" status --run-id "你的run_id"
```

## 常见问题

### 1）监控链接打不开

- 确认 `MONITOR_PUBLIC_BASE` 是公网地址，不是 `localhost`/`0.0.0.0`/内网 IP。
- 确认安全组或防火墙放行 `ORCH_MONITOR_PORT_CANDIDATES` 配置的端口。

### 2）提示 token 无效

- 检查 `QGDATA_TOKEN` 是否正确、是否过期、是否有对应 API 权限。

### 3）为什么不自动在聊天窗口二次推送摘要

- 当前流程优先保证“首响立即返回监控链接”。  
- 回测完成后，请主动执行 `status --run-id` 或在监控页查看结果。

## 安全建议

- 不要把 `.env` 或 token 提交到仓库。
- 上云部署时，建议使用环境变量注入密钥，不要硬编码在脚本中。
