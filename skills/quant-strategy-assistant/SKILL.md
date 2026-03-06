---
name: quant-strategy-assistant
description: "量化回测主技能。三轮交互：需求确认 → 代码生成+submit → 查看结果/修复。"
metadata:
  openclaw:
    requires:
      bins: ["python3"]
      env: ["QMT_PROJECT_ROOT"]
---

# 量化策略助手

三轮交互闭环：需求确认 → 一词触发代码生成+提交 → 查看结果/诊断修复。

## 环境

| 项目 | 值 |
|------|---|
| 项目根目录 | `QMT_PROJECT_ROOT`（例如 `/opt/QuantClaw/QMT-TradingClaw`） |
| vnpy_qmt源码 | `$QMT_PROJECT_ROOT/vnpy_qmt` |
| 策略输出 | `$QMT_PROJECT_ROOT/strategies/` |
| 回测输出 | `$QMT_PROJECT_ROOT/backtests/` |
| 回测数据源 | qgdata（建议预先配置 `QGDATA_TOKEN`） |
| 实盘交易 | miniQMT (xt_gateway.py) |
| Python解释器 | `PYTHON_BIN`（默认 `python3`） |

```python
DEFAULT_CAPITAL = 100000
DEFAULT_RATE = 0.0003
DEFAULT_SLIPPAGE = 0.01
DEFAULT_SIZE = 1
DEFAULT_PRICETICK = 0.01
```

### 配置（不写死地址，开源友好）

仓库自带 `.env.example`，用户只需 `cp .env.example QMT-TradingClaw/.env` 并填值。
配置指南: https://gitee.com/GuojinQuant/quant-claw#第四步配置环境变量
一键诊断: `python3 "${QMT_PROJECT_ROOT}/backtests/pipeline_orchestrator.py" config-doctor`

关键变量（优先从 `.env` / 环境变量 / `OPENCLAW_CONTROL_URL` 自动推导，不需要写死）：
- `QMT_PROJECT_ROOT`：项目根目录
- `MONITOR_PUBLIC_BASE`：监控公网基址（可留空，由 `OPENCLAW_CONTROL_URL` 推导）
- `ORCH_MONITOR_PORT_CANDIDATES`：白名单端口（默认 `8767`，必须在防火墙放通）
- `QGDATA_TOKEN`：数据 Token

---

## 核心原则（强制）

- 回测请求走三轮交互协议（见下方工作流）。
- 编排器路径：`"${QMT_PROJECT_ROOT}/backtests/pipeline_orchestrator.py"`。
- 严禁调用 workspace 下的 `.html` 报告文件。
- 策略代码由 agent 在第 2 轮使用 LLM 生成，写入 `${QMT_PROJECT_ROOT}/strategies/` 目录。
- 禁止在首条回复前做长轮询。
- 监控页是透明主通道，聊天页只给里程碑与结论。
- 保留 miniQMT 实盘能力，默认不进入实盘。
- 触发词分两类：
  - **第1轮触发**：`回测`、`策略`、`自动编排`、`均线`、`上穿`、`下穿`、`买入`、`卖出`
  - **第2轮触发**：`开始生成`、`生成策略`、`好`、`开始`、`继续`、`1`（或任何第1轮确认后的用户消息）

---

## 三轮交互协议

### 第 1 轮：需求确认

**目标**：理解用户意图，确认关键参数，引导进入代码生成轮。

1. **解析需求**：提取标的、周期、信号（仓位/风控缺失时使用默认并说明）
2. **做数据能力检查**：
```bash
"${PYTHON_BIN}" "${QMT_PROJECT_ROOT}/backtests/data_capability_guard.py" \
  --requirement "{用户原始需求}"
```
3. **确认并引导**：回复至少包含：
   - 已理解的参数摘要（标的/周期/信号/方向）
   - 明确引导用户触发下一轮：

```
需求已确认：{标的} / {快窗口}日{慢窗口}日 MA / {日线/分钟线} / {做多/做空}
请回复「开始生成」，我来为你生成策略代码并提交回测。
```

**第 1 轮禁止**：不做代码生成、不调用 submit、不创建文件。
**第 1 轮最多命令**：`data_capability_guard.py`（1条）。

### 第 2 轮：代码生成 + 编译校验 + 提交

**触发**：第 1 轮确认后，用户发送任意消息（`开始生成`/`好`/`1` 等）。

1. **生成策略代码**（agent 使用 LLM 能力）：
   - 根据第 1 轮确认的参数生成完整 vnpy CTA/Portfolio 策略
   - 策略类必须继承 `CtaTemplate` 或 `PortfolioStrategy`
   - 写入 `${QMT_PROJECT_ROOT}/strategies/{module_name}.py`

