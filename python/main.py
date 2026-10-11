import json
import os
import threading
import time
from collections import deque

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Bridge, Logger

import diagnostics
from cell import Cell

log = Logger("solar_cells_optim")
ui = WebUI()

RL_OHM = 10.0
ADC_MAX = 16383.0  # 14 bit ADC
ADC_VREF = 3.3
HISTORY_LEN = 300  # ~15 s at the sketch's 20 Hz push rate

# Optimizer: exhaustive search over valid relay masks, held with hysteresis.
# RL is the only load, so maximizing current also maximizes power (P = I^2 * RL).
OPTIMIZE_SETTLE_S = 0.3
OPTIMIZE_SAMPLE_S = 0.3
OPTIMIZE_SEARCH_PERIOD_S = 8.0  # re-search at least this often
OPTIMIZE_DROP_RATIO = 0.85  # held current below (best * this) triggers an early re-search

DIAG_PATH = "data/diagnostics.json"  # per-cell baseline/status/events; survives an App restart

lock = threading.Lock()
state = {
    "cell_count": None,
    "cells": [],  # [{"bypassed": bool}, ...], length == cell_count
    "diag_cells": [],  # [Cell, ...], same length; deduced state, auto mode only
    "history": deque(maxlen=HISTORY_LEN),
    "last_error": "",
    "mcu_ready": False,
    "mode": "manual",  # "manual" or "optimization"
    "last_sample_wall_time": None,  # frame[0] is MCU millis(), not wall-clock
    "optimizer": None,
}


def _new_optimizer_state():
    return {
        "best_mask": None,
        "best_ma": None,
        "last_search_t": 0.0,
        "searching": False,
        "status": "idle",
    }


state["optimizer"] = _new_optimizer_state()


def on_ready(_value):
    with lock:
        state["mcu_ready"] = True


def on_sample(frame):
    try:
        t_ms, raw, mask = (int(x) for x in frame)
    except Exception as e:
        with lock:
            state["last_error"] = f"{type(e).__name__}: {e}"
        return

    volts = None if raw < 0 else raw / ADC_MAX * ADC_VREF
    current_ma = None if volts is None else volts / RL_OHM * 1000.0
    power_mw = None if volts is None else current_ma * volts

    with lock:
        for i, cell in enumerate(state["cells"]):
            cell["bypassed"] = bool(mask & (1 << i))
        state["history"].append({
            "t": t_ms,
            "raw": raw,
            "v": volts,
            "ma": current_ma,
            "mw": power_mw,
            "mask": mask
        })
        state["last_sample_wall_time"] = time.time()


Bridge.provide("ready", on_ready)
Bridge.provide("sample", on_sample)


def _load_diagnostics(diag_cells):
    try:
        with open(DIAG_PATH) as f:
            saved = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for c in diag_cells:
        if c.id in saved:
            c.load_persisted(saved[c.id])


def _save_diagnostics():
    try:
        os.makedirs(os.path.dirname(DIAG_PATH), exist_ok=True)
        with lock:
            saved = {c.id: c.to_persist() for c in state["diag_cells"]}
        with open(DIAG_PATH, "w") as f:
            json.dump(saved, f)
    except OSError as e:
        with lock:
            state["last_error"] = f"{type(e).__name__}: {e}"


def _discover_cell_count():
    # Right after boot the sketch's Bridge.provide calls may not be registered
    # yet (RpcError code 2); that's expected, not an error.
    try:
        n = int(Bridge.call("get_cell_count", timeout=0.5))
    except Exception as e:
        with lock:
            state["last_error"] = f"{type(e).__name__}: {e}"
        return False
    with lock:
        state["cell_count"] = n
        state["cells"] = [{"bypassed": False} for _ in range(n)]
        state["diag_cells"] = [Cell(i, chr(ord("A") + i)) for i in range(n)]
        diag_cells = state["diag_cells"]
    _load_diagnostics(diag_cells)
    log.info(f"sketch reports {n} cell(s)")
    return True


def _apply_mask(mask, n):
    for i in range(n):
        want_bypassed = bool(mask & (1 << i))
        with lock:
            have_bypassed = state["cells"][i]["bypassed"]
        if have_bypassed == want_bypassed:
            continue
        try:
            Bridge.call("set_relay", i, 1 if want_bypassed else 0, timeout=1.0)
        except Exception as e:
            with lock:
                state["last_error"] = f"{type(e).__name__}: {e}"


def _measure_mask(mask, n):
    _apply_mask(mask, n)
    time.sleep(OPTIMIZE_SETTLE_S)
    time.sleep(OPTIMIZE_SAMPLE_S)
    want_samples = int(
        OPTIMIZE_SAMPLE_S * 1000 / 50) + 2  # sketch pushes ~every 50 ms
    with lock:
        recent = list(state["history"])[-want_samples:]
    values = [
        h["ma"] for h in recent if h["mask"] == mask and h["ma"] is not None
    ]
    return (sum(values) / len(values)) if values else None


