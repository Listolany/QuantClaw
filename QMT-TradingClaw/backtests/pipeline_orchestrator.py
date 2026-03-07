#!/usr/bin/env python3
"""Production orchestration pipeline for strategy generation/backtesting."""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from data_capability_guard import evaluate_requirement

PROJECT_ROOT = Path(os.getenv("QUANTCLAW_ROOT", "") or os.getenv("QMT_PROJECT_ROOT", "") or str(Path(__file__).resolve().parents[1])).resolve()
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
RUNS_DIR = BACKTESTS_DIR / "orchestrator_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PYTHON_BIN = os.getenv("PYTHON_BIN", sys.executable or "python3")
MONITOR_SERVER = BACKTESTS_DIR / "monitor_server.py"
BACKTEST_RUNNER = BACKTESTS_DIR / "backtest_runner.py"
STATE_VERSION = 1
MONITOR_BIND_HOST = os.getenv("ORCH_MONITOR_BIND_HOST", "0.0.0.0")
DEFAULT_REPORT_PUBLIC_DIR = (BACKTESTS_DIR / "public_reports").resolve()


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def atomic_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_symbol(raw: str) -> str:
    val = raw.strip().upper()
    if re.fullmatch(r"\d{6}", val):
        # Mainland A-share shorthand: 6xxxxx -> SSE, others -> SZSE
        return f"{val}.SSE" if val.startswith("6") else f"{val}.SZSE"
    if val.endswith(".SS"):
        return val[:-3] + ".SSE"
    if val.endswith(".SZ"):
        return val.replace(".SZ", ".SZSE")
    if val.endswith(".SH"):
        return val.replace(".SH", ".SSE")
    return val


def read_env_value_from_files(key: str, candidates: list[Path]) -> str:
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def resolve_qgdata_token(explicit_token: str) -> str:
    if explicit_token:
        return explicit_token
    env_token = os.getenv("QGDATA_TOKEN", "")
    if env_token:
        return env_token
    return read_env_value_from_files(
        "QGDATA_TOKEN",
        [PROJECT_ROOT / ".env", Path.home() / ".openclaw" / ".env", Path("/opt/.env")],
    )


def resolve_monitor_public_base(explicit_base: str) -> str:
    """解析监控公网基址（优先显式参数，其次环境变量/配置文件/控制台URL推导）"""
    if explicit_base and explicit_base.strip():
        return explicit_base.strip().rstrip("/")
    env_base = os.getenv("MONITOR_PUBLIC_BASE", "").strip()
    if env_base:
        return env_base.rstrip("/")
    file_base = read_env_value_from_files(
        "MONITOR_PUBLIC_BASE",
        [PROJECT_ROOT / ".env", Path.home() / ".openclaw" / ".env", Path("/opt/.env")],
    ).strip()
    if file_base:
        return file_base.rstrip("/")
    control_url = (
        os.getenv("OPENCLAW_CONTROL_URL", "").strip()
        or read_env_value_from_files(
            "OPENCLAW_CONTROL_URL",
            [PROJECT_ROOT / ".env", Path.home() / ".openclaw" / ".env", Path("/opt/.env")],
        ).strip()
    )
    if control_url:
        try:
            pu = urlparse(control_url)
            if pu.scheme in ("http", "https") and pu.hostname:
                port = f":{pu.port}" if pu.port else ""
                return f"{pu.scheme}://{pu.hostname}{port}"
        except Exception:
            pass
    return ""


def resolve_symbols_by_name(requirement: str, token: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,10}", requirement)
    if not candidates:
        return []
    stop_words = {
        "策略",
        "回测",
        "买入",
        "卖出",
        "上穿",
        "下穿",
        "均线",
        "日线",
        "分钟",
        "执行",
        "自动",
        "编排",
        "监控",
        "链接",
    }
    names = [c for c in candidates if c not in stop_words]
    if not names:
        return []
    try:
        import qgdata as qg  # type: ignore

        if token:
            qg.set_token(token)
        pro = qg.pro_api(timeout=8.0)
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        if df is None or len(df) == 0:
            return []
        all_rows = [(str(r["name"]), str(r["ts_code"])) for _, r in df.iterrows()]
        out: list[str] = []
        for name in names:
            exact = [ts for nm, ts in all_rows if nm == name]
            if exact:
                out.append(normalize_symbol(exact[0]))
                continue
            fuzzy = [ts for nm, ts in all_rows if name in nm]
            if len(fuzzy) == 1:
                out.append(normalize_symbol(fuzzy[0]))
        dedup = []
        seen = set()
        for sym in out:
            if sym not in seen:
                seen.add(sym)
                dedup.append(sym)
        return dedup
    except Exception:
        return []


def _resolve_stock_pool(txt: str, token: str, max_stocks: int = 50) -> list[str]:
    """解析股票池关键词→实际代码列表（全市场取主板+创业板活跃标的，控制数量避免回测过慢）"""
    pool_kw = {"全市场": "", "沪深主板": "主板", "创业板": "创业板", "科创板": "科创板", "沪深300": "主板", "中证500": "主板"}
    matched = ""
    for kw, market_filter in pool_kw.items():
        if kw in txt:
            matched = kw; break
    if not matched:
        return []
    try:
        import qgdata as qg
        if token: qg.set_token(token)
        pro = qg.pro_api(timeout=10)
        fields = "ts_code,name,market"
        df = pro.stock_basic(exchange="", list_status="L", fields=fields)
        if df is None or len(df) == 0:
            return []
        if matched == "科创板":
            df = df[df["market"] == "科创板"]
        elif matched == "创业板":
            df = df[df["market"] == "创业板"]
        elif matched in ("全市场", "沪深300", "中证500", "沪深主板"):
            df = df[df["market"].isin(["主板", "创业板"])]
        codes = [normalize_symbol(str(r["ts_code"])) for _, r in df.iterrows()]
        if len(codes) > max_stocks:
            import random; random.seed(42); codes = random.sample(codes, max_stocks)
        return codes
    except Exception:
        return []


