# -*- coding: utf-8 -*-
"""通用回测执行器 - 内置锁/心跳/数据/统计/曲线/实时监控（同进程线程）"""
import sys, os, time, json, argparse, importlib, threading
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

PROJECT_ROOT = Path(os.getenv("QUANTCLAW_ROOT", "") or os.getenv("QMT_PROJECT_ROOT", "") or str(Path(__file__).resolve().parents[1])).resolve()
VNPY_QMT_PATH = PROJECT_ROOT / "vnpy_qmt"
STRATEGIES_PATH = PROJECT_ROOT / "strategies"
sys.path.insert(0, str(VNPY_QMT_PATH))
sys.path.insert(0, str(STRATEGIES_PATH))
from datetime import datetime, timedelta
from vnpy.trader.constant import Exchange, Interval, Direction
from vnpy.trader.object import HistoryRequest
from vnpy.trader.database import get_database
from vnpy.trader.setting import SETTINGS
from vnpy_xt.qg_datafeed import QgDatafeed

BASE = str((PROJECT_ROOT / "backtests").resolve())
LOCK = os.path.join(BASE, ".run_lock")
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
MONITOR = ""  # http://127.0.0.1:port（启用时设置）

def p(msg): print(f"[{RUN_ID}]{msg}", flush=True)
def stage(n, total, state, msg):
    p(f"[{n}/{total}][{state}] {msg}")
    _report("/api/progress", run_id=RUN_ID, status=state, stage=msg, pct=_stage_pct(n, total, state))
    if state != "running": _report("/api/log", msg=f"[{n}/{total}][{state}] {msg}")
def _stage_pct(n, total, state):
    base = {1: 5, 2: 15, 3: 20, 4: 85, 5: 90}
    return min(base.get(n, 0) + (10 if state == "success" else 0), 99)
def _url(path): return Path(path).resolve().as_uri()
def _report(path, **kw):
    if not MONITOR: return
    try: urlopen(f"{MONITOR}{path}?{urlencode(kw, quote_via=quote)}", timeout=2)
    except Exception as e: p(f"[monitor-warn] report{path} failed: {e}")
def _report_post(path, data):
    if not MONITOR: return
    try: urlopen(Request(f"{MONITOR}{path}", json.dumps(data, ensure_ascii=False).encode(), {"Content-Type": "application/json"}), timeout=5)
    except Exception as e: p(f"[monitor-warn] post{path} failed: {e}")


def _normalize_vt_symbol(s: str) -> str:
    """Normalize common exchange suffix aliases to vn.py values."""
    val = (s or "").strip().upper()
    if "." not in val:
        return val
    symbol, ex = val.split(".", 1)
    ex_map = {
        "SH": "SSE",
        "SS": "SSE",
        "SZ": "SZSE",
    }
    return f"{symbol}.{ex_map.get(ex, ex)}"

