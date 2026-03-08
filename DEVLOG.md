# QuantClaw 开发日志 — 踩坑记录与架构演进

> 本文档记录了 QuantClaw 从零搭建到开源发布的完整开发历程，包括每一个重要决策的背景、踩过的坑及闭环修复方案。  
> 目的：让后续开发者和开源社区少走弯路。  
> 持续更新中，最新更新：2026-03-08。

---

## 目录

- [Day 1 — 2026-02-27：OpenClaw 部署与远程访问](#day-1--2026-02-27openclaw-部署与远程访问)
- [Day 2 — 2026-03-01：多设备访问与搜索技能](#day-2--2026-03-01多设备访问与搜索技能)
- [Day 3 — 2026-03-02：ClawHub 技能生态与 A 股数据技能](#day-3--2026-03-02clawhub-技能生态与-a-股数据技能)
- [Day 4 — 2026-03-03：QMT 策略自动化架构设计](#day-4--2026-03-03qmt-策略自动化架构设计)
- [Day 5 — 2026-03-04：vnpy_qmt 数据源对接](#day-5--2026-03-04vnpyqmt-数据源对接)
- [Day 6 — 2026-03-05：回测编排引擎与三轮交互协议](#day-6--2026-03-05回测编排引擎与三轮交互协议)
- [Day 7 — 2026-03-06：监控页体验优化与配置闭环](#day-7--2026-03-06监控页体验优化与配置闭环)
- [Day 8~9 — 2026-03-07~08：端到端测试与引擎深度加固](#day-89--2026-03-0708端到端测试与引擎深度加固)

---

## Day 1 — 2026-02-27：OpenClaw 部署与远程访问

### 背景
在阿里云 Linux 服务器上首次部署 OpenClaw，目标是实现本地和远程均可访问的 AI 对话平台。

### 踩坑记录

| 坑 | 现象 | 根因 | 解决方案 |
|----|------|------|----------|
| API Key 配置 | `No API key for provider "anthropic"` | 未在 `auth-profiles.json` 配置正确 provider | 配置阿里云百炼（bailian）provider，使用 qwen3.5-plus 模型 |
| Dashboard 访问 | 服务器上直接打开 `127.0.0.1:18789` 无效 | Dashboard 绑定在 localhost，需通过 SSH 隧道访问 | `ssh -N -L 18789:127.0.0.1:18789 root@<公网IP>` |
| 端口占用 | `bind [127.0.0.1]:18789: Permission denied` | 本地 18789 端口已被占用 | 改用其他本地端口映射，如 `-L 18080:127.0.0.1:18789` |

### 经验总结
- OpenClaw Dashboard 默认只监听 localhost，远程访问必须用 SSH 隧道或 Nginx 反代。
- 首次部署时优先确认 provider 和 API Key 配置，避免鉴权锁定。

---

## Day 2 — 2026-03-01：多设备访问与搜索技能

### 背景
希望公司电脑、手机等多设备都能访问 OpenClaw。同时测试搜索能力。

### 关键决策

| 决策 | 方案 |
|------|------|
| 多设备访问 | Cloudflare 代理 + Nginx 反代 + HTTPS，子域名 `openclaw.quantgo.ai` |
| 设备认证 | 配置 `dangerouslyDisableDeviceAuth: true` + `trustedProxies: ["loopback", "cloudflare"]` |
| 搜索策略 | 创建 smart-search 技能：优先 Tavily（有 API Key），额度用完自动降级 DuckDuckGo |

### 踩坑记录

| 坑 | 现象 | 解决 |
|----|------|------|
| `origin not allowed` | 外网访问被拒 | `allowedOrigins: ["*"]` |
| `device identity required` | 新设备/无痕模式报错 | 关闭设备认证 + 配置信任代理 |
| `ERR_TOO_MANY_REDIRECT` | Nginx 重定向规则冲突 | 移除有问题的重定向，直接使用带 token 的 URL |
| 搜索技能不生效 | OpenClaw 只识别 `web_search` 等固定名称 | 将 smart-search 重命名为 `web-search` |

---

## Day 3 — 2026-03-02：ClawHub 技能生态与 A 股数据技能

### 背景
开发并发布 A 股数据查询技能（`astock-data`、`a-stock-info`）到 ClawHub，供所有 OpenClaw 用户使用。

### 关键决策

| 决策 | 说明 |
|------|------|
| 技能命名 | ClawHub slug 全局唯一，先到先得 |
| 免费体验 | 内置共享 QGDATA_TOKEN（每日 1000 次），额度不足时引导注册 `data.quantgo.ai` |
| 文件名规范 | **OpenClaw 只识别大写 `SKILL.md`**，小写 `skill.md` 会被完全忽略 |

### 踩坑记录

| 坑 | 现象 | 根因 | 解决 |
|----|------|------|------|
| 技能安装后不可见 | `openclaw skills list` 看不到新装技能 | `skill.md`（小写）不被 OpenClaw 识别 | 改为大写 `SKILL.md` |
| ClawHub 发布后安全扫描 | 技能暂时隐藏 | ClawHub 新版本自动安全扫描 | 等扫描通过或本地安装 |
| 多名技能冲突 | `a-stock-info` 和 `astock-data` 的 metadata 名称不一致 | 统一 metadata 中 `name` 与 `slug` |

### 经验总结
- **`SKILL.md` 必须大写**，这是 OpenClaw 的硬性约定，不遵守就完全不生效。
- ClawHub 发布后有安全扫描流程，新技能可能暂时不可见。

---

## Day 4 — 2026-03-03：QMT 策略自动化架构设计

### 背景
设计从"用户一句话自然语言需求"到"生成可执行 QMT 策略"的完整闭环方案。

### 关键架构决策

| 决策 | 方案 | 原因 |
|------|------|------|
| 规划师架构 | 引入 `qmt-strategy-planner` 作为唯一入口 | 复杂策略需要编排多个子技能协作 |
| 连接管理器 | `qmt-connection-manager` 单例 | QMT 初始化动作复杂（检测→路径→session→账号→回调→连接→订阅），必须统一管理 |
| 需求澄清 | 1~5 个封闭式问题，不问"是否实盘" | 用户问策略肯定想实盘；默认实盘意图，只问影响交易结果的关键信息 |
| 数据源双源 | xtdata 为主，astock-data（qgdata）为补 | xtdata 分钟数据可能缺失，qgdata 作为降级方案 |
| session_id | `int(time.time())` 动态生成 | 硬编码或从环境变量读取会导致会话冲突 |

### 踩坑记录

| 坑 | 现象 | 教训 |
|----|------|------|
| 澄清问题与需求不符 | 用户问"轮动策略"，系统问"上穿还是下穿" | 不能用策略类型路由（穷举），应做信息缺口驱动提问 |
| `datetime` 导入错误 | `from datetime import datetime` 但用了 `datetime.timedelta` | Python 命名空间易混淆，建议 `from datetime import datetime, timedelta` |

### 经验总结
- **需求澄清不能穷举策略类型**，而应像 DeepResearch 一样，基于"信息缺口"提高信息增益的问题。
- QMT 初始化流程复杂，必须用单例模式管理，否则多 skill 各自建连会冲突。

---

## Day 5 — 2026-03-04：vnpy_qmt 数据源对接

### 背景
将 qgdata 接入 VeighNa（vnpy）回测引擎作为首选数据源，替代需要 Windows 的 xtdata。

### 关键决策

| 决策 | 说明 |
|------|------|
| 继承 BaseDatafeed | 实现 `query_bar_history()`，支持 MINUTE/HOUR/DAILY/WEEKLY |
| 字段映射 | qgdata `open/high/low/close/vol/amount` → vnpy `open_price/high_price/low_price/close_price/volume/turnover` |
| 交易所映射 | 仅保留 SSE→SH、SZSE→SZ、BSE→BJ；期货映射移除（实测不可用） |
| 平台兼容 | xtquant 改为 `try/except` 可选导入，Linux 下不阻塞 |

### 踩坑记录

| 坑 | 根因 | 修复 |
|----|------|------|
| `float()` 遇空值崩溃 | qgdata 返回字段可能为字符串/None | 新增 `_safe_float()` 统一安全转换 |
| 未映射交易所 KeyError | `.get()` 缺失 | 使用 `.get()` 返回 None 并日志提示 |
| 期货交易所映射不可用 | 文档声称支持但实际不行 | 移除期货映射，README 标明仅支持 A 股 |

### 产出
- 新项目 `vnpy_qmt` 发布到 `gitee.com/GuojinQuant/vnpy_qmt`
- 实测双均线策略回测通过

---

## Day 6 — 2026-03-05：回测编排引擎与三轮交互协议

### 背景
将"自然语言 → 策略生成 → 回测 → 结果展示"做成生产级自动化流水线。

### 关键架构决策

| 决策 | 方案 | 原因 |
|------|------|------|
| 单次触发 + 后台编排 | 用户发需求后只做一次 submit，后台 worker 串行执行 | OpenClaw 单轮只能产出一次最终回复，不能多轮自动轮询 |
| 三轮交互协议 | 第1轮需求确认 → 第2轮生成+submit → 第3轮查看结果 | 平台不支持跨轮次自动推送，必须引导用户主动触发下一步 |
| 数据能力闸门 | 新增 `data_capability_guard.py` | 避免启动编排后才发现数据不支持，浪费用户等待时间 |
| 监控页优先 | submit 立即返回 `monitor_url`，毫秒级首响 | 不能让用户等回测完才知道状态 |
| 限价单成交逻辑 | 用激进限价（如 close×1.10），让 vnpy 在下一根 bar 以 open 成交 | 原方案用 ±2% 滑点在跳空高开时无法成交 |

### 踩坑记录

| 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|
| agent 走错链路 | 不走编排器，用 akshare 临时脚本回测 | workspace 残留了演示脚本 + 误导性模板文件 | 删除所有残留文件，SKILL 增加 18 条"绝对禁止"规则 |
| 策略净值恒为 1 | 0 笔交易 | ArrayManager(size=80) 在 90 天日线（~50 根 K 线）下永远 `inited=False` | 改为 `size=slow_window+5`，默认回测改为 365 天 |
| 监控页返回内网地址 | `MONITOR_PUBLIC_BASE` 设为内网 IP | 缺乏校验 | 拒绝 10.x/127.x/localhost/0.0.0.0 |
| 标的解析错误 | 001309 → 000001.SZSE | 代码正则不精确 | 增加 6 位代码识别 + 中文名解析 |
| 同轮摘要不可行 | 试图回测完同轮返回结果 → 首响被阻塞 | 平台限制单轮只能产出一次回复 | 放弃同轮摘要，改为引导用户发「查看结果」 |

### 产出
- `pipeline_orchestrator.py`：submit/status/worker 三命令编排器
- `data_capability_guard.py`：基于 SDK_USER_API 做需求-数据能力匹配
- 三轮交互协议确定并固化到 SKILL.md 和 MEMORY.md

### 经验总结
- **OpenClaw 不支持 agent 主动发起新轮次**。所有需要用户等待的操作，必须在首响中给出监控页链接 + 引导词。
- workspace 中残留的旧文件会严重误导 agent，必须保持干净。

---

## Day 7 — 2026-03-06：监控页体验优化与配置闭环

### 背景
对监控页进行系统性 UX 优化，解决报告持久化、错误展示、端口管理等问题。

### 关键决策

| 决策 | 方案 |
|------|------|
| 双链接 | `monitor_url`（短时监控，过程中看）+ `report_url`（长期静态报告，完成后看）|
| Shift-Left 策略生成 | 代码生成前移到 OpenClaw 对话轮内（LLM 生成），worker 只负责回测执行 |
| 一词触发 | 用户回复「开始生成」触发第 2 轮，不支持自动进入 |
| 端口白名单 | 仅使用预设端口（默认 8767），公网不可达则 fail-fast |
| 两段式收尸 | 完成后保留 monitor 短窗口（90s）供查看，再自动退出 |

### 踩坑记录

| 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|
| 百分比指标×100 | 收益率显示 4000% | 前端对 vnpy 已为百分比的数值再乘 100 | 去掉多余的 `*100` |
| 交易方向颜色 | 颜色全错 | 后端发 `BUY/SELL`，前端判断 `买入/卖出` | 兼容英文和中文 |
| monitor 永不退出 | 失败任务后端口一直被占 | `auto_stop` 仅依赖 `done=True`，失败时永不退出 | 增加 `MONITOR_MAX_IDLE_SEC` 超时兜底 |
| 17:59 卡住不回复 | submit 失败后 agent 自动重试/诊断 | SKILL 未禁止 submit 失败后自动重试 | 要求一次失败立即回包 |
| `/api/done` 协议不一致 | pipeline 用 POST，monitor 只实现 GET | 统一支持 GET/POST |

### 产出
- 自包含 Report HTML（echarts、Tab 分区、指标置顶、交易分页、语法高亮）
- 结构化错误系统（5 种 error_type 分流）
- `.env.example` 配置模板

---

## Day 8~9 — 2026-03-07~08：端到端测试与引擎深度加固

### 背景
使用 Playwright 模拟用户进行端到端测试，覆盖多种策略场景，发现并修复了大量深层问题。

### 关键架构演进

#### 1. CTA / Portfolio 双模式自动路由

**问题**：系统只实现了 CTA（单标的），用户提出"全市场选股轮动"等需求时无法处理。

**方案**：
- `parse_requirement()` 按标的数量 + 关键词（轮动/选股/组合/全市场/排列）自动选择 CTA 或 Portfolio
- CTA → `CtaTemplate`，`on_bar(self, bar)`，`self.load_bar(N)`
- Portfolio → `StrategyTemplate`（vnpy_portfoliostrategy），`on_bars(self, bars)`，`self.load_bars(days)`
- **严禁混用**：引擎层有兜底自动降级

#### 2. 五层防御体系

```
第1层：parse_requirement — 意图/周期/模式解析
第2层：_lint_strategy — 提交前静态代码检查（am.update_bar / load_bar混用 / am.ma / fixed_size）
第3层：_guard_strategy_runtime — 运行时兜底（自动注入 am.update_bar / load_bars降级 / capital注入）
第4层：_patch_lot_compliance — 手数合规（主板100整数倍 / 科创板200起+1股递增）
第5层：_patch_account_model — A股账户模型（可用现金 / T+1 / 持仓市值 / 可卖数量）
```

#### 3. A 股账户模型（对齐 rqalpha / 聚宽 / backtrader）

**问题**：策略使用固定 capital 而非实际可用现金，买入不扣资金，卖出不回款。

**方案**：在 `backtest_runner.py` 实现 `_patch_account_model`：
- `strategy.available_cash` — 可用现金（买入扣减，卖出回款）
- `strategy.total_value` — 账户总值（现金 + 持仓市值）
- `strategy.positions_value` — 持仓市值
- `strategy.closable_pos` — T+1 可卖数量
- `strategy.capital` — 等于 available_cash（向后兼容）

#### 4. T+1 机制

**问题**：分钟级策略上一根 bar 买入、下一根 bar 卖出，实际 A 股当天买入不能卖出。

**方案**：
- 引擎层实现，不改策略代码
- 每日重置 `non_closable`（今日锁定股数）
- 卖出时检查 `closable_pos = pos - non_closable`
- 不足则调减到可卖量，全部锁定则跳过

#### 5. 多周期支持

**问题**：vnpy 内部 Interval 枚举只有 MINUTE/HOUR/DAILY/WEEKLY，缺少 5 分钟等。

**方案**：
- 不改 vnpy 源码，在 `qg_datafeed.py` 增加 `_MINUTE_FREQ_OVERRIDE`
- `backtest_runner.py` 接受 `5MIN/15MIN/30MIN`，映射到 `Interval.MINUTE` + 覆盖 qgdata 频率
- `parse_requirement()` 将"5 分钟" → `5MIN`、"60 分钟" → `HOUR`

### 踩坑记录（按严重程度排序）

| 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|
| **agent 用旧版代码** | 修过的 bug 反复出现 | 服务器存在 3 份代码（release/push/QuantClaw），agent 随机引用 | 删除旧目录，只保留 push，QUANTCLAW_ROOT 持久化 |
| **`am.ma()` 不存在** | `AttributeError` | vnpy 均线方法叫 `sma` | 全部改为 `am.sma()`，lint 检查兜底 |
| **`am.update_bar(bar)` 缺失** | 全程 0 交易 | agent 生成代码遗漏 + 外部策略绕过 lint | 静态检查 + 运行时自动注入（CTA 和 Portfolio 均覆盖）|
| **买卖 1 股** | 交易量不真实 | 默认资金 10 万 + `fixed_size=1` | 默认 100 万，`_calc_volume` 全仓动态计算 |
| **仅 CTA 模式** | 多标的需求无法处理 | 缺 Portfolio 依赖和模板 | 安装 vnpy_portfoliostrategy，双模板 + 自动路由 |
| **`load_bar` vs `load_bars`** | `AttributeError` | CTA 用单数，Portfolio 用复数，agent 混用 | SKILL 明确区分 + 引擎层自动降级 |
| **fast_window/slow_window 乱显** | 非均线策略显示均线参数 | `parse_requirement` 无条件输出 MA 参数 | 仅均线类输出，正则排除 MACD |
| **MACD 被识别为 MA** | 策略类型错误 | 关键词 `MA` 匹配到 `MACD` | 正则改为 `\bMA\b(?!CD)` |
| **monitor 首次打开白屏** | "this page isn't working" | keepalive 只有 90 秒 | 改为 600 秒 |
| **5 分钟线 0 交易** | 数据获取但无信号 | qgdata 默认映射 1min 而非 5min | `_MINUTE_FREQ_OVERRIDE` 动态覆盖 |
| **交易记录无标的** | 为单标的设计 | 前端模板缺 symbol 列 | `_extract_trades` 增加 symbol |
| **只有最终持仓** | 无法看到每日变化 | 只在结束时推一次 | 每 10 根 K 线推 `/api/position_snapshot` |
| **基准曲线不同步** | 策略曲线有但基准没有 | 基准只在最终推送 | 回测前即推 `/api/bench_data` |
| **收益曲线无动态增长** | 一次性渲染 | 前端等待全量数据 | 改为 `point` 事件逐步 push + echarts 动画 |
| **workspace SKILL 未同步** | 改了 push 但 agent 读 workspace | 两份独立文件 | workspace 建立软链接指向 push |
| **失败时无引导** | 用户不知道下一步 | 日志只有一行失败信息 | 错误卡片 + "请回到对话页输入「查看结果」" |
| **全市场选股只 1 只** | 股票池未展开 | 缺乏关键词解析 | 新增 `_resolve_stock_pool()`，识别全市场/沪深300 等 |
| **日期格式不兼容** | `ValueError` | runner 只接受 `YYYYMMDD` | 同时支持 `YYYY-MM-DD` |

### 经验总结

1. **五层防御是必须的**：LLM 生成的代码质量不稳定，从解析 → 检查 → 运行时 → 手数 → 账户，每层都必须有兜底。
2. **多份代码是定时炸弹**：服务器上绝对不能存在多份同名项目，agent 会随机引用旧版本。
3. **workspace 与 push 的同步**：SKILL.md 用软链接确保一致；MEMORY.md 仅在 workspace（环境相关，不入 git）。
4. **OpenClaw 不支持跨轮次主动推送**：回测完成后无法自动在聊天中通知用户，只能靠监控页 + 引导用户发「查看结果」。
5. **vnpy ArrayManager 的 `am.sma()` 不是 `am.ma()`**：这个坑会反复出现，必须在 lint 和 runtime 双重兜住。
6. **A 股特殊规则必须引擎层兜底**：T+1、手数合规、资金管理不能依赖策略代码层，因为 LLM 生成的代码经常遗漏。

### 2026-03-08 补充修复（本轮闭环）

| 修复点 | 问题现象 | 根因 | 修复方案 | 验证方式 |
|---|---|---|---|---|
| lint warnings/blockers 分类 | 有运行时兜底的检查被误标为 blocker 导致策略误拒 | 初版重构未区分"必崩"与"有兜底" | blocker 仅保留必崩项（`vnpy.trading.*`/`am.ma()`/`Signal`）；其余降为 warning | py_compile + 策略加载不再误拒 |
| compat 检查时序 | step3 success 在 compat 检查前发送，用户看到"就绪"后立刻"失败" | 调用顺序错误 | `_validate_engine_compat()` 移至 step3 success 之前；新增 `EngineCompatError` + 专属 except 块 | portfolio+WEEKLY 时 step3 不再先成功再失败 |
| Portfolio+WEEKLY 引擎驱动 vs 数据源混淆 | agent 输出"日线合成周线"但 qgdata 有 `pro.weekly()` | 错误信息未区分引擎驱动限制与数据能力 | 三层防御：① SKILL.md 明确引擎驱动约束+`pro.weekly()` 可用 ② `parse_requirement()` 自动降级+日志提示 ③ `_validate_engine_compat` 兜底 | `parse_requirement('全市场周级别轮动')` → interval=DAILY + 日志 |
| Portfolio 账户注入价格滞后 | `on_bars` 内连续下单时，`total_value/positions_value` 可能短时基于旧价格 | `new_bars` 包装器只在 `_orig_bars()` 之后同步 `last_prices` | 在 `_bars_wrap` 执行前后都同步 `engine.bars`；`send_order` 成功后也先同步再注入账户字段 | 分钟级 Portfolio 连续下单，观察监控页净值与持仓估值不再“跳变回补” |
| 现金扣减与成交手数不一致 | 账户层按 `vol` 扣钱，但下游手数合规可能把 `vol` 再向下取整 | 账户层和手数层未共享同一“最终手数” | 在账户层先按交易所规则做同口径取整（主板100整数倍、科创200起），现金校验/扣减全部基于取整后手数 | 构造 350 股下单场景，确认资金按 300 股口径变化（不再出现超扣） |
| 停牌/涨跌停废单透明性 | 策略可能误判“已下单” | 仅看 `last_order_status` 会被后续订单覆盖 | 强化文档与策略约定：优先检查 `buy/sell` 返回值，结合 `order_reject_log` 看完整拒单历史 | 单根K线多次下单回放，验证拒单可在日志与状态中追踪 |
| 策略股票池与引擎加载脱节 | 策略代码定义55只HS300但引擎只加载1只→0交易 | **根因：股票池所有权未定义**。vnpy 设计意图是引擎拥有股票池（`vt_symbols`），策略只使用，但 SKILL.md 未传导此契约 → LLM 在策略代码中硬编码股票池并覆盖引擎传入的列表 | ① SKILL.md 新增"股票池所有权契约"：`--symbols`=引擎=策略`self.vt_symbols`三者同源，策略禁止覆盖；标的格式统一 vnpy(.SSE/.SZSE) ② `_resolve_stock_pool`去空格容错 ③ 源码提取作为兜底警告（不是修复） | SKILL.md 契约已加；空格容错已验证 |
| qgdata Token 不足/过期静默失败 | 多处 `except: return []` 或 `except: pass` 吞掉异常，用户完全不知道数据API失败 | **根因：所有 qgdata 调用点的异常处理均为静默降级**，无任何用户引导 | **全链路统一 `QGDATA_RECHARGE_URL` 常量**（4个文件各自定义，值=`https://quantgo.ai/data`），覆盖 10 个调用点：① `pipeline_orchestrator.py`：`resolve_symbols_by_name`/`_resolve_stock_pool` 返回 `(list, warning)` 元组 + `parse_requirement` 传播 `pool_warning` + `cmd_submit` JSON输出&monitor页展示 + `config-doctor` token校验 ② `backtest_runner.py`：`validate_token`/`_load_trade_calendar`/`_patch_order_guards`(无token+初始化失败) ③ `qg_datafeed.py`：`init`(3个异常分支) + `query_bar_history` ④ `data_capability_guard.py`：`list_runtime_apis` 返回 `(set, warning)` + `evaluate_requirement` missing提示含充值URL ⑤ monitor前端：`addLog` 自动将URL转可点击超链接 + timeline `warning` 状态（⚠️黄色）⑥ `resolve_symbols_by_name` 停止词改子串正则过滤 | 编译通过 + 12项单元测试通过 |
| Token分级与试用配额改造 | 未配置Token无法使用；全市场策略因token问题静默降级为单标的 | **需要零门槛试用 + 付费转化闭环** | ① 新增 `qg_constants.py` 统一共享常量（`QGDATA_RECHARGE_URL`/`QGDATA_SHARED_TOKEN`/`classify_qgdata_error`/`mask_token`），所有模块统一import ② `resolve_qgdata_token` 改为4级优先级：`--token > 对话提取 > 环境变量 > 内置共享token`，返回 `(token, source)` ③ 新增 `extract_token_from_chat` 从对话自动提取60~70位token ④ `classify_qgdata_error` 统一分类：unauthorized/quota_exceeded/forbidden/api_error ⑤ 关键词匹配但API失败时阻断（`data_blocked=True`）而非静默fallback到默认标的 ⑥ submit返回`token_source`字段 ⑦ SKILL.md加对话token提取规则+共享试用说明 ⑧ README/.env.example更新试用说明 | 编译通过 + 单元测试覆盖token优先级/错误分类/阻断逻辑 |

---

## 附录：文件结构速查

```
quant-claw-push/
├── skills/quant-strategy-assistant/
│   ├── SKILL.md                    # 技能定义（软链接到 workspace）
│   └── qgdata-reference.md         # 数据 API 参考
├── QMT-TradingClaw/
│   ├── backtests/
│   │   ├── pipeline_orchestrator.py # 编排引擎（submit/status/worker）
│   │   ├── backtest_runner.py       # 回测执行器（账户模型/T+1/手数合规）
│   │   ├── monitor_server.py        # 实时监控页（SSE + 内嵌前端）
│   │   └── data_capability_guard.py # 数据能力闸门
│   ├── strategies/                  # 策略文件目录
│   └── vnpy_qmt/vnpy_xt/
│       └── qg_datafeed.py           # qgdata 数据源适配器
├── .cursor/rules/
│   ├── delivery-quality.mdc         # 交付质量标准（有用/方便/好用/美观）
│   └── monitor-page.mdc            # 监控页功能规范
├── README.md                        # 用户文档
├── DEVLOG.md                        # 本文件
└── .env.example                     # 配置模板
```

---

## #11 板块/指数成分股解析 + 日期关键词兜底（2026-03-08）

### 根因
1. `_resolve_stock_pool` 只支持固定关键词（全市场/沪深300/创业板/科创板），不支持板块/行业/概念名称
2. "沪深300"实现错误：返回主板+创业板全量股票（~4000只）而非真实300只成分股
3. `parse_requirement` 不解析日期关键词（"最近1年"），LLM 已证明会编造错误日期

### 架构决策
- **指数成分股双路径**：主路径 `ths_member`（883300.TI 等已验证存在） → 降级路径东方财富公开 API（`datacenter-web.eastmoney.com/RPT_INDEX_COMPONENT`）
- **板块映射三级查找**：静态 `THS_SECTOR_MAP`（60+ 条目全部经 API 验证） → 按日文件缓存 → `ths_index` API 模糊搜索
- **板块名提取**：静态 key 最长子串匹配优先 → 正则提取（2-8 字符约束 + 反向排除词）
- **日期解析双保险**：SKILL.md 约束 LLM 标准输出 + `_parse_date_range` 正则兜底 12 种模式（用 `relativedelta` 精确计算月/年）
- **日期优先级链**：`args.start`(CLI) > `parsed["start"]`(正则) > 空(默认 today-365)
- **新增 5 项 lint 检查**：策略调用板块 API(blocker) / Portfolio 覆盖 vt_symbols(blocker) / 硬编码 .SH/.SZ(warning) / 硬编码日期(warning) / self.capital(warning, 仅 portfolio)

### 已知限制
- **幸存者偏差**：板块成分股使用当前列表（`is_new='Y'`），历史回测存在偏差（如 2023 年的沪深300成分股与当前不同）。待 qgdata 提供历史成分股 API 后改进
- **板块代码时效性**：`THS_SECTOR_MAP` 静态表可能随同花顺调整而过时，API 模糊搜索兜底可覆盖

### 修改文件
- `pipeline_orchestrator.py`：重构 `_resolve_stock_pool`（三级查找）、新增 `_resolve_index_members`/`_resolve_sector_members`/`_extract_sector_name`/`_parse_date_range`、新增 5 项 lint 检查、`cmd_submit` 日期优先级链
- `SKILL.md`：新增板块成分股引擎解析约束 + 日期标准输出约束
- `DEVLOG.md`：本条目

---

### #12 — 北交所(BJ)标的导致回测崩溃
**日期**：2026-03-08  
**现象**：人工智能板块回测 `20260308_120513` 在 3 秒内崩溃 `ValueError: 'BJ' is not a valid Exchange`  
**5-Why 根因**：
1. `Exchange("BJ")` 失败 → vnpy 枚举值是 `BSE` 不是 `BJ`
2. 股票池含 `.BJ` 标的 → `ths_member` 返回全交易所成分股包括北交所
3. `normalize_symbol` 不处理 `.BJ` → 只映射了 `.SH/.SZ/.SS`，遗漏北交所
4. 之前用 `stock_basic+market` 不含北交所 → 新数据通道(ths_member)引入旧代码未覆盖的交易所
5. **核心根因：交易所后缀映射表不完整，缺少 BJ→BSE**

**修复**：
- `normalize_symbol`：新增 `.BJ→.BSE` 后缀映射 + 纯 6 位数字 `83/43/87/920` 开头→BSE
- `backtest_runner.py:872`：Exchange 解析加 try/except 防御，不支持的交易所跳过而非崩溃
- 单元测试新增 6 个北交所用例（T51-T56），共 64 个全部通过

---

### #13 — 监控页"等待启动"卡死10分钟不更新
**日期**：2026-03-08  
**现象**：run_id `20260308_123839`（1019只人工智能标的）监控页持续显示"等待启动"10分钟，后端实际在跑  
**5-Why 根因**：
1. 页面默认"等待启动"→ 需SSE `step/progress`事件才切换到"运行中"
2. SSE初始回放payload过大 → 1019只symbols序列化>60KB，浏览器EventSource解析阻塞/超时
3. SSE断开后无任何恢复机制 → 页面永久卡在最后已知状态
4. 健康检查只测HTTP可达 → 不验证SSE数据流是否实际可用
5. **核心根因：监控系统100%依赖SSE实时流传递"运行真相"，无持久化状态轮询兜底；大payload可卡死SSE连接**

**修复**：
- 新增 `/api/state` REST端点：返回轻量JSON状态快照（去掉symbols列表/points/trades等大字段）
- 前端加轮询兜底：页面加载1.5秒后首次轮询 + 每5秒定期fetch `/api/state`，SSE断也能自愈
- SSE初始回放精简：`requirement.symbols`只发数量（"共1019只标的"）不发全量列表
- 初始文案改为"连接中..." → 1.5秒后轮询自动切换到实际状态（running/等待启动/已完成）
- 页面顶部新增"X秒前更新"心跳指示器，用户可直观判断数据是否在流动
- broadcast()每次更新自动打_ts时间戳，轮询据此计算"最后更新时间"

---

### #14 — 监控页"连接中..."永久卡死（CDN阻塞级联故障）
**日期**：2026-03-08  
**现象**：多次回测（包括 `20260308_141253`）监控页永久显示"连接中..."，后端 SSE/API 完全正常  
**5-Why 根因**：
1. 页面显示"连接中..."不变 → EventSource 和 `_pollState` 从未执行
2. 为什么没执行？ → 同一 `<script>` 块中 `echarts.init()` 在第 197 行抛异常
3. 为什么 echarts 抛异常？ → `echarts` 全局变量为 `undefined`（CDN 脚本未加载完成）
4. 为什么 CDN 未加载？ → jsdelivr CDN 在中国大陆经常超时/阻塞
5. **核心根因：页面 `<head>` 中 echarts CDN 使用 jsdelivr（大陆不稳定），阻塞加载失败后 `echarts.init()` 无 try-catch → 级联中断同 script 块中所有后续代码（SSE、轮询、事件监听）**

**修复**：
- CDN 主源切 npmmirror（国内镜像），onerror 回退 jsdelivr
- `echarts.init()` / `dailyChart.init()` 包 try-catch，图表挂了不影响通信
- 所有 `chart.setOption()` / `chart.resize()` 加 null 保护
- `hljs.highlightAll()` 加 try-catch
- 确保 EventSource + 轮询 + 状态更新在图表失败时仍能正常工作

### #15 — LLM 第1轮误判 CTA/Portfolio + 默认日期编造2年
**日期**：2026-03-08  
**现象**：用户需求含"排序/筛选/买入前5名/每周重新选一次"等明显 portfolio 信号，LLM 第1轮确认却选了 CTA；默认回测区间写成"近2年"  
**根因**：
1. SKILL.md 路由关键词仅 `轮动/选股/组合/多标的/全市场/排列`，缺少 `排序/筛选/买入前/调仓/等权` 等常见 portfolio 信号词
2. LLM 将"多头排列"理解为技术分析术语而非 portfolio 触发词
3. 默认日期 SKILL 写了"最近1年"但不够醒目，第1轮确认模板未强制标注
**修复**（v2 分层方案，避免弱关键词误判）：
- 关键词分三层：强信号（`轮动/组合/等权/全市场/前N名`等，任一即 portfolio）、弱信号（`排序/筛选/选股/调仓/排列`，需配合多标的上下文）、多标的上下文（`板块/成分股/指数/行业/概念/股票池`）
- `parse_requirement()` 实现分层判断：`has_strong or (has_pool and has_weak) or len(symbols)>1`
- SKILL.md 同步更新分层规则描述
- SKILL.md 日期约束增加"第1轮确认必须写'引擎默认最近1年'"
- 7 个典型场景测试全部通过

### #16 — 第2轮耗时11分钟（22:31→22:42）优化
**日期**：2026-03-08  
**现象**：用户说"开始生成"后等了11分钟才收到agent回复  
**根因**：agent在Round 2重跑了data_capability_guard（第1轮已做）+ 单独跑py_compile（submit内已含）+ LLM生成复杂策略思考时间长，共5次工具调用，每次20-60s开销  
**修复**：
- SKILL.md 第2轮增加"速度约束"：禁止重跑data_capability_guard、禁止单独py_compile
- 第2轮最多2次工具调用（写文件+submit），编译失败由submit返回在第3轮修复
- 增加"Portfolio轮动策略速查"模式（周轮动/排序选股/等权全仓/周线数据），减少LLM生成思考时间
- 预计从5次工具调用降到2次，节省3-5分钟

---

### #17 — 监控页始终"连接中..."（SSE/轮询/图表全部失效）
**日期**：2026-03-08  
**现象**：监控页加载后永远停留在"连接中..."，SSE、轮询、图表均无反应，后端 `/api/state` 和 SSE 流完全正常  
**根因**：`monitor_server.py` L196 `addLog()` 函数中正则 `/(https?:\\/\\/[^\\s<]+)/g` 在 Python `r"""..."""` raw string 下，`\\` 原样输出到浏览器，JS 引擎解析 `\\` 为转义反斜杠后遇到 `/` 提前结束正则，剩余文本被当作非法 flags → `Invalid regular expression flags`。这是**解析级错误**，整个 `<script>` 块被拒绝，所有 JS 从未执行  
**修复**：`\\/` → `\/`，`\\s` → `\s`（raw string 中单反斜杠即可）  
**教训**：Python raw string 内嵌 JS 正则时，`\` 不会被 Python 转义但会被 JS 引擎解析，需按 JS 正则语法而非 Python 字符串转义

---

### #18 — backtest_runner 因 interval 大小写不匹配直接退出 (run 20260308_160303)
**日期**：2026-03-08  
**现象**：回测 runtime_error `exit code=2`，实际是 argparse 拒绝 `--interval daily`（小写），`backtest_runner.py` choices 只认大写 `DAILY`  
**根因链**：LLM agent 传 `--interval daily`（小写）→ `submit` argparse 无 choices 校验 → payload 原样保留小写 → `backtest_runner.py` argparse `choices` 严格大小写 → 拒绝  
**为什么静态检查没拦住**：`py_compile` 检查语法不管 CLI 参数；`_validate_engine_compat()` 内部 `.upper()` 归一化了所以没触发；缺少 payload 层的归一化  
**修复**：`pipeline_orchestrator.py` L1280 payload 构建时 `.upper()` 归一化 interval

---

## 附录：关键环境变量

| 变量 | 用途 | 示例 |
|------|------|------|
| `QUANTCLAW_ROOT` | 项目根路径（兼容旧名 `QMT_PROJECT_ROOT`）| `/opt/quant-claw-push/QMT-TradingClaw` |
| `QGDATA_TOKEN` | qgdata 数据 API token | `Kj9mN2x...` |
| `MONITOR_PUBLIC_BASE` | 监控页公网基址 | `http://8.211.147.124` |
| `ORCH_MONITOR_PORT_CANDIDATES` | 监控页端口白名单 | `8761,8767` |
| `REPORT_PUBLIC_BASE` | 静态报告公网基址 | 同 MONITOR_PUBLIC_BASE |
| `REPORT_PUBLIC_DIR` | 静态报告存储目录 | `/opt/quant-claw-push/.../public_reports` |