def _run_full_search(n):
    with lock:
        state["optimizer"]["searching"] = True
        state["optimizer"]["status"] = "searching..."
    full_mask = (1 << n) - 1
    best_mask, best_ma = None, -1.0
    for mask in range(0, full_mask):  # excludes the all-bypassed mask
        ma = _measure_mask(mask, n)
        if ma is not None and ma > best_ma:
            best_mask, best_ma = mask, ma
        if ma is not None:
            # mask == full_mask ^ (1 << i) means every cell but i is bypassed:
            # that reading is cell i's own current, isolated.
            for i in range(n):
                if mask == (full_mask ^ (1 << i)):
                    with lock:
                        state["diag_cells"][i].update(ma)
    with lock:
        diagnostics.analyze(state["diag_cells"])
    _save_diagnostics()
    if best_mask is not None:
        _apply_mask(best_mask,
                    n)  # end up holding the winner, not the last mask tried
        with lock:
            state["optimizer"]["best_mask"] = best_mask
            state["optimizer"]["best_ma"] = best_ma
            state["optimizer"]["last_search_t"] = time.time()
            state["optimizer"][
                "status"] = f"optimal mask=0b{best_mask:0{n}b} ({best_ma:.1f} mA)"
    with lock:
        state["optimizer"]["searching"] = False


def _run_optimizer_step():
    with lock:
        n = state["cell_count"]
        opt = dict(state["optimizer"])
    if not n:
        return

    now = time.time()
    need_search = opt["best_mask"] is None or (
        now - opt["last_search_t"]) >= OPTIMIZE_SEARCH_PERIOD_S

    if not need_search:
        with lock:
            recent = list(state["history"])[-5:]
        held = [
            h["ma"] for h in recent
            if h["mask"] == opt["best_mask"] and h["ma"] is not None
        ]
        if held:
            live_ma = sum(held) / len(held)
            with lock:
                state["optimizer"][
                    "status"] = f"holding mask=0b{opt['best_mask']:0{n}b} ({live_ma:.1f} mA)"
            if opt["best_ma"] and live_ma < opt[
                    "best_ma"] * OPTIMIZE_DROP_RATIO:
                need_search = True

    if need_search:
        _run_full_search(n)


def api_state() -> dict:
    with lock:
        wall_time = state["last_sample_wall_time"]
        latest = state["history"][-1] if state["history"] else None
        return {
            "cell_count":
            state["cell_count"],
            "cells":
            list(state["cells"]),
            "diagnostics":
            [c.to_dict() for c in state["diag_cells"]],
            "history":
            list(state["history"]),
            "latest":
            latest,
            "mode":
            state["mode"],
            "optimizer":
            dict(state["optimizer"]),
            "last_error":
            state["last_error"],
            "mcu_ready":
            state["mcu_ready"],
            "last_sample_age_s":
            None if wall_time is None else round(time.time() - wall_time, 1),
        }


ui.expose_api("GET", "/state", api_state)


def api_relay(index: int, bypassed: int) -> dict:
    with lock:
        mode = state["mode"]
    if mode != "manual":
        return {
            "ok":
            False,
            "error":
            "relay is under optimizer control, switch to manual mode first"
        }
    try:
        result = Bridge.call("set_relay", index, bypassed, timeout=1.0)
    except Exception as e:
        with lock:
            state["last_error"] = f"{type(e).__name__}: {e}"
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    if result == 1:
        return {"ok": True}
    if result == -1:
        return {"ok": False, "error": "invalid cell index"}
    return {"ok": False, "error": "refused: would leave no cell in the string"}


ui.expose_api("GET", "/relay", api_relay)


def api_mode(mode: str = "") -> dict:
    # Entering "optimization" always starts a fresh search, never trusts a
    # stale result from before the mode switch.
    if mode:
        if mode not in ("manual", "optimization"):
            return {
                "ok": False,
                "error": "mode must be 'manual' or 'optimization'"
            }
        with lock:
            if mode == "optimization" and state["mode"] != "optimization":
                state["optimizer"] = _new_optimizer_state()
            state["mode"] = mode
        log.info(f"mode -> {mode}")
    with lock:
        return {"ok": True, "mode": state["mode"]}


ui.expose_api("GET", "/mode", api_mode)


def loop():
    try:
        with lock:
            known = state["cell_count"] is not None
        if not known:
            _discover_cell_count()
            time.sleep(0.5)
            return
        with lock:
            mode = state["mode"]
        if mode == "optimization":
            _run_optimizer_step()
        time.sleep(0.2)
    except Exception as e:
        with lock:
            state["last_error"] = f"{type(e).__name__}: {e}"
        log.warning(f"loop: {type(e).__name__}: {e}")
        time.sleep(1.0)


App.run(user_loop=loop)