def _start_monitor(port):
    """优先连接已有外部monitor（agent预启动），否则本地线程启动"""
    global MONITOR
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1)
    if s.connect_ex(("127.0.0.1", port)) == 0: # 已有外部monitor（agent预启动）
        s.close(); MONITOR = f"http://127.0.0.1:{port}"
        p(f"[monitor] 连接已有监控服务: {MONITOR}/runs/{RUN_ID}")
        _report("/api/log", msg=f"回测执行器已连接 run_id={RUN_ID}"); return
    s.close()
    import importlib.util # 无外部monitor，本地线程启动（兼容旧流程）
    spec = importlib.util.spec_from_file_location("_mon", os.path.join(BASE, "monitor_server.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod._kill_port(port); mod.STATE["run_id"] = RUN_ID
    srv = mod.ThreadedHTTPServer(("127.0.0.1", port), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    MONITOR = f"http://127.0.0.1:{port}"; time.sleep(0.3)
    p(f"[monitor] 监控页已启动(线程): {MONITOR}/runs/{RUN_ID}")
    _report("/api/log", msg=f"回测执行器已就绪 run_id={RUN_ID}")

def validate_token(token, total_stages):
    stage(1, total_stages, "running", "检查qgdata token")
    if not token or len(token.strip()) < 20:
        stage(1, total_stages, "failed", "qgdata token为空或格式异常"); p("  订阅地址: https://quantgo.ai/data"); sys.exit(1)
    try:
        import qgdata as qg; qg.set_token(token.strip()); pro = qg.pro_api(timeout=15.0)
        pro.daily(ts_code="000001.SZ", start_date="20250101", end_date="20250110")
        stage(1, total_stages, "success", "qgdata token检查通过")
    except Exception as e:
        stage(1, total_stages, "failed", f"qgdata token检查失败: {type(e).__name__}")
        p(f"  可能原因: token无效/额度用尽/网络异常\n  订阅: https://quantgo.ai/data\n  错误: {str(e)[:160]}"); sys.exit(1)

def _bar(done, total, w=24):
    if total <= 0: return "[" + "-" * w + "]"
    f = int(w * done / total); return "[" + "#" * f + "-" * (w - f) + "]"
def _emit_progress(total_stages, done, total, tag="回测"):
    if total <= 0: return
    pct = int(done * 100 / total)
    p(f"[3/{total_stages}][running] {tag}进度 {done}/{total} {pct}% {_bar(done,total)}")

def _attach_progress(engine, mode, total_stages, capital=100000, size=1):
    """挂钩回测引擎，实时上报进度；CTA模式额外估算净值"""
    state = {"done": 0, "last": -1, "trades_n": 0, "realized": 0.0, "pos": 0.0, "avg_cost": 0.0, "err": ""}
    MONITOR_STEP = 10  # 每10根K线上报一次
    if mode == "cta":
        total = len(getattr(engine, "history_data", []) or [])
        con_step = max(total // 20, 1) if total else 1
        old = engine.new_bar
        def wrap(data):
            try: old(data)
            except Exception as e:
                state["err"] = f"{type(e).__name__}: {e}"
                _report("/api/log", msg=f"策略运行异常: {state['err']}")
                raise
            state["done"] += 1; d = state["done"]
            if d == 1 or d == total or d - state["last"] >= con_step: # 控制台进度
                state["last"] = d; _emit_progress(total_stages, d, total, "CTA回放")
            if MONITOR and (d % MONITOR_STEP == 0 or d == 1 or d == total): # 上报monitor
                pct = 20 + int(60 * d / max(total, 1))
                _report("/api/progress", run_id=RUN_ID, status="running", stage=f"CTA回放 {d}/{total} ({pct}%)", pct=min(pct, 80))
                trades = list(engine.trades.values())
                for t in trades[state["trades_n"]:]: # 增量处理新成交
                    vol = float(t.volume)
                    if t.direction == Direction.LONG:
                        new_pos = state["pos"] + vol
                        state["avg_cost"] = (state["avg_cost"] * state["pos"] + float(t.price) * vol) / new_pos if new_pos > 0 else 0
                        state["pos"] = new_pos
                    else:
                        state["realized"] += (float(t.price) - state["avg_cost"]) * vol * size
                        state["pos"] = max(state["pos"] - vol, 0)
                        if state["pos"] == 0: state["avg_cost"] = 0
                state["trades_n"] = len(trades)
                unrealized = state["pos"] * (float(data.close_price) - state["avg_cost"]) * size if state["pos"] > 0 else 0
                nav = (capital + state["realized"] + unrealized) / capital
                dt_str = data.datetime.strftime("%Y-%m-%d") if hasattr(data.datetime, "strftime") else str(data.datetime)[:10]
                _report("/api/point", dt=dt_str, nav=f"{nav:.6f}")
                if int(state["pos"]) > 0:
                    sym = getattr(engine, "vt_symbol", "") or (vt_symbols[0] if vt_symbols else "")
                    _report_post("/api/position_snapshot", {"date": dt_str, "positions": [{"symbol": sym, "volume": int(state["pos"]), "price": f"{data.close_price:.2f}", "value": f"{state['pos'] * data.close_price:.0f}"}]})
        engine.new_bar = wrap
    else: # portfolio模式
        total = len(getattr(engine, "dts", []) or [])
        con_step = max(total // 20, 1) if total else 1
        old = engine.new_bars
        vt_syms = vt_symbols
        def wrap(dt):
            try: old(dt)
            except Exception as e:
                state["err"] = f"{type(e).__name__}: {e}"
                _report("/api/log", msg=f"策略运行异常: {state['err']}")
                raise
            state["done"] += 1; d = state["done"]
            if d == 1 or d == total or d - state["last"] >= con_step:
                state["last"] = d; _emit_progress(total_stages, d, total, "Portfolio回放")
            if MONITOR and (d % MONITOR_STEP == 0 or d == 1 or d == total):
                pct = 20 + int(60 * d / max(total, 1))
                _report("/api/progress", run_id=RUN_ID, status="running", stage=f"Portfolio回放 {d}/{total}", pct=min(pct, 80))
                strat = engine.strategy
                if strat and hasattr(strat, "get_pos"):
                    dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                    pos_list = [{"symbol": s, "volume": strat.get_pos(s)} for s in vt_syms if strat.get_pos(s) != 0]
                    if pos_list:
                        _report_post("/api/position_snapshot", {"date": dt_str, "positions": pos_list})
        engine.new_bars = wrap
    return state

# ========== 锁 ==========
def acquire_lock():
    if os.path.exists(LOCK):
        try:
            with open(LOCK) as f: info = json.load(f)
            if time.time() - info.get("ts", 0) < 600: p(f"[0][failed] 上一轮 {info['run_id']} 尚未结束"); sys.exit(1)
        except Exception: pass
    with open(LOCK, "w") as f: json.dump({"run_id": RUN_ID, "ts": time.time()}, f)
def release_lock():
    try: os.remove(LOCK)
    except Exception: pass

# ========== 数据加载 ==========
def load_data(symbols_exchanges, interval, start, end, token, total_stages):
    SETTINGS["datafeed.name"] = "qg"; SETTINGS["datafeed.password"] = token
    db = get_database(); datafeed = None; n = len(symbols_exchanges); ok = 0
    stage(2, total_stages, "running", f"加载{n}个标的数据")
    for i, (sym, ex) in enumerate(symbols_exchanges):
        vts = f"{sym}.{ex.value}"; p(f"  [{i+1}/{n}] 检查 {vts} start={start} end={end}")
        bars = db.load_bar_data(sym, ex, interval, start, end)
        if bars and len(bars) > 10:
            p(f"  [{i+1}/{n}] {vts}: 缓存{len(bars)}根K线"); ok += 1; continue
        if datafeed is None:
            datafeed = QgDatafeed()
            if not datafeed.init(): stage(2, total_stages, "failed", "qgdata初始化失败"); sys.exit(1)
        p(f"  [{i+1}/{n}] {vts}: 本地不足，下载中...")
        req = HistoryRequest(symbol=sym, exchange=ex, interval=interval, start=start, end=end)
        bars = datafeed.query_bar_history(req)
        if bars: db.save_bar_data(bars); p(f"  [{i+1}/{n}] {vts}: 下载{len(bars)}根K线"); ok += 1
        else: p(f"  [{i+1}/{n}] {vts}: 无数据(下载返回空)")
    if ok == 0: stage(2, total_stages, "failed", f"所有{n}个标的均无数据"); sys.exit(1)
    stage(2, total_stages, "success", f"数据加载完成 {ok}/{n}个标的")

def _patch_lot_compliance(engine, vt_symbols, mode):
    """引擎层兜底：下单手数自动向下取整至交易所合规（主板/创业板100整数倍，科创板200起+1股递增）"""
    sym_lots = {}
    for s in vt_symbols:
        digits = "".join(c for c in s if c.isdigit())[:6]
        sym_lots[s] = "star" if digits.startswith("688") else "main"
    def _comply(vol, sym):
        board = sym_lots.get(sym, "main")
        if board == "star": return int(vol) if vol >= 200 else 0  #科创：200起+1股递增，向下取整到整数
        return int(vol / 100) * 100  #主板/创业板：100整数倍
    if mode == "cta":
        _orig = engine.send_order
        def _wrap(strategy, direction, offset, price, volume, stop, lock, net):
            sym = getattr(strategy, "vt_symbol", vt_symbols[0] if vt_symbols else "")
            adj = _comply(volume, sym)
            if adj != int(volume) and adj > 0: p(f"[lot-fix] {sym} {volume}->{adj}股 (交易所合规取整)")
            if adj <= 0: p(f"[lot-fix] {sym} {volume}股不足最低手数，跳过下单"); return []
            return _orig(strategy, direction, offset, price, adj, stop, lock, net)
        engine.send_order = _wrap
    else:
        _orig = engine.send_order
        def _wrap(strategy, vt_symbol, direction, offset, price, volume, lock, net):
            adj = _comply(volume, vt_symbol)
            if adj != int(volume) and adj > 0: p(f"[lot-fix] {vt_symbol} {volume}->{adj}股 (交易所合规取整)")
            if adj <= 0: p(f"[lot-fix] {vt_symbol} {volume}股不足最低手数，跳过下单"); return []
            return _orig(strategy, vt_symbol, direction, offset, price, adj, lock, net)
        engine.send_order = _wrap

def _patch_t1_compliance(engine, interval):
    """A股T+1持仓模型（参考rqalpha/聚宽设计）：维护closable_pos，策略可查询可卖数量，卖出时自动调减"""
    if interval in (Interval.DAILY, Interval.WEEKLY):
        return
    t1 = {"today": None, "non_closable": 0, "stats": {"blocked": 0, "adjusted": 0, "unlocked": 0}}
    _orig_bar = engine.new_bar
    def _bar_wrap(data):
        dt_date = data.datetime.date() if hasattr(data.datetime, 'date') else None
        if dt_date and dt_date != t1["today"]:
            if t1["non_closable"] > 0:
                t1["stats"]["unlocked"] += 1
                p(f"[T+1] 新交易日{dt_date}，解锁{t1['non_closable']}股(non_closable→0)")
            t1["today"] = dt_date; t1["non_closable"] = 0
            if engine.strategy: engine.strategy.closable_pos = int(engine.strategy.pos)  #日初：全部可卖
        _orig_bar(data)
        if engine.strategy:  #每根bar更新closable_pos
            engine.strategy.closable_pos = max(int(engine.strategy.pos) - t1["non_closable"], 0)
    engine.new_bar = _bar_wrap
    _orig_send = engine.send_order
    def _send_wrap(strategy, direction, offset, price, volume, stop, lock, net):
        if direction == Direction.LONG:  #买入：成交后增加non_closable
            result = _orig_send(strategy, direction, offset, price, volume, stop, lock, net)
            if result:  #有返回说明下单成功（引擎接受了委托）
                t1["non_closable"] += int(volume)
                strategy.closable_pos = max(int(strategy.pos) - t1["non_closable"], 0)
            return result
        else:  #卖出：基于closable_pos调减，而非静默拒绝
            closable = max(int(strategy.pos) - t1["non_closable"], 0)
            req_vol = int(volume)
            if req_vol <= closable:
                return _orig_send(strategy, direction, offset, price, volume, stop, lock, net)
            elif closable > 0:  #部分可卖：只卖可卖部分，日志透明
                t1["stats"]["adjusted"] += 1
                p(f"[T+1] 卖出{req_vol}→调减为{closable}股(non_closable={t1['non_closable']})")
                return _orig_send(strategy, direction, offset, price, closable, stop, lock, net)
            else:  #全部锁定：完全无法卖出
                t1["stats"]["blocked"] += 1
                p(f"[T+1] 卖出{req_vol}股跳过：可卖0股(全部{int(strategy.pos)}股为当日买入)")
                return []
    engine.send_order = _send_wrap
    if engine.strategy:
        engine.strategy.closable_pos = 0  #初始化属性
    p(f"[T+1] A股T+1持仓模型已启用(closable_pos可查询可卖数量)")
    return t1

# ========== 回测 ==========
def run_backtest(mode, strategy_cls, vt_symbols, interval, start, end, capital, rate, slippage, size, pricetick, strategy_params, total_stages):
    t0 = time.time()
    if mode == "cta":
        from vnpy_ctastrategy.backtesting import BacktestingEngine
        stage(3, total_stages, "running", "CTA回测引擎初始化")
        engine = BacktestingEngine()
        engine.set_parameters(vt_symbol=vt_symbols[0], interval=interval, start=start, end=end,
            rate=rate, slippage=slippage, size=size, pricetick=pricetick, capital=capital)
        engine.add_strategy(strategy_cls, strategy_params)
    else:
        from vnpy_portfoliostrategy.backtesting import BacktestingEngine
        stage(3, total_stages, "running", "Portfolio回测引擎初始化")
        engine = BacktestingEngine()
        engine.set_parameters(vt_symbols=vt_symbols, interval=interval, start=start, end=end,
            rates={s: rate for s in vt_symbols}, slippages={s: slippage for s in vt_symbols},
            sizes={s: size for s in vt_symbols}, priceticks={s: pricetick for s in vt_symbols}, capital=capital)
        engine.add_strategy(strategy_cls, strategy_params)
    _patch_lot_compliance(engine, vt_symbols, mode)
    if mode == "cta":
        _patch_t1_compliance(engine, interval)
    if mode == "cta" and engine.strategy:
        if not hasattr(engine.strategy, 'load_bars'):
            engine.strategy.load_bars = lambda days=10, interval=None: engine.strategy.load_bar(days)  #兜底：CTA策略误用load_bars时降级为load_bar
            p("[fix] CTA策略缺少load_bars，已自动兜底为load_bar")
        if not hasattr(engine.strategy, 'capital') or getattr(engine.strategy, 'capital', 0) == 0:
            engine.strategy.capital = capital  #兜底：注入capital参数
            p(f"[fix] 策略缺少capital属性，已注入capital={capital}")
    engine.load_data()
    bar_count = len(engine.history_data) if mode == "cta" else len(getattr(engine, "dts", []) or [])
    p(f"  引擎参数: vt_symbols={vt_symbols} interval={interval} start={start} end={end}")
    p(f"  引擎加载K线数: {bar_count}")
    if bar_count == 0:
        stage(3, total_stages, "failed", f"引擎加载0根K线，请检查标的代码格式(应为xxx.SSE/SZSE)和日期范围")
        raise RuntimeError(f"engine loaded 0 bars for {vt_symbols}, start={start}, end={end}")
    if MONITOR:
        if mode == "cta": all_dates = [bar.datetime.strftime("%Y-%m-%d") for bar in (engine.history_data or [])]
        else: all_dates = [dt.strftime("%Y-%m-%d") for dt in (engine.dts or [])]
        _report_post("/api/init_axis", {"dates": all_dates})
        try:
            bench = _load_hs300(start, end)
            if bench is not None and len(bench) > 5:
                bnav = bench / float(bench.iloc[0])
                bench_dates = [d.strftime("%Y-%m-%d") for d in bnav.index]
                bench_vals = [round(float(v), 6) for v in bnav.values]
                _report_post("/api/bench_data", {"dates": bench_dates, "bench": bench_vals})
                p(f"  [monitor] 沪深300基准已推送({len(bench_dates)}点)")
        except Exception as e:
            p(f"  [monitor] 基准推送失败: {e}")
    state = _attach_progress(engine, mode, total_stages, capital, size)
    stage(3, total_stages, "running", f"{bar_count}根K线已加载，回放中...")
    engine.run_backtesting()
    if state.get("err"):
        stage(3, total_stages, "failed", f"策略运行异常: {state['err']}")
        raise RuntimeError(state["err"])
    stage(3, total_stages, "running", f"回放完成 耗时{int(time.time()-t0)}s，统计中")
    df = engine.calculate_result()
    stats = engine.calculate_statistics(output=True)
    trade_list = _extract_trades(engine)
    _push_trades(trade_list)
    stage(3, total_stages, "success", f"回测完成 收益={stats.get('total_return','N/A')} 夏普={stats.get('sharpe_ratio','N/A')}")
    return df, stats, trade_list

# ========== 指标输出 ==========
def print_stats(stats, total_stages):
    stage(4, total_stages, "running", "输出核心指标")
    KEYS = ["start_date","end_date","total_days","total_net_pnl","total_return",
        "annual_return","max_drawdown","max_ddpercent","sharpe_ratio","total_trade_count","winning_rate","profit_days","loss_days"]
    if stats:
        p("=" * 50)
        for k in KEYS:
            v = stats.get(k, "N/A")
            if isinstance(v, float): v = f"{v:.4f}" if abs(v) < 100 else f"{v:.2f}"
            p(f"  {k}: {v}")
        p("=" * 50)
        s = {}
        for k in KEYS:
            val = stats.get(k)
            if val is not None:
                try: s[k] = float(val)
                except (ValueError, TypeError): s[k] = str(val)
        if s: _report_post("/api/stats", s)
    stage(4, total_stages, "success", "指标输出完成")

# ========== 推送精确净值到monitor ==========

def _extract_trades(engine):
    trades = list(getattr(engine, "trades", {}).values())
    trade_list, pos_map, cost_map = [], {}, {} # 按标的分组跟踪仓位，兼容CTA/Portfolio
    for t in trades:
        dt_str = t.datetime.strftime("%Y-%m-%d") if hasattr(t.datetime, "strftime") else str(t.datetime)[:10]
        direction = "BUY" if t.direction == Direction.LONG else "SELL"
        price, volume, pnl = float(t.price), float(t.volume), ""
        sym = getattr(t, 'vt_symbol', '') or ''
        pos, avg_cost = pos_map.get(sym, 0.0), cost_map.get(sym, 0.0)
        if direction == "BUY":
            new_pos = pos + volume
            avg_cost = (avg_cost * pos + price * volume) / new_pos if new_pos > 0 else 0
            pos = new_pos
        else:
            if avg_cost > 0: pnl = f"{(price - avg_cost) * volume:.2f}"
            pos = max(pos - volume, 0)
            if pos == 0: avg_cost = 0
        pos_map[sym], cost_map[sym] = pos, avg_cost
        trade_list.append({"date": dt_str, "symbol": sym, "direction": direction, "price": f"{price:.2f}", "volume": f"{volume:.0f}", "amount": f"{price * volume:.2f}", "pnl": pnl})
    return trade_list

def _extract_positions(trade_list):
    """从交易记录推算最终持仓"""
    pos_map = {}
    for t in trade_list:
        sym = t.get("symbol", "")
        vol = float(t.get("volume", 0))
        price = float(t.get("price", 0))
        if t["direction"] == "BUY":
            cur = pos_map.get(sym, {"symbol": sym, "volume": 0, "cost": 0.0, "amount": 0.0})
            cur["amount"] += price * vol
            cur["volume"] += int(vol)
            cur["cost"] = cur["amount"] / cur["volume"] if cur["volume"] > 0 else 0
            pos_map[sym] = cur
        else:
            if sym in pos_map:
                pos_map[sym]["volume"] -= int(vol)
                if pos_map[sym]["volume"] <= 0: del pos_map[sym]
    return [{"symbol": v["symbol"], "volume": v["volume"], "cost": f"{v['cost']:.2f}", "market_value": f"{v['amount']:.2f}"} for v in pos_map.values() if v["volume"] > 0]

def _push_trades(trade_list):
    if not MONITOR or not trade_list: return
    try:
        _report_post("/api/trades", {"trades": trade_list})
        _report("/api/log", msg=f"Trades pushed ({len(trade_list)})")
        positions = _extract_positions(trade_list)
        if positions: _report_post("/api/positions", {"positions": positions})
    except Exception as e:
        p(f"[warn] Push trades failed: {e}")


def _push_final_nav(df, total_stages):
    if not MONITOR or df is None or df.empty: return
    _report("/api/log", msg="推送精确净值曲线...")
    nav = df["balance"].astype(float) / float(df["balance"].iloc[0])
    bench = _load_hs300(nav.index.min(), nav.index.max())
    data = {"dates": [d.strftime("%Y-%m-%d") for d in nav.index], "navs": [round(float(v), 6) for v in nav.values], "bench": []}
    if bench is not None and len(bench) > 10:
        bnav = bench.reindex(nav.index).ffill().dropna().astype(float)
        bnav_norm = bnav / float(bnav.iloc[0])
        data["bench"] = [round(float(v), 6) for v in bnav_norm.values]
    _report_post("/api/final", data)
    _report("/api/log", msg="精确净值曲线已推送（含沪深300基准）")

def _save_report_data(df, stats, trades, output_name):
    if df is None or df.empty: return
    nav = df["balance"].astype(float) / float(df["balance"].iloc[0])
    bench = _load_hs300(nav.index.min(), nav.index.max())
    data = {"dates": [d.strftime("%Y-%m-%d") for d in nav.index], "navs": [round(float(v), 6) for v in nav.values], "bench": [], "trades": trades or [],
        "stats": {k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in (stats or {}).items()}}
    if bench is not None and len(bench) > 10:
        bnav = bench.reindex(nav.index).ffill().dropna().astype(float)
        data["bench"] = [round(float(v), 6) for v in (bnav / float(bnav.iloc[0])).values]
    path = os.path.join(BASE, f"{output_name}_report_data.json")
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
    p(f"[report_data] {path}")

# ========== 净值曲线文件 ==========
def plot_result(df, title, out_name, total_stages):
    if df is None or df.empty: stage(5, total_stages, "failed", "无回测数据"); return
    stage(5, total_stages, "running", "生成净值曲线")
    html = os.path.join(BASE, f"{out_name}.html"); png = os.path.join(BASE, f"{out_name}.png"); replay = os.path.join(BASE, f"{out_name}_replay.html")
    nav = df["balance"].astype(float) / float(df["balance"].iloc[0])
    bench = _load_hs300(nav.index.min(), nav.index.max())
    wrote_chart = False
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=nav.index, y=nav.values, mode="lines", name="策略净值", line=dict(width=3, color="#2563eb")))
        if bench is not None and len(bench) > 10:
            bnav = (bench.reindex(nav.index).ffill().dropna()).astype(float)
            nav2 = nav.reindex(bnav.index); fig.data = ()
            fig.add_trace(go.Scatter(x=nav2.index, y=nav2.values, mode="lines", name="策略净值", line=dict(width=3, color="#2563eb")))
            fig.add_trace(go.Scatter(x=bnav.index, y=(bnav / float(bnav.iloc[0])).values, mode="lines", name="沪深300基准", line=dict(width=2, color="#ef4444", dash="dot")))
        else: p("  [提示] 未获取到沪深300数据，仅展示策略净值")
        fig.update_layout(title=f"{title}（含沪深300基准）", xaxis_title="日期", yaxis_title="净值(起点=1.0)",
            template="plotly_white", height=560, hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
        fig.write_html(html); _write_replay_html(nav, bench, title, replay)
        try: fig.write_image(png, width=1200, height=500, scale=2)
        except Exception: _matplotlib_fallback(nav, bench, title, png)
        wrote_chart = True
    except ImportError:
        wrote_chart = _matplotlib_fallback(nav, bench, title, png)
    if wrote_chart:
        stage(5, total_stages, "success", "曲线已生成")
        p(f"  [交互版曲线]({_url(html)})"); p(f"  [回放版曲线]({_url(replay)})"); p(f"  [静态PNG]({_url(png)})")
    else:
        stage(5, total_stages, "success", "缺少绘图库，已跳过曲线文件生成（不影响回测结果）")

def _load_hs300(start, end):
    try:
        import pandas as pd; db = get_database()
        bars = db.load_bar_data("000300", Exchange.SSE, Interval.DAILY, start, end)
        if not bars or len(bars) < 10:
            f = QgDatafeed()
            if not f.init(): return None
            bars = f.query_bar_history(HistoryRequest(symbol="000300", exchange=Exchange.SSE, interval=Interval.DAILY, start=start, end=end))
            if bars: db.save_bar_data(bars)
        if bars: return pd.Series([b.close_price for b in bars], index=[b.datetime for b in bars]).sort_index()
        import qgdata as qg; pro = qg.pro_api(timeout=15.0)
        ds, de = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        df = pro.daily(ts_code="000300.SH", start_date=ds, end_date=de)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date"); return pd.Series(df["close"].astype(float).tolist(), index=pd.to_datetime(df["trade_date"]).tolist())
        return _load_hs300_public(ds, de)
    except Exception:
        try: return _load_hs300_public(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        except Exception: return None

def _load_hs300_public(ds, de):
    import pandas as pd
    qs = urlencode({"secid": "1.000300", "klt": "101", "fqt": "1", "beg": ds, "end": de, "lmt": "5000", "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"})
    with urlopen(f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{qs}", timeout=12) as r: raw = r.read().decode("utf-8", errors="ignore")
    ks = (((json.loads(raw) or {}).get("data") or {}).get("klines") or [])
    if not ks: return None
    dts, closes = [], []
    for row in ks:
        pp = row.split(",")
        if len(pp) >= 3: dts.append(pd.to_datetime(pp[0])); closes.append(float(pp[2]))
    return pd.Series(closes, index=dts).sort_index() if closes else None

def _write_replay_html(nav, bench, title, out_html):
    try:
        import plotly.graph_objects as go
        xs, ys = list(nav.index), [float(v) for v in nav.tolist()]; by = None
        if bench is not None and len(bench) > 10:
            b = bench.reindex(nav.index).ffill().dropna().astype(float); n = nav.reindex(b.index).astype(float)
            xs, ys, by = list(n.index), [float(v) for v in n.tolist()], [float(v / b.iloc[0]) for v in b.tolist()]
        if len(xs) < 2: return
        step = max(len(xs) // 120, 1); ids = list(range(1, len(xs) + 1, step))
        if ids[-1] != len(xs): ids.append(len(xs))
        if by is None:
            frames = [go.Frame(data=[go.Scatter(x=xs[:i], y=ys[:i], mode="lines", name="策略净值", line=dict(width=3, color="#2563eb"))], name=str(i)) for i in ids]
            fig = go.Figure(data=[go.Scatter(x=[xs[0]], y=[ys[0]], mode="lines", name="策略净值", line=dict(width=3, color="#2563eb"))], frames=frames)
        else:
            frames = [go.Frame(data=[go.Scatter(x=xs[:i], y=ys[:i], mode="lines", name="策略净值", line=dict(width=3, color="#2563eb")),
                go.Scatter(x=xs[:i], y=by[:i], mode="lines", name="沪深300基准", line=dict(width=2, color="#ef4444", dash="dot"))], name=str(i)) for i in ids]
            fig = go.Figure(data=[go.Scatter(x=[xs[0]], y=[ys[0]], mode="lines", name="策略净值", line=dict(width=3, color="#2563eb")),
                go.Scatter(x=[xs[0]], y=[by[0]], mode="lines", name="沪深300基准", line=dict(width=2, color="#ef4444", dash="dot"))], frames=frames)
        fig.update_layout(title=f"{title}（回放，含沪深300）", xaxis_title="日期", yaxis_title="净值(起点=1.0)", template="plotly_white", height=560,
            updatemenus=[{"type":"buttons","showactive":False,"x":0.02,"y":1.1,"buttons":[
                {"label":"播放","method":"animate","args":[None,{"frame":{"duration":80,"redraw":True},"fromcurrent":True}]},
                {"label":"暂停","method":"animate","args":[[None],{"frame":{"duration":0,"redraw":False},"mode":"immediate"}]}]}],
            sliders=[{"x":0.08,"len":0.9,"steps":[{"method":"animate","label":str(i),"args":[[str(i)],{"frame":{"duration":0,"redraw":True},"mode":"immediate"}]} for i in ids]}])
        fig.write_html(out_html)
    except Exception: pass

def _matplotlib_fallback(nav, bench, title, png):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        p("  [warn] matplotlib未安装，跳过静态PNG绘制")
        return False
    plt.style.use("seaborn-v0_8-whitegrid"); plt.figure(figsize=(13, 5.5))
    plt.plot(nav.index, nav.values, label="策略净值", linewidth=2.5, color="#2563eb")
    if bench is not None and len(bench) > 10:
        b = bench.reindex(nav.index).ffill().dropna().astype(float); n = nav.reindex(b.index).astype(float)
        plt.plot(n.index, (b / float(b.iloc[0])).values, label="沪深300基准", linewidth=2.0, color="#ef4444", linestyle="--")
    plt.title(f"{title}（含沪深300基准）"); plt.legend(); plt.tight_layout(); plt.savefig(png, dpi=170); plt.close()
    return True

# ========== 主入口 ==========
def main():
    ap = argparse.ArgumentParser(description="通用回测执行器")
    ap.add_argument("--strategy", required=True, help="策略模块名")
    ap.add_argument("--class", dest="cls", required=True, help="策略类名")
    ap.add_argument("--symbols", required=True, help="标的列表逗号分隔")
    ap.add_argument("--mode", choices=["cta", "portfolio"], default="cta")
    _d_end = datetime.now().strftime("%Y%m%d"); _d_start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    ap.add_argument("--start", default=_d_start); ap.add_argument("--end", default=_d_end)
    ap.add_argument("--interval", default="DAILY", choices=["DAILY", "MINUTE", "HOUR", "WEEKLY", "5MIN", "15MIN", "30MIN"])
    ap.add_argument("--capital", type=float, default=1000000); ap.add_argument("--rate", type=float, default=0.0003)
    ap.add_argument("--slippage", type=float, default=0.01); ap.add_argument("--size", type=float, default=1)
    ap.add_argument("--pricetick", type=float, default=0.01)
    ap.add_argument("--token", default=os.getenv("QGDATA_TOKEN", ""))
    ap.add_argument("--params", default="{}", help="策略参数JSON")
    ap.add_argument("--output", default="backtest_result"); ap.add_argument("--title", default="")
    ap.add_argument("--monitor-port", type=int, default=0, help="监控服务端口，0=不启动")
    ap.add_argument("--run-id", default="", help="覆盖run_id")
    ap.add_argument("--monitor-keepalive-sec", type=int, default=300, help="回测完成后监控保活秒数")
    args = ap.parse_args()

    global RUN_ID
    if args.run_id: RUN_ID = args.run_id
    TOTAL = 5
    if args.monitor_port > 0: _start_monitor(args.monitor_port)

    vt_symbols = [_normalize_vt_symbol(s) for s in args.symbols.split(",") if s.strip()]
    _min_map = {"5MIN": ("MINUTE", "5min"), "15MIN": ("MINUTE", "15min"), "30MIN": ("MINUTE", "30min")}
    if args.interval in _min_map:
        _base, _freq = _min_map[args.interval]
        interval = getattr(Interval, _base)
        import vnpy_xt.qg_datafeed as _qdf; _qdf._MINUTE_FREQ_OVERRIDE = _freq  #覆盖datafeed的分钟频率
        p(f"[interval] {args.interval} → Interval.{_base} + qgdata freq={_freq}")
    else:
        interval = getattr(Interval, args.interval)
    _dfmt = "%Y-%m-%d" if "-" in args.start else "%Y%m%d"
    start = datetime.strptime(args.start, _dfmt); end = datetime.strptime(args.end, _dfmt)
    strategy_params = json.loads(args.params)
    title = args.title or f"{','.join(vt_symbols[:3])} 回测净值曲线"
    symbols_exchanges = [(s.split(".")[0], Exchange(s.split(".")[1])) for s in vt_symbols]
    mod = importlib.import_module(args.strategy)
    if hasattr(mod, args.cls): strategy_cls = getattr(mod, args.cls)
    else: # 大小写模糊匹配（agent常把Ma写成MA）
        low = args.cls.lower(); hit = [n for n in dir(mod) if n.lower() == low]
        if hit: p(f"  [warn] 类名修正: {args.cls} -> {hit[0]}"); strategy_cls = getattr(mod, hit[0])
        else: raise AttributeError(f"模块 {args.strategy} 中找不到类 {args.cls}，可用: {[n for n in dir(mod) if n[0].isupper() and 'Strategy' in n]}")

    acquire_lock()
    try:
        validate_token(args.token, TOTAL)
        load_data(symbols_exchanges, interval, start, end, args.token, TOTAL)
        df, stats, trade_list = run_backtest(args.mode, strategy_cls, vt_symbols, interval, start, end,
            args.capital, args.rate, args.slippage, args.size, args.pricetick, strategy_params, TOTAL)
        print_stats(stats, TOTAL)
        _push_final_nav(df, TOTAL)
        _save_report_data(df, stats, trade_list, args.output)
        plot_result(df, title, args.output, TOTAL)
    except Exception as e:
        import traceback; p(f"[failed] {type(e).__name__}: {e}"); p(traceback.format_exc()[-800:])
        _report("/api/progress", run_id=RUN_ID, status="failed", stage=f"失败: {type(e).__name__}", pct=0)
        sys.exit(1)
    finally:
        release_lock()
    summary = {"run_id": RUN_ID, "status": "done", "output": args.output, "stats": {k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in (stats or {}).items()}}
    spath = os.path.join(BASE, f"{args.output}_summary.json")
    with open(spath, "w", encoding="utf-8") as f: json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    p(f"[summary] {spath}")
    _report("/api/done")
    p("[完成] 回测结束")
    if MONITOR and args.monitor_keepalive_sec > 0: # 保持监控页可查看
        p(f"[monitor] 监控页保持{args.monitor_keepalive_sec}秒: {MONITOR}/runs/{RUN_ID}")
        try: time.sleep(args.monitor_keepalive_sec)
        except KeyboardInterrupt: pass

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-1000:]
        print(f"[CRASH] {type(e).__name__}: {e}", flush=True)
        print(tb, flush=True)
        # 尝试向监控服务发送失败状态
        try:
            if MONITOR:
                from urllib.parse import quote
                msg = f"{type(e).__name__}: {str(e)[:80]}"
                urlopen(f"{MONITOR}/api/step?step=3&status=failed&title=回测执行&msg={quote(msg)}", timeout=3)
        except: pass
        sys.exit(1)


