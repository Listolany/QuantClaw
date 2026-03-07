---
name: quant-strategy-assistant
description: "量化策略助手：自然语言→策略生成→回测→优化→QMT模拟/实盘。三轮交互闭环。"
metadata:
  openclaw:
    requires:
      bins: ["python3"]
---

# 量化策略助手

回测三轮交互闭环 → 用户按需选择参数优化 / 模拟实盘。

## 能力分层

| 能力 | 引擎 | 依赖 | 说明 |
|------|------|------|------|
| **CTA回测** | vnpy_ctastrategy | python3 + qgdata | 单标的择时策略，任意平台 |
| **Portfolio回测** | vnpy_portfoliostrategy | python3 + qgdata | 多标的组合/轮动策略，任意平台 |
| **参数优化** | vnpy OptimizationSetting | 同回测 | 回测后由用户触发，穷举/遗传算法 |
| **模拟/实盘** | miniQMT | QMT 交易端 | 运行 `qmt-check` 检测可用性，缺失时如实提示具体缺少项 |

回测是核心能力，不依赖 QMT。用户请求模拟/实盘时才运行 `qmt-check`。

### CTA vs Portfolio 自动路由（强制）

| 条件 | 模式 | 策略基类 |
|------|------|----------|
| 单一标的 + 无组合关键词 | `cta` | `CtaTemplate` |
| 多标的 / 含 `轮动/选股/组合/多标的/全市场/排列` | `portfolio` | `StrategyTemplate`（vnpy_portfoliostrategy） |

路由由 `parse_requirement()` 自动判定并写入 `parsed["mode"]`，agent 生成策略代码时必须使用对应基类。

### 模拟/实盘检测（独立流程，不走三轮协议）

用户提及 `模拟`/`实盘`/`QMT` 时触发：

```bash
"${PYTHON_BIN}" "${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py" qmt-check
```

输出 JSON 含 `ready`（布尔）和 `hint`（缺失项说明）：

- `ready=true` → 告知用户 QMT 环境已就绪。自动化模拟/实盘编排尚在开发中，当前可先完成回测验证策略
- `ready=false` → 将 `hint` 中的缺失项如实告知用户（不主动提及操作系统）

**禁止**在 `ready=true` 时编造不存在的模拟/实盘启动命令。

所需环境变量（仅模拟/实盘时需要，回测无关）：

| 变量 | 说明 |
|------|------|
| `QMT_PATH` | QMT 安装目录（含 `userdata_mini` 子目录） |
| `QMT_ACCOUNT_ID` | 资金账号 |

## 环境

| 项目 | 值 |
|------|---|
| 项目根目录 | `QUANTCLAW_ROOT`（兼容 `QMT_PROJECT_ROOT`） |
| vnpy_qmt源码 | `$QUANTCLAW_ROOT/vnpy_qmt` |
| 策略输出 | `$QUANTCLAW_ROOT/strategies/` |
| 回测输出 | `$QUANTCLAW_ROOT/backtests/` |
| 回测数据源 | qgdata（建议预先配置 `QGDATA_TOKEN`） |
| 实盘交易 | miniQMT (xt_gateway.py)，需 QMT 交易端已启动 |
| Python解释器 | `PYTHON_BIN`（默认 `python3`） |

```python
DEFAULT_CAPITAL = 1000000
DEFAULT_RATE = 0.0003
DEFAULT_SLIPPAGE = 0.01
DEFAULT_SIZE = 1
DEFAULT_PRICETICK = 0.01
```

### 配置（不写死地址，开源友好）

仓库自带 `.env.example`，用户只需 `cp .env.example QMT-TradingClaw/.env` 并填值。
配置指南: https://gitee.com/GuojinQuant/quant-claw#第四步配置环境变量
一键诊断: `python3 "${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py" config-doctor`

关键变量（优先从 `.env` / 环境变量 / `OPENCLAW_CONTROL_URL` 自动推导，不需要写死）：
- `QUANTCLAW_ROOT`：项目根目录（兼容 `QMT_PROJECT_ROOT`）
- `MONITOR_PUBLIC_BASE`：监控公网基址（可留空，由 `OPENCLAW_CONTROL_URL` 推导）
- `ORCH_MONITOR_PORT_CANDIDATES`：白名单端口（默认 `8767`，必须在防火墙放通）
- `QGDATA_TOKEN`：数据 Token

---

## 核心原则（强制）

- 回测请求走三轮交互协议（见下方工作流）。
- 编排器路径：`"${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py"`。
- 严禁调用 workspace 下的 `.html` 报告文件。
- 策略代码由 agent 在第 2 轮使用 LLM 生成，写入 `${QUANTCLAW_ROOT}/strategies/` 目录。
- 禁止在首条回复前做长轮询。
- 监控页是透明主通道，聊天页只给里程碑与结论。
- 实盘能力保留，默认不进入实盘；用户请求模拟/实盘时执行 `qmt-check` 检测。
- 触发词分四类：
  - **回测第1轮**：`回测`、`策略`、`自动编排`、`均线`、`上穿`、`下穿`、`买入`、`卖出` → 进入三轮交互协议
  - **回测第2轮**：`开始生成`、`生成策略`、`好`、`开始`、`继续`、`1`（或任何第1轮确认后的用户消息）
  - **参数优化**：`优化`、`调参`、`参数优化`、`网格搜索` → 执行 `optimize`（回测完成后触发）
  - **模拟/实盘**：`模拟`、`模拟盘`、`实盘`、`实盘交易`、`QMT` → 执行 `qmt-check`（独立流程，不走三轮协议）

---

## 第 0 步：定位项目根目录（每次会话首次触发时执行一次）

按优先级定位 `QUANTCLAW_ROOT`：