def parse_requirement(requirement: str, symbols_override: Optional[str], token: str = "") -> Dict[str, Any]:
    txt = requirement.strip()
    symbol_matches = re.findall(r"(?<!\d)(\d{6}\.(?:SZSE|SSE|SZ|SH|SS)|\d{6})(?!\d)", txt, flags=re.IGNORECASE)
    symbols = [normalize_symbol(s) for s in symbol_matches]
    if symbols_override:
        symbols = [normalize_symbol(s) for s in symbols_override.split(",") if s.strip()]
    if not symbols:
        symbols = resolve_symbols_by_name(txt, token)
    if not symbols:
        pool = _resolve_stock_pool(txt, token)
        symbols = pool if pool else ["000001.SZSE"]

    ma_kw = ["均线", "上穿", "下穿", "金叉", "死叉", "SMA", "sma", "EMA", "ema", "日线交叉", "移动平均"]
    is_ma = any(k in txt for k in ma_kw) or bool(re.search(r'\bMA\b(?!CD)', txt))
    result: Dict[str, Any] = {"symbols": symbols}
    if is_ma:
        windows = [int(m.group(1)) for m in re.finditer(r"(\d+)\s*日", txt)]
        if len(windows) >= 2:
            result["fast_window"], result["slow_window"] = sorted(windows[:2])
        elif len(windows) == 1:
            result["fast_window"], result["slow_window"] = max(5, windows[0] // 2), windows[0]
        else:
            result["fast_window"], result["slow_window"] = 5, 10

    min_match = re.search(r"(\d+)\s*分钟|(\d+)\s*min", txt, re.IGNORECASE)
    if any(k in txt for k in ["60分钟", "小时", "hour", "1h", "60min"]):
        interval = "HOUR"
    elif min_match:
        mins = int(min_match.group(1) or min_match.group(2))
        interval = {5: "5MIN", 15: "15MIN", 30: "30MIN", 1: "MINUTE"}.get(mins, "5MIN")
    elif "分钟" in txt:
        interval = "5MIN"
    elif "周" in txt and any(k in txt for k in ["周线", "周级别", "每周", "周K"]):
        interval = "WEEKLY"
    else:
        interval = "DAILY"
    direction = "bearish" if any(k in txt for k in ["下穿", "死叉"]) else "bullish"
    multi_kw = ["轮动", "选股", "组合", "多标的", "portfolio", "多只", "排列", "全市场"]
    mode = "portfolio" if (len(symbols) > 1 or any(k in txt for k in multi_kw)) else "cta"
    result.update({"interval": interval, "direction": direction, "mode": mode})
    return result


DEFAULT_MONITOR_PORTS = [8767]  # 白名单端口，必须在防火墙/安全组中放通


def pick_free_port(candidates: Optional[list[int]] = None) -> int:
    ports = candidates or DEFAULT_MONITOR_PORTS
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    tried = ",".join(str(p) for p in ports)
    raise RuntimeError(f"白名单端口均被占用({tried})，请释放端口或通过 ORCH_MONITOR_PORT_CANDIDATES 扩展白名单")


def monitor_get(base_url: str, path: str, timeout: float = 3.0) -> Optional[str]:
    try:
        with urlopen(f"{base_url}{path}", timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def monitor_post(base_url: str, path: str, payload: Dict[str, Any], timeout: float = 5.0) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout):
            return True
    except URLError:
        return False


def monitor_step(base_url: str, *, step: str, status: str, title: str, msg: str, run_id: str) -> None:
    qs = urlencode({"step": step, "status": status, "title": title, "msg": msg, "run_id": run_id})
    monitor_get(base_url, f"/api/step?{qs}", timeout=2.0)


def probe_monitor_url(url: str, timeout: float = 2.0) -> Tuple[bool, str]:
    """Best-effort reachability probe for returned monitor URLs."""
    try:
        with urlopen(url, timeout=timeout) as resp:
            if 200 <= getattr(resp, "status", 200) < 500:
                return True, ""
            return False, f"http_status={getattr(resp, 'status', 'unknown')}"
    except Exception as exc:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return False, f"http_error:{exc}"
            except Exception as sock_exc:
                return False, f"connect_error:{sock_exc}"
        return False, f"url_error:{exc}"


def validate_monitor_public_base(base: str) -> Tuple[bool, str]:
    val = (base or "").strip().rstrip("/")
    if not val:
        return False, "MONITOR_PUBLIC_BASE is required"
    parsed = urlparse(val)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "MONITOR_PUBLIC_BASE must be a valid http(s) base URL"
    host = parsed.hostname or ""
    if host in {"0.0.0.0", "127.0.0.1", "localhost"}:
        return False, "MONITOR_PUBLIC_BASE must be publicly reachable (not localhost/0.0.0.0)"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            return False, "MONITOR_PUBLIC_BASE points to a non-public IP"
    except ValueError:
        # Hostname/domain is allowed; reachability is checked later by probe_monitor_url.
        pass
    return True, ""


def validate_strategy_file(filepath: str) -> Tuple[bool, str]:
    """校验策略文件路径安全性：必须在 STRATEGIES_DIR 内且为 .py 文件"""
    p = Path(filepath).resolve()
    if not p.suffix == ".py":
        return False, f"strategy file must be .py, got: {p.suffix}"
    if not p.exists():
        return False, f"strategy file not found: {p}"
    try:
        if not str(p).startswith(str(STRATEGIES_DIR.resolve())):
            return False, f"strategy file must be under {STRATEGIES_DIR}, got: {p}"
    except Exception as exc:
        return False, f"path resolution error: {exc}"
    return True, ""


def detect_strategy_class(filepath: Path) -> str:
    """从策略文件中自动检测 Strategy 类名"""
    try:
        content = filepath.read_text(encoding="utf-8")
        classes = re.findall(r"^class\s+(\w*Strategy\w*)\s*[\(:]", content, re.MULTILINE)
        return classes[0] if classes else ""
    except Exception:
        return ""


def normalize_public_base(base: str) -> str:
    return (base or "").strip().rstrip("/")


def public_url(base: str, name: str) -> str:
    return f"{normalize_public_base(base)}/{name}" if normalize_public_base(base) else ""


def publish_static_reports(
    *,
    run_id: str,
    output_prefix: str,
    report_public_base: str,
    report_public_dir: str,
) -> Tuple[Dict[str, str], str]:
    base = normalize_public_base(report_public_base)
    if not base:
        return {}, "REPORT_PUBLIC_BASE not configured"
    try:
        target_dir = Path(report_public_dir).expanduser().resolve() if report_public_dir else DEFAULT_REPORT_PUBLIC_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        published: Dict[str, str] = {}
        mapping = {
            f"{output_prefix}_report.html": f"{run_id}_report.html",
            f"{output_prefix}.html": f"{run_id}.html",
            f"{output_prefix}_replay.html": f"{run_id}_replay.html",
            f"{output_prefix}_summary.json": f"{run_id}_summary.json",
            f"{output_prefix}.png": f"{run_id}.png",
        }
        for src_name, dst_name in mapping.items():
            src = BACKTESTS_DIR / src_name
            if not src.exists():
                continue
            dst = target_dir / dst_name
            shutil.copy2(src, dst)
            published[dst_name] = public_url(base, dst_name)
        return published, ""
    except Exception as exc:
        return {}, str(exc)


def generate_report_html(*, run_id: str, report_data: Dict, summary: Dict, strategy_code: str = "", parsed: Dict = None) -> str:
    """生成自包含持久化报告 HTML（Tab分区 + 指标置顶 + echarts 图表）"""
    import html as _html
    stats = report_data.get("stats", summary.get("stats", {}))
    dates_json = json.dumps(report_data.get("dates", []), ensure_ascii=False)
    navs_json = json.dumps(report_data.get("navs", []))
    bench_json = json.dumps(report_data.get("bench", []))
    trades_json = json.dumps(report_data.get("trades", []), ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)
    code_escaped = _html.escape(strategy_code or "")
    p = parsed or {}
    meta = {k: str(v) for k, v in {**p, "run_id": run_id}.items() if v}
    meta_json = json.dumps(meta, ensure_ascii=False)
    return f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>回测报告 - {run_id}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/atom-one-light.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/python.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh}}
