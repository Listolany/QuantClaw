#!/usr/bin/env python3
"""Production orchestration pipeline for strategy generation/backtesting."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from data_capability_guard import evaluate_requirement

PROJECT_ROOT = Path(os.getenv("QMT_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
RUNS_DIR = BACKTESTS_DIR / "orchestrator_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PYTHON_BIN = os.getenv("PYTHON_BIN", sys.executable or "python3")
MONITOR_SERVER = BACKTESTS_DIR / "monitor_server.py"
BACKTEST_RUNNER = BACKTESTS_DIR / "backtest_runner.py"
STATE_VERSION = 1
MONITOR_BIND_HOST = os.getenv("ORCH_MONITOR_BIND_HOST", "0.0.0.0")


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


def parse_requirement(requirement: str, symbols_override: Optional[str], token: str = "") -> Dict[str, Any]:
    txt = requirement.strip()
    symbol_matches = re.findall(r"\b(\d{6}\.(?:SZSE|SSE|SZ|SH|SS)|\d{6})\b", txt, flags=re.IGNORECASE)
    symbols = [normalize_symbol(s) for s in symbol_matches]
    if symbols_override:
        symbols = [normalize_symbol(s) for s in symbols_override.split(",") if s.strip()]
    if not symbols:
        symbols = resolve_symbols_by_name(txt, token) or ["000001.SZSE"]

    windows = [int(m.group(1)) for m in re.finditer(r"(\d+)\s*日", txt)]
    if len(windows) >= 2:
        fast_window, slow_window = sorted(windows[:2])
    elif len(windows) == 1:
        fast_window, slow_window = max(5, windows[0] // 2), windows[0]
    else:
        fast_window, slow_window = 5, 10

    interval = "MINUTE" if ("分钟" in txt or "min" in txt.lower()) else "DAILY"
    direction = "bearish" if any(k in txt for k in ["下穿", "死叉"]) else "bullish"

    return {
        "symbols": symbols,
        "fast_window": fast_window,
        "slow_window": slow_window,
        "interval": interval,
        "direction": direction,
    }


def pick_free_port(start: int = 8765, end: int = 8999, candidates: Optional[list[int]] = None) -> int:
    if candidates:
        for port in candidates:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    return port
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free monitor port available")


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


def strategy_source(class_name: str, fast: int, slow: int, author: str, direction: str) -> str:
    return f'''"""Auto-generated MA cross strategy."""\nfrom vnpy_ctastrategy import CtaTemplate\nfrom vnpy_ctastrategy.base import StopOrder\nfrom vnpy.trader.object import BarData, TradeData, OrderData\nfrom vnpy.trader.utility import ArrayManager\n\n\nclass {class_name}(CtaTemplate):\n    author = "{author}"\n    fast_window = {fast}\n    slow_window = {slow}\n    fixed_size = 100\n    direction_hint = "{direction}"\n\n    parameters = ["fast_window", "slow_window", "fixed_size", "direction_hint"]\n    variables = ["fast_ma", "slow_ma"]\n\n    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):\n        super().__init__(cta_engine, strategy_name, vt_symbol, setting)\n        self.am = ArrayManager(size=self.slow_window + 5)\n        self.fast_ma = 0.0\n        self.slow_ma = 0.0\n        self.prev_fast = 0.0\n        self.prev_slow = 0.0\n\n    def on_init(self):\n        self.load_bar(self.slow_window + 20)\n\n    def on_start(self):\n        pass\n\n    def on_stop(self):\n        pass\n\n    def on_bar(self, bar: BarData):\n        self.am.update_bar(bar)\n        if not self.am.inited:\n            return\n\n        self.cancel_all()\n        self.prev_fast = self.fast_ma\n        self.prev_slow = self.slow_ma\n        self.fast_ma = self.am.sma(self.fast_window)\n        self.slow_ma = self.am.sma(self.slow_window)\n\n        cross_up = self.prev_fast <= self.prev_slow and self.fast_ma > self.slow_ma\n        cross_down = self.prev_fast >= self.prev_slow and self.fast_ma < self.slow_ma\n\n        if self.pos == 0 and cross_up:\n            # Use aggressive limit to emulate next-bar open fill in backtesting.\n            self.buy(bar.close_price * 1.10, self.fixed_size)\n        elif self.pos > 0 and cross_down:\n            # Use aggressive limit to emulate next-bar open fill in backtesting.\n            self.sell(bar.close_price * 0.90, abs(self.pos))\n\n        self.put_event()\n\n    def on_trade(self, trade: TradeData):\n        self.put_event()\n\n    def on_order(self, order: OrderData):\n        pass\n\n    def on_stop_order(self, stop_order: StopOrder):\n        pass\n'''


def wait_monitor_ready(base_url: str, timeout_sec: int = 20) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if monitor_get(base_url, "/api/health", timeout=1.5) is not None:
            return True
        time.sleep(0.5)
    return False


def cmd_submit(args: argparse.Namespace) -> int:
    ok, err = validate_monitor_public_base(args.monitor_public_base)
    if not ok:
        print(
            json.dumps(
                {
                    "status": "config_missing",
                    "error": err,
                    "next_action": "请先配置公网 MONITOR_PUBLIC_BASE（例如 http://<public-ip-or-domain>）",
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
    port_start = int(os.getenv("ORCH_MONITOR_PORT_START", str(args.monitor_port_start)))
    port_end = int(os.getenv("ORCH_MONITOR_PORT_END", str(args.monitor_port_end)))
    raw_candidates = args.monitor_port_candidates or os.getenv("ORCH_MONITOR_PORT_CANDIDATES", "")
    candidate_ports: list[int] = []
    if raw_candidates:
        for token in raw_candidates.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                candidate_ports.append(int(token))
            except ValueError:
                continue
    monitor_port = args.monitor_port or pick_free_port(port_start, port_end, candidate_ports)
    monitor_base = f"http://127.0.0.1:{monitor_port}"
    monitor_url = f"{args.monitor_public_base.rstrip('/')}:{monitor_port}/runs/{run_id}"
    monitor_url_local = f"http://127.0.0.1:{monitor_port}/runs/{run_id}"
    public_reachable = False
    public_probe_error = "probe_pending"
    payload = {
        "requirement": args.requirement,
        "parsed": parsed,
        "capability_check": cap,
        "monitor_port": monitor_port,
        "monitor_base": monitor_base,
        "monitor_url": monitor_url,
        "monitor_url_local": monitor_url_local,
        "monitor_public_reachable": public_reachable,
        "monitor_public_probe_error": public_probe_error,
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

    public_reachable, public_probe_error = probe_monitor_url(monitor_url, timeout=1.5)
    payload["monitor_public_reachable"] = public_reachable
    payload["monitor_public_probe_error"] = public_probe_error
    state["payload"] = payload
    store.save(state)

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
                "monitor_public_reachable": public_reachable,
                "monitor_public_probe_error": public_probe_error,
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

    try:
        monitor_step(monitor_base, step="2", status="running", title="策略生成", msg="正在生成策略代码", run_id=run_id)
        module_name = f"auto_ma_{run_id}".lower()
        class_name = "AutoMaCrossStrategy"
        strategy_file = STRATEGIES_DIR / f"{module_name}.py"
        source = strategy_source(class_name, parsed["fast_window"], parsed["slow_window"], "quant-strategy-assistant", parsed["direction"])
        strategy_file.write_text(source, encoding="utf-8")
        subprocess.run([payload["python_bin"], "-m", "py_compile", str(strategy_file)], check=True, cwd=str(PROJECT_ROOT))
        monitor_post(
            monitor_base,
            "/api/code",
            {"filename": strategy_file.name, "content": source},
        )
        monitor_step(monitor_base, step="2", status="success", title="策略生成", msg=f"策略已生成: {strategy_file.name}", run_id=run_id)
        monitor_step(monitor_base, step="3", status="success", title="策略代码", msg=f"策略已生成并推送: {strategy_file.name}", run_id=run_id)
        state["artifacts"]["strategy_file"] = str(strategy_file)
        store.mark_step(state, "strategy_generation", "success", strategy_file.name)

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
            "cta",
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
        proc = start_process(cmd, run_log_path, env={**os.environ, "QMT_PROJECT_ROOT": str(PROJECT_ROOT)})
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
            monitor_step(monitor_base, step="5", status="success", title="结果展示", msg="回测完成，结果已生成", run_id=run_id)
            store.mark_step(state, "result", "success", str(summary_path))
        else:
            store.mark_step(state, "result", "running", "summary pending")

        state["status"] = "completed"
        store.save(state)
        return 0
    except Exception as exc:
        state["status"] = "failed"
        store.append_error(state, str(exc))
        monitor_step(monitor_base, step="9", status="failed", title="执行失败", msg=str(exc), run_id=run_id)
        store.save(state)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    state = RunStore(args.run_id).load()
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
        default=os.getenv("ORCH_MONITOR_PORT_CANDIDATES", "8761,8767"),
        help="Preferred monitor ports CSV, e.g. 8761,8767",
    )
    submit.add_argument("--monitor-port-start", type=int, default=8761, help="Monitor port range start")
    submit.add_argument("--monitor-port-end", type=int, default=8999, help="Monitor port range end")
    submit.add_argument("--monitor-public-base", default=os.getenv("MONITOR_PUBLIC_BASE", ""))
    submit.add_argument("--python-bin", default=DEFAULT_PYTHON_BIN)
    submit.add_argument("--token", default="")
    submit.add_argument("--start", default="")
    submit.add_argument("--end", default="")
    submit.add_argument("--interval", default="")
    submit.add_argument("--capital", type=float, default=100000)
    submit.add_argument("--rate", type=float, default=0.0003)
    submit.add_argument("--slippage", type=float, default=0.01)
    submit.add_argument("--size", type=float, default=1)
    submit.add_argument("--pricetick", type=float, default=0.01)
    submit.add_argument("--title", default="")
    submit.add_argument("--timeout-sec", type=int, default=int(os.getenv("ORCH_BACKTEST_TIMEOUT_SEC", "1200")))

    worker = sub.add_parser("worker", help="Internal worker command")
    worker.add_argument("--run-id", required=True)

    status = sub.add_parser("status", help="Read run state")
    status.add_argument("--run-id", required=True)

    ls_cmd = sub.add_parser("list", help="List recent runs")
    ls_cmd.add_argument("--limit", type=int, default=20)

    return parser


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
    return 1


if __name__ == "__main__":
    sys.exit(main())