1. `echo "${QUANTCLAW_ROOT:-$QMT_PROJECT_ROOT}"`，非空且包含 `backtests/pipeline_orchestrator.py` → 使用
2. 若为空，自动发现：
```bash
for d in /opt /root /home; do find "$d" -maxdepth 5 -name "pipeline_orchestrator.py" -path "*/backtests/*" 2>/dev/null; done | head -1
```
取结果的 `parents[1]` 作为项目根目录，后续命令用该绝对路径。
3. 都找不到 → 返回 `status=config_missing` + 配置指南链接 + `config-doctor` 命令。**禁止降级为手动脚本。**

编排器脚本内置路径回退（`Path(__file__).parents[1]`），即使环境变量未设置，只要找到脚本就能正常运行。

---

## 三轮交互协议

### 第 1 轮：需求确认

**目标**：理解用户意图，确认关键参数，引导进入代码生成轮。

1. **解析需求**：提取标的、周期、信号（仓位/风控缺失时使用默认并说明）
2. **做数据能力检查**：
```bash
"${PYTHON_BIN}" "${QUANTCLAW_ROOT}/backtests/data_capability_guard.py" \
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
   - 根据 `parsed["mode"]` 选择正确模板：
     - `cta` → 继承 `CtaTemplate`，`on_bar(self, bar)`，`self.buy(price, vol)` / `self.sell(price, vol)`，`self.pos`，初始化用 `self.load_bar(N)`（**单数**，N=bar 数量）
     - `portfolio` → 继承 `StrategyTemplate`（vnpy_portfoliostrategy），`on_bars(self, bars: dict)`，`self.buy(vt_symbol, price, vol)` / `self.sell(vt_symbol, price, vol)`，`self.get_pos(vt_symbol)`，初始化用 `self.load_bars(days)`（**复数**，days=天数）
   - **严禁混用**：CTA 策略禁止用 `load_bars`，Portfolio 策略禁止用 `load_bar`
   - **仓位计算（强制）**：默认资金100万，用户未指定手数时必须按资金全仓动态计算买卖数量，禁止 `fixed_size=1` 这种玩具逻辑
   - **交易所合规（强制）**：沪深主板/创业板 100 股整数倍，科创板(688xxx) 200 股起步+1 股递增（205 股合法）；策略内需含 `_calc_volume(symbol, price, capital)` 辅助函数
   - **ArrayManager API**：均线用 `am.sma()`，禁止用 `am.ma()`（vnpy 不存在此方法）
   - 写入 `${QUANTCLAW_ROOT}/strategies/{module_name}.py`

2. **编译校验**（最多 3 轮 compile-fix 循环）：
```bash
"${PYTHON_BIN}" -m py_compile "${QUANTCLAW_ROOT}/strategies/{module_name}.py"
```
   - 编译通过 → 进入步骤 3
   - 编译失败 → 读取错误信息，LLM 修复代码，重写文件，重新编译
   - 超过 3 轮仍失败 → 告知用户并附错误信息，结束本轮

3. **提交回测**：
```bash
"${PYTHON_BIN}" "${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py" submit \
  --requirement "{用户原始需求}" \
  --strategy-file "${QUANTCLAW_ROOT}/strategies/{module_name}.py" \
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
"${PYTHON_BIN}" "${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py" status --run-id "{run_id}"
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

4. **完成后引导**（status=completed 时必须附带）：

```
回测已完成，{摘要}。您可以：
1. 回复「优化参数」对策略参数进行网格搜索
2. 回复「模拟/实盘」检测 QMT 环境
```

---

## 参数优化流程（回测完成后由用户触发）

**触发词**：`优化`、`调参`、`参数优化`、`网格搜索`

**前提**：已完成至少一次回测（数据已缓存在数据库中）。

1. **确认优化方案**：agent 分析当前策略的可调参数，向用户确认：
   - 优化目标（默认 `sharpe_ratio`，可选 `total_return`/`annual_return`/`max_ddpercent`）
   - 参数范围（`[起始, 终止, 步长]`）
   - 预估组合数

2. **执行优化**：
```bash
"${PYTHON_BIN}" "${QUANTCLAW_ROOT}/backtests/pipeline_orchestrator.py" optimize \
  --strategy-file "${QUANTCLAW_ROOT}/strategies/{module_name}.py" \
  --strategy-class "{class_name}" \
  --symbols "{vt_symbol}" \
  --start "{YYYYMMDD}" --end "{YYYYMMDD}" \
  --optimize-params '{"target":"sharpe_ratio","params":{"fast_window":[5,30,5],"slow_window":[10,60,10]}}'
```

支持 `"algorithm":"ga"` 使用遗传算法（大参数空间时推荐）。

3. **展示结果**：输出 JSON 含 `best`（最优参数+指标）和 `results`（Top N），agent 以表格形式呈现。

4. **后续选择**：用户可选择用最优参数重新回测验证，或继续调整参数范围。

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
- **禁止**在编排器找不到时降级为手动脚本、akshare/yfinance 临时方案、或任何非编排器回测方式

### 输出禁止
- **禁止**寒暄/自我介绍/营销文案
- **禁止**承诺"完成后自动推送摘要"或"跨轮次自动再回复"
- **禁止**使用"模拟数据演示"口径替代真实回测
- **禁止**硬编码市场数据
- **禁止**繁琐状态输出 `[run_id][N/M][状态]`
- **禁止**发了"请确认"却自动继续
- **禁止**前台启动长驻进程

### 安全禁止
- **禁止**硬编码绝对路径（统一使用 `QUANTCLAW_ROOT`）
- **禁止**在 SKILL 或脚本中提交明文凭据
- **禁止**策略文件路径指向 `strategies/` 目录之外