.hdr{{background:linear-gradient(135deg,#1e40af,#3b82f6);color:#fff;padding:28px 32px}}
.hdr h1{{font-size:24px;font-weight:800}}.hdr .sub{{font-size:13px;opacity:.8;margin-top:6px;font-family:monospace}}
.mx{{max-width:1200px;margin:0 auto;padding:24px 20px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px;margin-bottom:24px}}
.mc{{background:#fff;border-radius:14px;padding:18px;text-align:center;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.mc .lb{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.mc .vl{{font-size:24px;font-weight:800;margin-top:6px}}
.mc .vl.pos{{color:#16a34a}}.mc .vl.neg{{color:#dc2626}}.mc .vl.neu{{color:#475569}}
.tabs{{display:flex;gap:4px;background:#fff;border-radius:12px;padding:4px;border:1px solid #e2e8f0;margin-bottom:20px}}
.tab{{padding:10px 20px;border-radius:8px;border:none;background:transparent;cursor:pointer;font-size:14px;font-weight:600;color:#64748b;transition:all .2s}}
.tab.active{{background:#2563eb;color:#fff;box-shadow:0 2px 8px rgba(37,99,235,.25)}}
.tab:hover:not(.active){{background:#f1f5f9}}
.panel{{display:none;background:#fff;border-radius:14px;border:1px solid #e2e8f0;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.panel.active{{display:block}}
.chart-box{{width:100%;height:400px}}
.chart-box2{{width:100%;height:280px;margin-top:20px}}
.tt{{width:100%;border-collapse:collapse;font-size:13px}}
.tt th{{background:#f8fafc;color:#64748b;font-weight:600;text-align:left;padding:12px 14px;border-bottom:2px solid #e2e8f0;font-size:11px;text-transform:uppercase}}
.tt td{{padding:12px 14px;border-bottom:1px solid #f1f5f9}}
.tt tr:hover{{background:#f8fafc}}
.tt .buy{{color:#16a34a;font-weight:600}}.tt .sell{{color:#dc2626;font-weight:600}}
.pn{{display:flex;justify-content:center;gap:6px;margin-top:14px}}
.pn button{{padding:6px 12px;border:1px solid #e2e8f0;background:#fff;border-radius:6px;cursor:pointer;font-size:12px}}
.pn button.act{{background:#2563eb;color:#fff;border-color:#2563eb}}
pre.cb{{background:#fafafa;margin:0;padding:16px;font-size:13px;max-height:500px;overflow:auto;line-height:1.7;border-radius:10px;border:1px solid #e2e8f0}}
pre.cb code{{font-family:'Cascadia Code','Fira Code','Consolas',monospace}}
.info-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
.info-item{{background:#f8fafc;border-radius:10px;padding:14px;border:1px solid #e2e8f0}}
.info-item .ik{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.info-item .iv{{font-size:14px;font-weight:600;margin-top:6px;color:#1e293b;word-break:break-all}}
.ft{{text-align:center;padding:24px;font-size:12px;color:#94a3b8}}
</style></head><body>
<div class="hdr"><h1>回测报告</h1><div class="sub">run: {run_id} | generated: {now_iso()}</div></div>
<div class="mx">
<div class="metrics" id="metricsRow"></div>
<div class="tabs" id="tabBar">
  <button class="tab active" data-t="equity">收益分析</button>
  <button class="tab" data-t="trades">交易明细</button>
  <button class="tab" data-t="code">策略代码</button>
  <button class="tab" data-t="info">运行信息</button>
</div>
<div class="panel active" id="p-equity"><div class="chart-box" id="eqChart"></div><div class="chart-box2" id="dayChart"></div></div>
<div class="panel" id="p-trades"><div id="tradeArea"></div><div class="pn" id="tradeNav"></div></div>
<div class="panel" id="p-code"><pre class="cb"><code class="language-python">{code_escaped}</code></pre></div>
<div class="panel" id="p-info"><div class="info-grid" id="infoGrid"></div></div>
</div>
<div class="ft">Generated by QuantClaw | {run_id}</div>
<script>
const D={dates_json},N={navs_json},B={bench_json},T={trades_json},S={stats_json},M={meta_json};
/* --- metrics --- */
(function(){{
const fmt={{total_return:['总收益率',1],annual_return:['年化收益',1],max_ddpercent:['最大回撤',1],sharpe_ratio:['夏普比率',0],total_trade_count:['交易次数',0],winning_rate:['胜率',1],profit_days:['盈利天数',0],loss_days:['亏损天数',0]}};
let h='';for(const[k,[lb,isPct]] of Object.entries(fmt)){{const v=S[k];if(v===undefined)continue;
const n=typeof v==='number';let d=n?(isPct?v.toFixed(2)+'%':v.toFixed(4)):v;
const c=n?(v>=0?'pos':'neg'):'neu';h+='<div class="mc"><div class="lb">'+lb+'</div><div class="vl '+c+'">'+d+'</div></div>'}}
document.getElementById('metricsRow').innerHTML=h}})();
/* --- tabs --- */
document.querySelectorAll('.tab').forEach(b=>b.onclick=function(){{
document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));b.classList.add('active');
document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
document.getElementById('p-'+b.dataset.t).classList.add('active')}});
/* --- equity chart --- */
(function(){{
const ch=echarts.init(document.getElementById('eqChart'));
ch.setOption({{animation:true,tooltip:{{trigger:'axis'}},legend:{{data:['策略净值','沪深300基准'],top:10,right:16}},
grid:{{left:64,right:32,top:52,bottom:48}},
xAxis:{{type:'category',data:D,axisLabel:{{color:'#94a3b8',fontSize:11}},boundaryGap:false}},
yAxis:{{type:'value',name:'净值',min:'dataMin',axisLabel:{{color:'#64748b',formatter:v=>v.toFixed(2)}},splitLine:{{lineStyle:{{color:'#f1f5f9'}}}}}},
series:[{{name:'策略净值',type:'line',data:N,smooth:.25,lineStyle:{{width:3,color:'#2563eb'}},areaStyle:{{color:{{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{{offset:0,color:'rgba(37,99,235,.12)'}},{{offset:1,color:'rgba(37,99,235,0)'}}]}}}},symbol:'none'}},
{{name:'沪深300基准',type:'line',data:B,smooth:.25,lineStyle:{{width:2,color:'#dc2626',type:'dashed'}},symbol:'none'}}]}});
const dc=echarts.init(document.getElementById('dayChart'));
const dd=[],dl=[];for(let i=1;i<N.length&&i<D.length;i++){{const p=N[i-1]||1;dd.push(((N[i]-p)/p*100).toFixed(3));dl.push(D[i])}}
dc.setOption({{animation:true,tooltip:{{trigger:'axis'}},grid:{{left:56,right:24,top:36,bottom:48}},
xAxis:{{type:'category',data:dl,axisLabel:{{color:'#94a3b8',fontSize:10}}}},
yAxis:{{type:'value',name:'日收益%',axisLabel:{{color:'#64748b',formatter:v=>v.toFixed(2)+'%'}},splitLine:{{lineStyle:{{color:'#f1f5f9'}}}}}},
series:[{{type:'bar',data:dd.map(v=>parseFloat(v)),itemStyle:{{color:function(p){{return p.data>=0?'#16a34a':'#dc2626'}}}},barWidth:'60%'}}]}});
window.addEventListener('resize',()=>{{ch.resize();dc.resize()}})
}})();
/* --- trades --- */
(function(){{
let pg=1;const ps=15;
function render(){{
const s=(pg-1)*ps,page=T.slice(s,s+ps);
let h='<table class="tt"><thead><tr><th>日期</th><th>标的</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>盈亏</th></tr></thead><tbody>';
page.forEach(t=>{{const ib=t.direction==='买入'||t.direction==='BUY';const pnl=t.pnl||'';const ps=pnl?(parseFloat(pnl)>=0?'color:#16a34a;font-weight:600':'color:#dc2626;font-weight:600'):'';const sym=t.symbol||'';h+='<tr><td>'+t.date+'</td><td>'+sym+'</td><td class="'+(ib?'buy':'sell')+'">'+(ib?'买入':'卖出')+'</td><td>'+t.price+'</td><td>'+t.volume+'</td><td>'+t.amount+'</td><td style="'+ps+'">'+pnl+'</td></tr>'}});
h+='</tbody></table>';document.getElementById('tradeArea').innerHTML=h||'<div style="color:#94a3b8;text-align:center;padding:40px">暂无交易记录</div>';
const tp=Math.ceil(T.length/ps),nav=document.getElementById('tradeNav');
if(tp>1){{let p='';for(let i=1;i<=tp;i++)p+='<button class="'+(i===pg?'act':'')+'" onclick="window._tp('+i+')">'+i+'</button>';nav.innerHTML=p}}else nav.innerHTML=''}}
window._tp=function(n){{pg=n;render()}};render()
}})();
/* --- info --- */
(function(){{
let h='';for(const[k,v] of Object.entries(M))h+='<div class="info-item"><div class="ik">'+k+'</div><div class="iv">'+v+'</div></div>';
document.getElementById('infoGrid').innerHTML=h||'<div style="color:#94a3b8">无额外信息</div>'}})();
hljs.highlightAll();
</script></body></html>'''


class RunStore:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.run_dir = RUNS_DIR / run_id
        self.state_file = self.run_dir / "state.json"
        self.run_log = self.run_dir / "worker.log"
        self.monitor_log = self.run_dir / "monitor.log"

    def init_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "version": STATE_VERSION,
            "run_id": self.run_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "status": "submitted",
            "payload": payload,
            "steps": {},
            "process": {},
            "artifacts": {},
            "errors": [],
        }
        atomic_json_write(self.state_file, state)
        return state

    def load(self) -> Dict[str, Any]:
        return read_json(self.state_file)

    def save(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = now_iso()
        atomic_json_write(self.state_file, state)

    def mark_step(self, state: Dict[str, Any], name: str, status: str, detail: str = "") -> None:
        state["steps"][name] = {"status": status, "detail": detail, "at": now_iso()}
        self.save(state)

    def append_error(self, state: Dict[str, Any], message: str) -> None:
        state["errors"].append({"at": now_iso(), "message": message})
        self.save(state)


def start_process(command: list[str], log_path: Path, env: Optional[Dict[str, str]] = None) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = log_path.open("a", encoding="utf-8")
    return subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env or os.environ.copy(),
        stdout=f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _lot_size_for_symbol(code: str) -> int:
    """根据A股代码确定最小交易单位：科创板688xxx→200股，其余→100股"""
    digits = "".join(c for c in code if c.isdigit())[:6]
    return 200 if digits.startswith("688") else 100


def strategy_source(class_name: str, fast: int, slow: int, author: str, direction: str) -> str:
    return f'''"""Auto-generated MA cross strategy — 动态全仓 + 交易所合规手数"""
from vnpy_ctastrategy import CtaTemplate
from vnpy_ctastrategy.base import StopOrder
from vnpy.trader.object import BarData, TradeData, OrderData
from vnpy.trader.utility import ArrayManager


def _calc_volume(symbol: str, price: float, capital: float) -> int:
    """按资金全仓计算合规手数：主板/创业板100股整数倍，科创板(688)200起+1股递增"""
    digits = "".join(c for c in symbol if c.isdigit())[:6]
    if digits.startswith("688"):
        vol = int(capital / price)
        return max(vol, 200) if vol >= 200 else 0
    else:
        vol = int(capital / price / 100) * 100
        return max(vol, 100) if vol >= 100 else 0


class {class_name}(CtaTemplate):
    author = "{author}"
    fast_window = {fast}
    slow_window = {slow}
    capital = 1000000.0
    direction_hint = "{direction}"

    parameters = ["fast_window", "slow_window", "capital", "direction_hint"]
    variables = ["fast_ma", "slow_ma"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.am = ArrayManager(size=self.slow_window + 5)
        self.fast_ma = 0.0
        self.slow_ma = 0.0
        self.prev_fast = 0.0
        self.prev_slow = 0.0

    def on_init(self):
        self.load_bar(self.slow_window + 20)

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_bar(self, bar: BarData):
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        self.cancel_all()
        self.prev_fast = self.fast_ma
        self.prev_slow = self.slow_ma
        self.fast_ma = self.am.sma(self.fast_window)
        self.slow_ma = self.am.sma(self.slow_window)

        cross_up = self.prev_fast <= self.prev_slow and self.fast_ma > self.slow_ma
        cross_down = self.prev_fast >= self.prev_slow and self.fast_ma < self.slow_ma

        if self.pos == 0 and cross_up:
            vol = _calc_volume(self.vt_symbol, bar.close_price, self.capital)
            self.buy(bar.close_price * 1.31, vol)
        elif self.pos > 0 and cross_down:
            self.sell(bar.close_price * 0.69, abs(self.pos))

        self.put_event()

    def on_trade(self, trade: TradeData):
        self.put_event()

    def on_order(self, order: OrderData):
        pass

    def on_stop_order(self, stop_order: StopOrder):
        pass
'''


def portfolio_strategy_source(class_name: str, fast: int, slow: int, author: str, direction: str, vt_symbols: list[str]) -> str:
    syms_str = json.dumps(vt_symbols)
    return f'''"""Auto-generated Portfolio MA cross strategy — 多标的组合 + 动态全仓 + 交易所合规手数"""
from vnpy_portfoliostrategy import StrategyTemplate
from vnpy.trader.object import BarData
from vnpy.trader.utility import ArrayManager


def _calc_volume(symbol: str, price: float, capital: float) -> int:
    """按资金动态计算合规手数：主板/创业板100股整数倍，科创板(688)200起+1股递增"""
    digits = "".join(c for c in symbol if c.isdigit())[:6]
    if digits.startswith("688"):
        vol = int(capital / price)
        return max(vol, 200) if vol >= 200 else 0
    else:
        vol = int(capital / price / 100) * 100
        return max(vol, 100) if vol >= 100 else 0


class {class_name}(StrategyTemplate):
    author = "{author}"
    fast_window = {fast}
    slow_window = {slow}
    capital = 1000000.0
    direction_hint = "{direction}"

    parameters = ["fast_window", "slow_window", "capital", "direction_hint"]
    variables = []

    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        self.vt_symbols = {syms_str}
        self.ams: dict[str, ArrayManager] = {{s: ArrayManager(size=self.slow_window + 5) for s in self.vt_symbols}}
        self.prev_fast: dict[str, float] = {{s: 0.0 for s in self.vt_symbols}}
        self.prev_slow: dict[str, float] = {{s: 0.0 for s in self.vt_symbols}}

    def on_init(self):
        self.load_bars(self.slow_window + 20)

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_bars(self, bars: dict[str, BarData]):
        per_capital = self.capital / max(len(self.vt_symbols), 1)
        for vt_symbol in self.vt_symbols:
            bar = bars.get(vt_symbol)
            if not bar:
                continue
            am = self.ams[vt_symbol]
            am.update_bar(bar)
            if not am.inited:
                continue

            prev_f = self.prev_fast.get(vt_symbol, 0.0)
            prev_s = self.prev_slow.get(vt_symbol, 0.0)
            fast_ma = am.sma(self.fast_window)
            slow_ma = am.sma(self.slow_window)
            self.prev_fast[vt_symbol] = fast_ma
            self.prev_slow[vt_symbol] = slow_ma

            cross_up = prev_f <= prev_s and fast_ma > slow_ma
            cross_down = prev_f >= prev_s and fast_ma < slow_ma

            pos = self.get_pos(vt_symbol)
            if pos == 0 and cross_up:
                vol = _calc_volume(vt_symbol, bar.close_price, per_capital)
                if vol > 0:
                    self.buy(vt_symbol, bar.close_price * 1.31, vol)
            elif pos > 0 and cross_down:
                self.sell(vt_symbol, bar.close_price * 0.69, abs(pos))

        self.put_event()
'''


def wait_monitor_ready(base_url: str, timeout_sec: int = 20) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if monitor_get(base_url, "/api/health", timeout=1.5) is not None:
            return True
        time.sleep(0.5)
    return False


def cmd_submit(args: argparse.Namespace) -> int:
    resolved_monitor_public_base = resolve_monitor_public_base(args.monitor_public_base)
    ok, err = validate_monitor_public_base(resolved_monitor_public_base)
    if not ok:
        print(
            json.dumps(
                {
                    "status": "config_missing",
                    "error": err,
                    "next_action": "请先配置公网 MONITOR_PUBLIC_BASE，或配置 OPENCLAW_CONTROL_URL 让系统自动推导（例如 https://your-control-host）",
                },
                ensure_ascii=False,
            )
        )
        return 1

    run_id = args.run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    store = RunStore(run_id)
    if store.state_file.exists():
        print(json.dumps({"status": "error", "error": f"run_id already exists: {run_id}"}, ensure_ascii=False))
        return 1

    resolved_token = resolve_qgdata_token(args.token)
    parsed = parse_requirement(args.requirement, args.symbols, resolved_token)
    cap = evaluate_requirement(args.requirement).to_dict()
    if not cap.get("ok", False):
        print(
            json.dumps(
                {
                    "status": cap.get("status", "clarification_needed"),
                    "message": "需求与当前数据能力不匹配，未启动后台编排。",
                    "capability_check": cap,
                },
                ensure_ascii=False,
            )
        )
        return 2
    raw_candidates = args.monitor_port_candidates or os.getenv("ORCH_MONITOR_PORT_CANDIDATES", "")
    candidate_ports: list[int] = []
    if raw_candidates:
        for tok in raw_candidates.split(","):
            tok = tok.strip()
            if tok:
                try: candidate_ports.append(int(tok))
                except ValueError: pass
    monitor_port = args.monitor_port or pick_free_port(candidate_ports or None)
    monitor_base = f"http://127.0.0.1:{monitor_port}"
    monitor_url = f"{resolved_monitor_public_base.rstrip('/')}:{monitor_port}/runs/{run_id}"
    monitor_url_local = f"http://127.0.0.1:{monitor_port}/runs/{run_id}"
    report_public_base = normalize_public_base(args.report_public_base)
    report_url = public_url(report_public_base, f"{run_id}.html")
    report_replay_url = public_url(report_public_base, f"{run_id}_replay.html")
    report_summary_url = public_url(report_public_base, f"{run_id}_summary.json")
    public_reachable = False
    public_probe_error = "probe_pending"
    strategy_file = ""
    strategy_module = args.strategy_module
    strategy_class = args.strategy_class
    if args.strategy_file:
        sf_ok, sf_err = validate_strategy_file(args.strategy_file)
        if not sf_ok:
            print(json.dumps({"status": "error", "error": sf_err, "next_action": "请检查策略文件路径"}, ensure_ascii=False))
            return 1
        strategy_file = str(Path(args.strategy_file).resolve())
        if not strategy_module:
            strategy_module = Path(strategy_file).stem
        if not strategy_class:
            strategy_class = detect_strategy_class(Path(strategy_file))
            if not strategy_class:
                print(json.dumps({"status": "error", "error": f"无法在 {strategy_file} 中检测到 Strategy 类", "next_action": "请通过 --strategy-class 显式指定"}, ensure_ascii=False))
                return 1

    payload = {
        "requirement": args.requirement,
        "parsed": parsed,
        "capability_check": cap,
        "monitor_port": monitor_port,
        "monitor_base": monitor_base,
        "monitor_url": monitor_url,
        "monitor_url_local": monitor_url_local,
        "monitor_public_base": resolved_monitor_public_base,
        "monitor_public_reachable": public_reachable,
        "monitor_public_probe_error": public_probe_error,
        "report_public_base": report_public_base,
        "report_public_dir": args.report_public_dir,
        "report_url": report_url,
        "report_replay_url": report_replay_url,
        "report_summary_url": report_summary_url,
        "start": args.start,
        "end": args.end,
        "interval": args.interval or parsed["interval"],
        "capital": args.capital,
        "rate": args.rate,
        "slippage": args.slippage,
        "size": args.size,
        "pricetick": args.pricetick,
        "title": args.title,
        "python_bin": args.python_bin or DEFAULT_PYTHON_BIN,
        "qgdata_token_present": bool(resolved_token),
        "timeout_sec": args.timeout_sec,
        "strategy_file": strategy_file,
        "strategy_module": strategy_module,
        "strategy_class": strategy_class,
    }
    state = store.init_state(payload)

    monitor_cmd = [
        payload["python_bin"],
        str(MONITOR_SERVER),
        "--host",
        MONITOR_BIND_HOST,
        "--port",
        str(monitor_port),
        "--run-id",
        run_id,
    ]
    mon_proc = start_process(monitor_cmd, store.monitor_log)
    state["process"]["monitor_pid"] = mon_proc.pid
    store.save(state)
    if not wait_monitor_ready(monitor_base):
        store.append_error(state, "monitor server failed to start")
        state["status"] = "failed"
        store.save(state)
        print(json.dumps({"status": "error", "error": "monitor startup failed", "run_id": run_id}, ensure_ascii=False))
        return 1

    public_reachable, public_probe_error = probe_monitor_url(monitor_url, timeout=3.0)
    payload["monitor_public_reachable"] = public_reachable
    payload["monitor_public_probe_error"] = public_probe_error
    state["payload"] = payload
    store.save(state)

    if not public_reachable:
        try: mon_proc.kill()
        except Exception: pass
        state["status"] = "failed"
        store.append_error(state, f"monitor公网不可达: {public_probe_error}")
        store.save(state)
        print(json.dumps({
            "status": "config_missing",
            "error": f"monitor_url 公网不可达: {monitor_url} ({public_probe_error})",
            "monitor_port": monitor_port,
            "next_action": f"请确认: 1) MONITOR_PUBLIC_BASE 指向正确的公网地址; 2) 防火墙/安全组已放通端口 {monitor_port}; 3) 运行 config-doctor 一键诊断: python3 pipeline_orchestrator.py config-doctor",
        }, ensure_ascii=False))
        return 1

    monitor_post(monitor_base, "/api/requirement", {"requirement": args.requirement, **parsed, "run_id": run_id})
    monitor_step(monitor_base, step="1", status="success", title="需求确认", msg="监控页面已启动", run_id=run_id)
    store.mark_step(state, "monitor", "success", "monitor started and requirement posted")

    worker_cmd = [payload["python_bin"], str(Path(__file__).resolve()), "worker", "--run-id", run_id]
    worker_env = os.environ.copy()
    if resolved_token:
        worker_env["QGDATA_TOKEN"] = resolved_token
    worker_proc = start_process(worker_cmd, store.run_log, env=worker_env)
    state["process"]["worker_pid"] = worker_proc.pid
    state["status"] = "running"
    store.save(state)

    print(
        json.dumps(
            {
                "status": "accepted",
                "run_id": run_id,
                "monitor_url": monitor_url,
                "monitor_url_local": monitor_url_local,
                "monitor_public_base": resolved_monitor_public_base,
                "monitor_public_reachable": public_reachable,
                "monitor_public_probe_error": public_probe_error,
                "report_url": report_url,
                "report_replay_url": report_replay_url,
                "report_summary_url": report_summary_url,
                "state_file": str(store.state_file),
                "worker_pid": worker_proc.pid,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    qgdata_token = os.getenv("QGDATA_TOKEN", "") or resolve_qgdata_token("")
    store = RunStore(args.run_id)
    state = store.load()
    payload = state["payload"]
    run_id = state["run_id"]
    monitor_base = payload["monitor_base"]
    parsed = payload["parsed"]
    output_prefix = f"run_{run_id}"

    def _structured_error(state_: Dict, error_type: str, step: str, message: str, tb: str = "") -> None:
        """保存结构化错误到 state"""
        state_["errors"].append({"at": now_iso(), "error_type": error_type, "step": step, "message": message, "traceback": tb[:4000]})
        store.save(state_)
        monitor_post(monitor_base, "/api/error", {"error_type": error_type, "step": step, "message": message, "traceback": tb[:2000]})
        monitor_get(monitor_base, f"/api/log?{urlencode({'msg': f'[{error_type}] {step}: {message}'})}", timeout=2.0)

    def _fail_report(state_: Dict, error_msg: str) -> None:
        """失败时也生成最小 report HTML"""
        try:
            code = ""
            sf = state_.get("artifacts", {}).get("strategy_file", "") or state_.get("artifacts", {}).get("strategy_snapshot", "")
            if sf and Path(sf).exists():
                try: code = Path(sf).read_text(encoding="utf-8")
                except Exception: pass
            fail_data = {"dates": [], "navs": [], "bench": [], "trades": [], "stats": {}}
            fail_summary = {"stats": {"error": error_msg}}
            html = generate_report_html(run_id=run_id, report_data=fail_data, summary=fail_summary, strategy_code=code, parsed=parsed)
            rpath = BACKTESTS_DIR / f"{output_prefix}_report.html"
            rpath.write_text(html, encoding="utf-8")
            state_["artifacts"]["report_html"] = str(rpath)
            published, _ = publish_static_reports(run_id=run_id, output_prefix=output_prefix, report_public_base=payload.get("report_public_base", ""), report_public_dir=payload.get("report_public_dir", ""))
            if published:
                state_["artifacts"]["report_public_urls"] = published
                payload["report_url"] = published.get(f"{run_id}_report.html", payload.get("report_url", ""))
                state_["payload"] = payload
            store.save(state_)
        except Exception:
            pass

    try:
        ext_strategy_file = payload.get("strategy_file", "")
        if ext_strategy_file and Path(ext_strategy_file).exists():
            monitor_step(monitor_base, step="2", status="running", title="策略加载", msg="加载外部策略文件", run_id=run_id)
            module_name = payload.get("strategy_module", "") or Path(ext_strategy_file).stem
            class_name = payload.get("strategy_class", "") or detect_strategy_class(Path(ext_strategy_file))
            snapshot_path = store.run_dir / "strategy_snapshot.py"
            shutil.copy2(ext_strategy_file, snapshot_path)
            state["artifacts"]["strategy_snapshot"] = str(snapshot_path)
            strategy_file_path = Path(ext_strategy_file)
            source = strategy_file_path.read_text(encoding="utf-8")
            monitor_post(monitor_base, "/api/code", {"filename": strategy_file_path.name, "content": source})
            monitor_step(monitor_base, step="2", status="success", title="策略加载", msg=f"外部策略已加载: {strategy_file_path.name}", run_id=run_id)
            state["artifacts"]["strategy_file"] = ext_strategy_file
            state["status"] = "code_ready"
            store.mark_step(state, "strategy_generation", "success", f"external: {strategy_file_path.name}")
        else:
            bt_mode = parsed.get("mode", "cta")
            monitor_step(monitor_base, step="2", status="running", title="策略生成", msg=f"正在生成{bt_mode.upper()}策略代码", run_id=run_id)
            module_name = f"auto_ma_{run_id}".lower()
            class_name = "AutoMaCrossStrategy" if bt_mode == "cta" else "AutoPortfolioStrategy"
            strategy_file_path = STRATEGIES_DIR / f"{module_name}.py"
            fw, sw = parsed.get("fast_window", 5), parsed.get("slow_window", 10)
            if bt_mode == "portfolio":
                source = portfolio_strategy_source(class_name, fw, sw, "quant-strategy-assistant", parsed["direction"], [normalize_symbol(s) for s in parsed["symbols"]])
            else:
                source = strategy_source(class_name, fw, sw, "quant-strategy-assistant", parsed["direction"])
            strategy_file_path.write_text(source, encoding="utf-8")
            subprocess.run([payload["python_bin"], "-m", "py_compile", str(strategy_file_path)], check=True, cwd=str(PROJECT_ROOT))
            monitor_post(monitor_base, "/api/code", {"filename": strategy_file_path.name, "content": source})
            monitor_step(monitor_base, step="2", status="success", title="策略生成", msg=f"策略已生成: {strategy_file_path.name}", run_id=run_id)
            state["artifacts"]["strategy_file"] = str(strategy_file_path)
            store.mark_step(state, "strategy_generation", "success", strategy_file_path.name)

        monitor_step(monitor_base, step="3", status="success", title="策略就绪", msg=f"策略已就绪: {module_name}.{class_name}", run_id=run_id)
        monitor_step(monitor_base, step="4", status="running", title="回测执行", msg="回测已启动", run_id=run_id)
        cmd = [
            payload["python_bin"],
            str(BACKTEST_RUNNER),
            "--strategy",
            module_name,
            "--class",
            class_name,
            "--symbols",
            ",".join(parsed["symbols"]),
            "--mode",
            parsed.get("mode", "cta"),
            "--interval",
            payload["interval"],
            "--capital",
            str(payload["capital"]),
            "--rate",
            str(payload["rate"]),
            "--slippage",
            str(payload["slippage"]),
            "--size",
            str(payload["size"]),
            "--pricetick",
            str(payload["pricetick"]),
            "--output",
            output_prefix,
            "--title",
            payload["title"] or f"Auto MA Cross {run_id}",
            "--monitor-port",
            str(payload["monitor_port"]),
            "--run-id",
            run_id,
            "--monitor-keepalive-sec",
            "5",
        ]
        if payload.get("start"):
            cmd.extend(["--start", payload["start"]])
        if payload.get("end"):
            cmd.extend(["--end", payload["end"]])
        if qgdata_token:
            cmd.extend(["--token", qgdata_token])

        run_log_path = store.run_dir / "backtest.log"
        proc = start_process(cmd, run_log_path, env={**os.environ, "QUANTCLAW_ROOT": str(PROJECT_ROOT), "QMT_PROJECT_ROOT": str(PROJECT_ROOT)})
        state["process"]["backtest_pid"] = proc.pid
        store.save(state)

        timeout_sec = int(payload.get("timeout_sec", 1200))
        deadline = time.time() + timeout_sec
        while True:
            ret = proc.poll()
            if ret is not None:
                if ret != 0:
                    raise RuntimeError(f"backtest runner exit code={ret}")
                break
            if time.time() > deadline:
                proc.kill()
                raise TimeoutError(f"backtest timeout after {timeout_sec}s")
            time.sleep(2)

        summary_path = BACKTESTS_DIR / f"{output_prefix}_summary.json"
        if summary_path.exists():
            summary = read_json(summary_path)
            state["artifacts"]["summary_file"] = str(summary_path)
            state["artifacts"]["summary"] = summary
            report_data_path = BACKTESTS_DIR / f"{output_prefix}_report_data.json"
            report_data = read_json(report_data_path) if report_data_path.exists() else {}
            strategy_code = ""
            sf = state["artifacts"].get("strategy_file", "")
            if sf and Path(sf).exists():
                try: strategy_code = Path(sf).read_text(encoding="utf-8")
                except Exception: pass
            report_html = generate_report_html(run_id=run_id, report_data=report_data, summary=summary, strategy_code=strategy_code, parsed=parsed)
            report_html_path = BACKTESTS_DIR / f"{output_prefix}_report.html"
            report_html_path.write_text(report_html, encoding="utf-8")
            state["artifacts"]["report_html"] = str(report_html_path)
            published_reports, publish_err = publish_static_reports(
                run_id=run_id,
                output_prefix=output_prefix,
                report_public_base=payload.get("report_public_base", ""),
                report_public_dir=payload.get("report_public_dir", ""),
            )
            if published_reports:
                state["artifacts"]["report_public_urls"] = published_reports
                payload["report_url"] = published_reports.get(f"{run_id}_report.html", published_reports.get(f"{run_id}.html", payload.get("report_url", "")))
                payload["report_replay_url"] = published_reports.get(f"{run_id}_replay.html", payload.get("report_replay_url", ""))
                payload["report_summary_url"] = published_reports.get(f"{run_id}_summary.json", payload.get("report_summary_url", ""))
                state["payload"] = payload
            elif publish_err and publish_err != "REPORT_PUBLIC_BASE not configured":
                store.append_error(state, f"report publish warning: {publish_err}")
            report_url_final = payload.get("report_url", "")
            monitor_post(monitor_base, "/api/report_urls", {
                "report_url": report_url_final,
                "report_replay_url": payload.get("report_replay_url", ""),
                "report_summary_url": payload.get("report_summary_url", ""),
            })
            monitor_step(monitor_base, step="5", status="success", title="结果展示", msg="回测完成，结果已生成", run_id=run_id)
            store.mark_step(state, "result", "success", str(summary_path))
        else:
            store.mark_step(state, "result", "running", "summary pending")

        state["status"] = "completed"
        store.save(state)
        return 0
    except subprocess.CalledProcessError as exc:
        import traceback as _tb
        state["status"] = "failed"
        _structured_error(state, "compile_error", "strategy_generation", str(exc), _tb.format_exc())
        _fail_report(state, str(exc))
        monitor_step(monitor_base, step="9", status="failed", title="编译失败", msg=str(exc)[:200], run_id=run_id)
        store.save(state)
        return 1
    except TimeoutError as exc:
        import traceback as _tb
        state["status"] = "failed"
        _structured_error(state, "timeout_error", "backtest_execution", str(exc), _tb.format_exc())
        _fail_report(state, str(exc))
        monitor_step(monitor_base, step="9", status="failed", title="回测超时", msg=str(exc)[:200], run_id=run_id)
        store.save(state)
        return 1
    except RuntimeError as exc:
        import traceback as _tb
        tb_str = _tb.format_exc()
        etype = "data_error" if any(k in str(exc) for k in ["0 bars", "无数据", "data", "token"]) else "runtime_error"
        state["status"] = "failed"
        _structured_error(state, etype, "backtest_execution", str(exc), tb_str)
        _fail_report(state, str(exc))
        monitor_step(monitor_base, step="9", status="failed", title="执行失败", msg=str(exc)[:200], run_id=run_id)
        store.save(state)
        return 1
    except Exception as exc:
        import traceback as _tb
        state["status"] = "failed"
        _structured_error(state, "runtime_error", "unknown", str(exc), _tb.format_exc())
        _fail_report(state, str(exc))
        monitor_step(monitor_base, step="9", status="failed", title="执行失败", msg=str(exc)[:200], run_id=run_id)
        store.save(state)
        return 1
    finally:
        done_ok = monitor_post(monitor_base, "/api/done", {})
        mon_pid = state.get("process", {}).get("monitor_pid")
        # done 回调成功时保留短窗口供用户查看失败日志；仅在回调失败时兜底强杀，防泄漏。
        if mon_pid and not done_ok:
            try: os.kill(mon_pid, 15)
            except OSError: pass


def cmd_status(args: argparse.Namespace) -> int:
    state = RunStore(args.run_id).load()
    errors = state.get("errors", [])
    if errors:
        last = errors[-1]
        state["last_error"] = {"error_type": last.get("error_type", "unknown"), "step": last.get("step", ""), "message": last.get("message", str(last))}
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    runs = sorted(RUNS_DIR.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    payload = []
    for p in runs[: args.limit]:
        st = read_json(p)
        payload.append(
            {
                "run_id": st["run_id"],
                "status": st.get("status"),
                "updated_at": st.get("updated_at"),
                "monitor_url": st.get("payload", {}).get("monitor_url"),
                "report_url": st.get("payload", {}).get("report_url"),
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quant strategy orchestration pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    submit = sub.add_parser("submit", help="Submit a run and return monitor URL immediately")
    submit.add_argument("--requirement", required=True, help="Natural language strategy requirement")
    submit.add_argument("--run-id", default="", help="Optional custom run id")
    submit.add_argument("--symbols", default="", help="Optional symbols CSV override")
    submit.add_argument("--monitor-port", type=int, default=0, help="Optional fixed monitor port")
    submit.add_argument(
        "--monitor-port-candidates",
        default=os.getenv("ORCH_MONITOR_PORT_CANDIDATES", ",".join(str(p) for p in DEFAULT_MONITOR_PORTS)),
        help="白名单端口CSV（必须在防火墙放通），默认 8767",
    )
    submit.add_argument("--monitor-public-base", default=os.getenv("MONITOR_PUBLIC_BASE", ""))
    submit.add_argument("--report-public-base", default=os.getenv("REPORT_PUBLIC_BASE", ""))
    submit.add_argument("--report-public-dir", default=os.getenv("REPORT_PUBLIC_DIR", str(DEFAULT_REPORT_PUBLIC_DIR)))
    submit.add_argument("--python-bin", default=DEFAULT_PYTHON_BIN)
    submit.add_argument("--token", default="")
    submit.add_argument("--start", default="")
    submit.add_argument("--end", default="")
    submit.add_argument("--interval", default="")
    submit.add_argument("--capital", type=float, default=1000000)
    submit.add_argument("--rate", type=float, default=0.0003)
    submit.add_argument("--slippage", type=float, default=0.01)
    submit.add_argument("--size", type=float, default=1)
    submit.add_argument("--pricetick", type=float, default=0.01)
    submit.add_argument("--title", default="")
    submit.add_argument("--timeout-sec", type=int, default=int(os.getenv("ORCH_BACKTEST_TIMEOUT_SEC", "1200")))
    submit.add_argument("--strategy-file", default="", help="Pre-generated strategy .py file path (Shift-Left mode)")
    submit.add_argument("--strategy-module", default="", help="Strategy module name (default: derived from file)")
    submit.add_argument("--strategy-class", default="", help="Strategy class name (default: auto-detect from file)")

    worker = sub.add_parser("worker", help="Internal worker command")
    worker.add_argument("--run-id", required=True)

    status = sub.add_parser("status", help="Read run state")
    status.add_argument("--run-id", required=True)

    ls_cmd = sub.add_parser("list", help="List recent runs")
    ls_cmd.add_argument("--limit", type=int, default=20)

    sub.add_parser("config-doctor", help="一键诊断所有必需配置项")
    sub.add_parser("qmt-check", help="检测 QMT 模拟/实盘环境可用性")

    opt = sub.add_parser("optimize", help="参数优化（穷举/遗传算法）")
    opt.add_argument("--strategy-file", required=True, help="策略文件路径")
    opt.add_argument("--strategy-class", required=True, help="策略类名")
    opt.add_argument("--symbols", required=True, help="标的代码（如 600519.SSE）")
    opt.add_argument("--optimize-params", required=True, help='优化参数JSON: {"target":"sharpe_ratio","params":{"fast_window":[5,30,5]}}')
    _d_end = datetime.now().strftime("%Y%m%d")
    _d_start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    opt.add_argument("--start", default=_d_start)
    opt.add_argument("--end", default=_d_end)
    opt.add_argument("--interval", default="DAILY")
    opt.add_argument("--capital", type=float, default=1000000)
    opt.add_argument("--rate", type=float, default=0.0003)
    opt.add_argument("--slippage", type=float, default=0.01)
    opt.add_argument("--size", type=float, default=1)
    opt.add_argument("--pricetick", type=float, default=0.01)
    opt.add_argument("--top-n", type=int, default=10, help="返回前N组最优参数")

    return parser


def cmd_config_doctor(_args: argparse.Namespace) -> int:
    """逐项校验所有环境配置，输出 PASS/FAIL/WARN 清单"""
    results: list[Dict[str, str]] = []
    all_ok = True

    def _check(name: str, ok: bool, val: str, hint: str):
        nonlocal all_ok
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        results.append({"check": name, "status": status, "value": val or "(空)", "hint": hint})

    def _warn(name: str, val: str, hint: str):
        results.append({"check": name, "status": "WARN", "value": val or "(空)", "hint": hint})

    root = os.getenv("QUANTCLAW_ROOT", "") or os.getenv("QMT_PROJECT_ROOT", "")
    root_ok = bool(root) and Path(root).is_dir() and (Path(root) / "backtests" / "pipeline_orchestrator.py").exists()
    _check("QUANTCLAW_ROOT", root_ok, root, "项目根目录，应包含 backtests/pipeline_orchestrator.py（也接受 QMT_PROJECT_ROOT）" if not root_ok else "OK")

    py = os.getenv("PYTHON_BIN", "") or DEFAULT_PYTHON_BIN
    py_ok = shutil.which(py) is not None
    _check("PYTHON_BIN", py_ok, py, f"找不到 {py}，请安装或修正路径" if not py_ok else "OK")

    mpb = resolve_monitor_public_base("")
    mpb_valid, mpb_err = validate_monitor_public_base(mpb) if mpb else (False, "未配置")
    _check("MONITOR_PUBLIC_BASE", mpb_valid, mpb, mpb_err if not mpb_valid else "OK")

    ports_raw = os.getenv("ORCH_MONITOR_PORT_CANDIDATES", ",".join(str(p) for p in DEFAULT_MONITOR_PORTS))
    ports = [int(x) for x in ports_raw.split(",") if x.strip().isdigit()]
    if mpb_valid and ports:
        port_results = []
        for p in ports:
            test_url = f"{mpb.rstrip('/')}:{p}/"
            try:
                with socket.create_connection((urlparse(mpb).hostname or "", p), timeout=2.0):
                    port_results.append((p, True, ""))
            except Exception as e:
                port_results.append((p, False, str(e)))
        any_ok = any(ok for _, ok, _ in port_results)
        detail = "; ".join(f"{p}={'通' if ok else '不通('+err+')'}" for p, ok, err in port_results)
        _check("端口公网可达", any_ok, detail, "请在安全组/防火墙放通这些端口" if not any_ok else "OK")
    else:
        _warn("端口公网可达", ports_raw, "需先修复 MONITOR_PUBLIC_BASE 才能测试端口连通性")

    token = resolve_qgdata_token("")
    token_ok = bool(token)
    if token_ok:
        try:
            import qgdata as qg  # type: ignore
            qg.set_token(token)
            pro = qg.pro_api(timeout=5.0)
            df = pro.stock_basic(exchange="", list_status="L", fields="ts_code", limit=1)
            token_ok = df is not None and len(df) > 0
            _check("QGDATA_TOKEN", token_ok, token[:6] + "***", "Token 校验通过" if token_ok else "Token 无效或接口无权限，请确认 Pro 套餐")
        except Exception as e:
            _check("QGDATA_TOKEN", False, token[:6] + "***", f"Token 校验异常: {e}")
    else:
        _check("QGDATA_TOKEN", False, "", "未配置，前往 https://quantgo.ai/data 获取")

    ctrl = os.getenv("OPENCLAW_CONTROL_URL", "") or read_env_value_from_files("OPENCLAW_CONTROL_URL", [PROJECT_ROOT / ".env", Path.home() / ".openclaw" / ".env"])
    if ctrl:
        _warn("OPENCLAW_CONTROL_URL", ctrl, "已配置（用于自动推导 MONITOR_PUBLIC_BASE）")
    else:
        _warn("OPENCLAW_CONTROL_URL", "", "未配置（可选，可用于自动推导公网基址）")

    rpb = os.getenv("REPORT_PUBLIC_BASE", "")
    rpd = os.getenv("REPORT_PUBLIC_DIR", str(DEFAULT_REPORT_PUBLIC_DIR))
    if rpb:
        _warn("REPORT_PUBLIC_BASE", rpb, "已配置")
    else:
        _warn("REPORT_PUBLIC_BASE", "", "未配置（可选，用于持久化报告公网链接）")
    rpd_ok = Path(rpd).is_dir() or not rpb
    if rpb and not rpd_ok:
        _check("REPORT_PUBLIC_DIR", False, rpd, "目录不存在，请创建或修正")
    else:
        _warn("REPORT_PUBLIC_DIR", rpd, "OK" if rpd_ok else "目录不存在")

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        _warn(".env 文件", str(env_file), "已存在")
    else:
        example = PROJECT_ROOT.parent / ".env.example"
        hint = f"不存在。建议: cp {example} {env_file} 然后编辑" if example.exists() else "不存在。建议创建 .env 文件配置环境变量"
        _warn(".env 文件", str(env_file), hint)

    print("\n" + "=" * 60)
    print("  QuantClaw Config Doctor")
    print("  https://gitee.com/GuojinQuant/quant-claw")
    print("=" * 60)
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}[r["status"]]
        print(f"\n  {icon} [{r['status']}] {r['check']}")
        print(f"    值: {r['value']}")
        print(f"    {r['hint']}")
    print("\n" + "-" * 60)
    if all_ok:
        print("  所有必需项通过 ✓  可以正常运行")
    else:
        fail_count = sum(1 for r in results if r["status"] == "FAIL")
        print(f"  {fail_count} 项未通过，请按提示修复后重新运行:")
        print(f"  python3 {Path(__file__).name} config-doctor")
        print(f"\n  详细配置指南: https://gitee.com/GuojinQuant/quant-claw#第四步配置环境变量")
    print("=" * 60 + "\n")
    return 0 if all_ok else 1


def cmd_optimize(args: argparse.Namespace) -> int:
    """参数优化：穷举遍历参数组合，返回最优参数集（JSON）"""
    strategy_file = Path(args.strategy_file).resolve()
    if not strategy_file.exists():
        print(json.dumps({"status": "error", "error": f"策略文件不存在: {strategy_file}"}, ensure_ascii=False))
        return 1
    try:
        opt_cfg = json.loads(args.optimize_params)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "error": f"optimize-params JSON 解析失败: {e}"}, ensure_ascii=False))
        return 1
    target = opt_cfg.get("target", "sharpe_ratio")
    param_ranges = opt_cfg.get("params", {})
    if not param_ranges:
        print(json.dumps({"status": "error", "error": "params 为空，需指定至少一个参数范围 {\"name\": [start, end, step]}"}, ensure_ascii=False))
        return 1
    vnpy_qmt_path = PROJECT_ROOT / "vnpy_qmt"
    for p in [str(vnpy_qmt_path), str(STRATEGIES_DIR), str(strategy_file.parent)]:
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import importlib
        mod = importlib.import_module(strategy_file.stem)
        cls_name = args.strategy_class
        if not hasattr(mod, cls_name):
            low = cls_name.lower()
            hit = [n for n in dir(mod) if n.lower() == low]
            cls_name = hit[0] if hit else cls_name
        strategy_cls = getattr(mod, cls_name)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"策略导入失败: {e}"}, ensure_ascii=False))
        return 1
    try:
        from vnpy_ctastrategy.backtesting import BacktestingEngine
        from vnpy.trader.optimize import OptimizationSetting
        from vnpy.trader.constant import Interval
        from vnpy.trader.setting import SETTINGS
        qgdata_token = os.getenv("QGDATA_TOKEN", "") or resolve_qgdata_token("")
        if qgdata_token:
            SETTINGS["datafeed.name"] = "qg"
            SETTINGS["datafeed.password"] = qgdata_token
        vt_symbol = args.symbols.split(",")[0].strip()
        interval = getattr(Interval, args.interval)
        start_dt = datetime.strptime(args.start, "%Y%m%d")
        end_dt = datetime.strptime(args.end, "%Y%m%d")
        engine = BacktestingEngine()
        engine.set_parameters(vt_symbol=vt_symbol, interval=interval, start=start_dt, end=end_dt,
            rate=args.rate, slippage=args.slippage, size=args.size, pricetick=args.pricetick, capital=args.capital)
        engine.add_strategy(strategy_cls, {})
        engine.load_data()
        bar_count = len(getattr(engine, "history_data", []) or [])
        if bar_count == 0:
            print(json.dumps({"status": "error", "error": "数据库无缓存数据，请先运行一次回测以下载并缓存行情数据"}, ensure_ascii=False))
            return 1
        setting = OptimizationSetting()
        setting.set_target(target)
        for name, rng in param_ranges.items():
            setting.add_parameter(name, rng[0], rng[1], rng[2])
        total_combinations = len(setting.generate_settings())
        use_ga = opt_cfg.get("algorithm", "bf") == "ga"
        results = engine.run_ga_optimization(setting, output=False) if use_ga else engine.run_optimization(setting, output=False)
        top_n = min(args.top_n, len(results))
        formatted = []
        for setting_dict, target_val, stats in results[:top_n]:
            key_stats = {}
            for k in ["total_return", "annual_return", "max_ddpercent", "sharpe_ratio", "total_trade_count", "winning_rate"]:
                v = stats.get(k)
                if v is not None:
                    key_stats[k] = round(float(v), 4) if isinstance(v, float) else v
            formatted.append({"params": setting_dict, target: round(float(target_val), 6) if target_val else 0, "stats": key_stats})
        output = {"status": "completed", "target_metric": target, "algorithm": "ga" if use_ga else "bf",
            "total_combinations": total_combinations, "bar_count": bar_count, "top_n": top_n,
            "results": formatted, "best": formatted[0] if formatted else None}
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-500:]}, ensure_ascii=False))
        return 1


def cmd_qmt_check(_args: argparse.Namespace) -> int:
    """检测 QMT 模拟/实盘环境可用性，输出 JSON"""
    result: Dict[str, Any] = {"xtquant": False, "qmt_path": "", "qmt_path_ok": False, "account_id": "", "ready": False, "hint": ""}
    _orig_stdout = sys.stdout
    sys.stdout = io.StringIO()  # xtquant 导入时会打印文档地址，抑制以保持 JSON 输出干净
    try:
        import xtquant  # type: ignore  # noqa: F401
        result["xtquant"] = True
    except ImportError:
        pass
    finally:
        sys.stdout = _orig_stdout
    qmt_path = os.getenv("QMT_PATH", "")
    result["qmt_path"] = qmt_path
    if qmt_path:
        result["qmt_path_ok"] = (Path(qmt_path) / "userdata_mini").is_dir()
    account_id = os.getenv("QMT_ACCOUNT_ID", "")
    result["account_id"] = ("***" + account_id[-4:]) if len(account_id) > 4 else ("已配置" if account_id else "")
    result["ready"] = result["xtquant"] and result["qmt_path_ok"] and bool(account_id)
    if result["ready"]:
        result["hint"] = "QMT 环境就绪，可进行模拟/实盘交易"
    else:
        missing = []
        if not result["xtquant"]:
            missing.append("xtquant 库（需安装 miniQMT SDK）")
        if not qmt_path:
            missing.append("QMT_PATH 环境变量（指向 QMT 安装目录）")
        elif not result["qmt_path_ok"]:
            missing.append(f"QMT_PATH={qmt_path} 下未找到 userdata_mini 目录，请确认 QMT 已安装且路径正确")
        if not account_id:
            missing.append("QMT_ACCOUNT_ID 环境变量")
        result["hint"] = "缺少: " + "; ".join(missing)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "submit":
        return cmd_submit(args)
    if args.cmd == "worker":
        return cmd_worker(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "config-doctor":
        return cmd_config_doctor(args)
    if args.cmd == "qmt-check":
        return cmd_qmt_check(args)
    if args.cmd == "optimize":
        return cmd_optimize(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