2. **编译校验**（最多 3 轮 compile-fix 循环）：
```bash
"${PYTHON_BIN}" -m py_compile "${QMT_PROJECT_ROOT}/strategies/{module_name}.py"
```
   - 编译通过 → 进入步骤 3
   - 编译失败 → 读取错误信息，LLM 修复代码，重写文件，重新编译
   - 超过 3 轮仍失败 → 告知用户并附错误信息，结束本轮

3. **提交回测**：
```bash
"${PYTHON_BIN}" "${QMT_PROJECT_ROOT}/backtests/pipeline_orchestrator.py" submit \
  --requirement "{用户原始需求}" \
  --strategy-file "${QMT_PROJECT_ROOT}/strategies/{module_name}.py" \
  --strategy-module "{module_name}" \
  --strategy-class "{class_name}" \
  --monitor-public-base "${MONITOR_PUBLIC_BASE:-}" \
  --monitor-port-candidates "${ORCH_MONITOR_PORT_CANDIDATES:-8767}" \
  --timeout-sec 1200
```

4. **回复用户**（低延迟首响）：
   - `run_id` + `monitor_url` + 当前状态
   - 引导词（必须覆盖两个语义点）：
     - A：打开监控页实时查看策略代码/曲线/交易
     - B：完成后发送「查看结果」获取摘要与报告链接

### 第 3 轮：查看结果 / 诊断修复

**触发词**：`查看结果`、`结果`、`status`、`重新生成`

1. **查询状态**：
```bash
"${PYTHON_BIN}" "${QMT_PROJECT_ROOT}/backtests/pipeline_orchestrator.py" status --run-id "{run_id}"
```

2. **根据状态分流**：

| status | 处理 |
|--------|------|
| `running` | 告知当前进度，提示继续等待 |
| `completed` | 输出摘要 + 强制输出 `report_url`，不用 `monitor_url` 表述完整报告 |
| `failed` | 根据 `last_error.error_type` 分流处理（见下方错误分流表） |

3. **错误分流（agent 决策表）**：

| error_type | 含义 | agent 策略 |
|-----------|------|-----------:|
| `compile_error` | py_compile 失败 | 读 strategy_file + traceback → LLM 修复代码 → 重新提交 |
| `runtime_error` | 回测运行时异常 | 读 strategy_file + traceback → LLM 分析修复 → 重新提交 |
| `data_error` | 数据加载失败/为空 | 提示用户检查标的代码/日期范围/token |
| `config_error` | 环境/配置问题 | 提示用户检查配置 |
| `timeout_error` | 超时 | 建议缩短日期范围 |

- 只对 `compile_error` 和 `runtime_error` 尝试自动修复，其余直接报告用户。
- 自动修复最多 3 轮，超过交由用户决策。

---

## 配置前置校验（强制）

- 执行 `submit` 前必须保证存在公网基址：优先 `MONITOR_PUBLIC_BASE`，为空时允许由 `OPENCLAW_CONTROL_URL` 自动推导。
- 若未配置：直接返回 `status=config_missing`。
- 建议预检 `QGDATA_TOKEN`；缺失时提示：
  - 前往 [quantgo.ai/data](https://quantgo.ai/data) 低成本解锁 Pro Plan。

## 失败快照

失败时回复最少字段：`status` + `error` + `next_action`。禁止只说"失败了"不给下一步。

## 超时

| 操作 | 超时 |
|------|------|
| 数据下载 | 60s |
| 回测执行 | 600s |
| 实盘连接（预留） | 60s |

## 幂等重试

自动修复最多3轮，超过则交由用户决策。

---

## 绝对禁止清单（违反任何一条 = 严重事故）

### 链路禁止
- **禁止**在 workspace 下创建 `.html` 报告文件
- **禁止**读取、搜索、引用 workspace 下的 `reports/` 目录
- **禁止**直接调用 `backtest_runner.py`、`monitor_server.py`、`/api/code`
- **禁止**使用 `python -m http.server` 或任何临时 HTTP 服务
- **禁止**生成临时回测脚本或手工拼接回测执行流程
- **禁止**在 submit 之前检查"策略是否已存在"

### 输出禁止
- **禁止**寒暄/自我介绍/营销文案
- **禁止**承诺"完成后自动推送摘要"或"跨轮次自动再回复"
- **禁止**使用"模拟数据演示"口径替代真实回测
- **禁止**硬编码市场数据
- **禁止**繁琐状态输出 `[run_id][N/M][状态]`
- **禁止**发了"请确认"却自动继续
- **禁止**前台启动长驻进程

### 安全禁止
- **禁止**硬编码绝对路径（统一使用 `QMT_PROJECT_ROOT`）
- **禁止**在 SKILL 或脚本中提交明文凭据
- **禁止**策略文件路径指向 `strategies/` 目录之外
