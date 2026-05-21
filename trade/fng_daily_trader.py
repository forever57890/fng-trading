#!/usr/bin/env python3
"""
Fear & Greed daily live trader (fng_trading.trade).

Runs once per invocation:
  1) Fetch latest Fear & Greed index and evaluate today's signal
  2) Close existing position: pre-limit → IOC → MARKET
  3) If signal says trade, pre-limit → IOC open then TP/SL on filled qty

From repo root:
  python -m fng_trading.trade.fng_daily_trader

Cron (UTC 00:00): see ``fng_trading/trade/run_fng_daily_cron.sh``.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from fng_trading.env_loader import load_fng_env

load_fng_env()

from fng_trading.core.data_fetch import fetch_binance_futures_klines, fetch_fear_greed_chart
from fng_trading.core.fng_signal import evaluate_latest_signal, evaluate_signal_on_date, signal_to_dict
from fng_trading.trade.binance_futures_trader import BinanceFuturesTrader
from fng_trading.trade.run_logging import (
    OPENED_STATUSES,
    build_config_snapshot,
    build_state_account_snapshot,
    capture_account_snapshot,
    enrich_run_record,
    format_run_log_block,
    print_run_output,
)
from fng_trading.trade.runtime_io import (
    ensure_runtime_dir,
    safe_append_log,
    safe_read_json,
    safe_write_json,
)

_TRADE_ROOT = Path(__file__).resolve().parent

# ---------- configurable parameters ----------
SYMBOL = os.getenv("FNG_SYMBOL", "BTCUSDT")
INTERVAL = "1d"
CONVERT_ID = int(os.getenv("FNG_CONVERT_ID", "2781"))
USE_MA_TP = os.getenv("FNG_USE_MA_TP", "1") == "1"
MA_DAYS = int(os.getenv("FNG_MA_DAYS", "90"))
DRY_RUN = os.getenv("FNG_DRY_RUN", "1") == "1"
ORDER_QTY_OVERRIDE = os.getenv("FNG_ORDER_QTY")  # optional, e.g. "0.01"
LOOKBACK_DAYS = int(os.getenv("FNG_LOOKBACK_DAYS", "120"))
SIGNAL_DAY_OVERRIDE = os.getenv("FNG_SIGNAL_DAY")  # e.g. "2026-05-15" for backtest
IGNORE_STATE = os.getenv("FNG_IGNORE_STATE", "0") == "1"
RUNTIME_DIR = Path(os.getenv("FNG_RUNTIME_DIR", str(_TRADE_ROOT / "runtime")))
STATE_FILE = RUNTIME_DIR / "fng_daily_state.json"
LOG_FILE = RUNTIME_DIR / "fng_daily_runs.log"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_state() -> dict:
    return safe_read_json(STATE_FILE)


def save_state(state: dict) -> None:
    safe_write_json(STATE_FILE, state)


def append_run_log(record: dict) -> None:
    safe_append_log(LOG_FILE, format_run_log_block(record))


def log_fatal_error(exc: Exception) -> None:
    """Persist and print a fatal run error (best-effort)."""
    err: Dict[str, Any] = {
        "run_at": utc_now().isoformat(),
        "action": "ERROR",
        "error": str(exc),
        "config": build_config_snapshot(),
    }
    try:
        ensure_runtime_dir(RUNTIME_DIR)
        trader = try_create_trader()
        err["account_at_start"] = capture_account_snapshot(
            trader, SYMBOL, state=load_state(), phase="error"
        )
        enrich_run_record(err)
        append_run_log(err)
        print_run_output(err)
    except Exception as log_exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        print(f"Failed to write run log: {log_exc}", file=sys.stderr)


def _state_snapshot(state: dict) -> dict:
    return {
        "last_signal_day": state.get("last_signal_day"),
        "last_run_at": state.get("last_run_at"),
        "last_action": state.get("last_action"),
        "last_side": state.get("last_side"),
        "open_position": state.get("open_position"),
        "last_close": state.get("last_close"),
    }


def fetch_recent_fear_greed(days: int = LOOKBACK_DAYS) -> list:
    end = int(utc_now().timestamp())
    start = int((utc_now() - timedelta(days=days)).timestamp())
    payload = fetch_fear_greed_chart(start, end, CONVERT_ID)
    return payload["data"]["dataList"]


def fetch_ma_klines(days: int = MA_DAYS + 10, as_of: Optional[datetime] = None) -> pd.DataFrame:
    as_of = as_of or utc_now()
    end_ms = int((as_of + timedelta(days=1)).timestamp() * 1000)
    start_ms = int((as_of - timedelta(days=days)).timestamp() * 1000)
    return fetch_binance_futures_klines(SYMBOL, INTERVAL, start_ms, end_ms)


def already_ran_today(state: dict, signal_day: str) -> bool:
    return state.get("last_signal_day") == signal_day


def resolve_order_qty(signal_qty: float) -> float:
    if ORDER_QTY_OVERRIDE:
        return float(ORDER_QTY_OVERRIDE)
    return float(signal_qty)


def _has_binance_keys() -> bool:
    return bool(os.getenv("bn_api_key") and os.getenv("bn_api_secret"))


def try_create_trader() -> Optional[BinanceFuturesTrader]:
    if not _has_binance_keys():
        return None
    return BinanceFuturesTrader()


def finalize_run(
    result: dict,
    state_after: Optional[dict] = None,
    *,
    print_output: bool = True,
) -> dict:
    if state_after is not None:
        result["state_after"] = _state_snapshot(state_after)
    if "account_at_end" not in result:
        if result.get("account_after_trade"):
            result["account_at_end"] = result["account_after_trade"]
        elif result.get("account_after_close"):
            result["account_at_end"] = result["account_after_close"]
        else:
            result["account_at_end"] = result.get("account_at_start")
    enrich_run_record(result)
    append_run_log(result)
    if print_output:
        print_run_output(result)
    return result


def close_existing_positions(
    state: dict,
    trader: Optional[BinanceFuturesTrader] = None,
) -> dict:
    """
    Daily normal exit before today's signal.
    Pre-limit → IOC @ opponent 1st level → MARKET remainder.
    """
    open_position = state.get("open_position")

    if DRY_RUN and not _has_binance_keys():
        positions_before = []
        if open_position:
            qty = float(open_position.get("quantity") or 0)
            side = open_position.get("side")
            amt = qty if side == "LONG" else -qty
            positions_before.append(
                {
                    "symbol": SYMBOL,
                    "position_side": side,
                    "position_amt": amt,
                    "source": "state_file",
                }
            )
        if not open_position:
            return {
                "status": "NO_POSITION_TO_CLOSE",
                "symbol": SYMBOL,
                "dry_run": True,
                "close_mode": "PRE_LIMIT_THEN_IOC_THEN_MARKET",
                "positions_before": [],
                "positions_after": [],
                "note": "No tracked open_position in state",
            }
        return {
            "status": "DRY_RUN_CLOSE",
            "dry_run": True,
            "symbol": SYMBOL,
            "close_mode": "PRE_LIMIT_THEN_IOC_THEN_MARKET",
            "positions_before": positions_before,
            "positions_after": [],
            "closed": [
                {
                    **open_position,
                    "symbol": SYMBOL,
                    "exit_reason": "NORMAL_EXIT",
                    "note": "Simulated close (no API keys)",
                }
            ],
        }

    active = trader or BinanceFuturesTrader()
    return active.close_open_positions_at_market(SYMBOL, dry_run=DRY_RUN)


def _apply_close_to_state(new_state: dict, close_result: dict) -> None:
    status = close_result.get("status")
    if status in {"CLOSED", "DRY_RUN_CLOSE"}:
        new_state["last_action"] = "CLOSED_NORMAL_EXIT"
        new_state["last_close"] = close_result
        new_state.pop("open_position", None)
        new_state.pop("last_side", None)
    elif status == "NO_POSITION_TO_CLOSE":
        new_state["last_action"] = "NO_POSITION_TO_CLOSE"


def run_once() -> dict:
    ensure_runtime_dir(RUNTIME_DIR)
    run_at = utc_now().isoformat()
    trader = try_create_trader()
    state = load_state()

    result: Dict[str, Any] = {
        "run_at": run_at,
        "signal_day_override": SIGNAL_DAY_OVERRIDE,
        "ignore_state": IGNORE_STATE,
        "dry_run": DRY_RUN,
        "symbol": SYMBOL,
        "config": build_config_snapshot(),
        "state_before": _state_snapshot(state),
        "action": "NO_TRADE",
    }

    result["account_at_start"] = capture_account_snapshot(
        trader, SYMBOL, state=state, phase="start"
    )

    data_list = fetch_recent_fear_greed()

    if SIGNAL_DAY_OVERRIDE:
        signal = evaluate_signal_on_date(
            data_list,
            SIGNAL_DAY_OVERRIDE,
            kline_df=None,
            use_ma_tp=False,
            ma_days=MA_DAYS,
        )
        if USE_MA_TP:
            kline_df = fetch_ma_klines(as_of=signal.timestamp.to_pydatetime())
            signal = evaluate_signal_on_date(
                data_list,
                SIGNAL_DAY_OVERRIDE,
                kline_df=kline_df,
                use_ma_tp=True,
                ma_days=MA_DAYS,
            )
    else:
        kline_df = fetch_ma_klines() if USE_MA_TP else None
        signal = evaluate_latest_signal(
            data_list,
            kline_df=kline_df,
            use_ma_tp=USE_MA_TP,
            ma_days=MA_DAYS,
        )

    signal_day = signal.timestamp.strftime("%Y-%m-%d")
    result["signal_day"] = signal_day
    result["signal"] = signal_to_dict(signal)

    if not IGNORE_STATE and already_ran_today(state, signal_day):
        result["action"] = "SKIPPED_ALREADY_RAN"
        return finalize_run(result)

    close_result = close_existing_positions(state, trader=trader)
    result["close"] = close_result

    mark_for_snap = None
    if trader:
        try:
            mark_for_snap = trader.get_mark_price(SYMBOL)
        except Exception:
            pass
    result["account_after_close"] = capture_account_snapshot(
        trader,
        SYMBOL,
        state=_cleared_state_for_snapshot(state, close_result),
        mark_price=mark_for_snap or close_result.get("mark_price"),
        phase="after_close",
    )

    new_state = {
        "last_signal_day": signal_day,
        "last_run_at": run_at,
    }
    _apply_close_to_state(new_state, close_result)

    if not signal.should_trade:
        result["action"] = "NO_SIGNAL"
        if not IGNORE_STATE:
            save_state(new_state)
        return finalize_run(result, state_after=new_state if not IGNORE_STATE else None)

    qty = resolve_order_qty(signal.qty_btc)

    if DRY_RUN and not _has_binance_keys():
        mark_price = float(signal.btc_price)
        tp_price = signal.take_profit_price
        sl_price = signal.stop_loss_price
        trade_result = {
            "status": "DRY_RUN",
            "symbol": SYMBOL,
            "side": signal.side,
            "quantity": qty,
            "target_quantity": qty,
            "mark_price_used": mark_price,
            "take_profit_price": tp_price,
            "stop_loss_price": sl_price,
            "open_mode": "PRE_LIMIT_THEN_IOC_THEN_MARKET",
            "dry_run": True,
            "note": "No API keys; skipped Binance calls",
            "planned_brackets": {
                "take_profit_price": tp_price,
                "stop_loss_price": sl_price,
            },
        }
        result["mark_price"] = mark_price
        result["order_qty"] = qty
        result["planned_entry"] = {
            "side": signal.side,
            "quantity": qty,
            "mark_price": mark_price,
            "take_profit_price": tp_price,
            "stop_loss_price": sl_price,
        }
        result["trade"] = trade_result
        result["action"] = trade_result["status"]
        result["account_after_trade"] = build_state_account_snapshot(
            {
                **new_state,
                "open_position": {
                    "side": signal.side,
                    "quantity": qty,
                    "opened_signal_day": signal_day,
                },
            },
            SYMBOL,
            mark_price=mark_price,
        )
        if not IGNORE_STATE:
            new_state["open_position"] = {
                "side": signal.side,
                "quantity": qty,
                "opened_signal_day": signal_day,
            }
            new_state["last_action"] = "DRY_RUN_OPEN"
            new_state["last_side"] = signal.side
            save_state(new_state)
        return finalize_run(result, state_after=new_state if not IGNORE_STATE else None)

    active_trader = trader or BinanceFuturesTrader()
    mark_price = active_trader.get_mark_price(SYMBOL)

    if signal.side == "LONG":
        tp_price = mark_price * (1 + signal.take_profit_rate)
        sl_price = mark_price * (1 - signal.stop_loss_rate)
    else:
        tp_price = mark_price * (1 - signal.take_profit_rate)
        sl_price = mark_price * (1 + signal.stop_loss_rate)

    result["planned_entry"] = {
        "side": signal.side,
        "quantity": qty,
        "mark_price": mark_price,
        "take_profit_price": tp_price,
        "stop_loss_price": sl_price,
        "take_profit_rate": signal.take_profit_rate,
        "stop_loss_rate": signal.stop_loss_rate,
    }

    trade_result = active_trader.open_position_with_brackets(
        symbol=SYMBOL,
        side=signal.side,
        quantity=qty,
        take_profit_price=tp_price,
        stop_loss_price=sl_price,
        dry_run=DRY_RUN,
    )

    result["mark_price"] = mark_price
    result["order_qty"] = qty
    result["trade"] = trade_result
    result["action"] = trade_result.get("status", "UNKNOWN")

    result["account_after_trade"] = capture_account_snapshot(
        active_trader,
        SYMBOL,
        phase="after_trade",
    )

    if not IGNORE_STATE:
        new_state["last_side"] = signal.side
        status = trade_result.get("status")
        if status in OPENED_STATUSES or str(status).startswith("DRY_RUN"):
            filled = trade_result.get("filled_quantity") or qty
            new_state["last_action"] = status
            new_state["open_position"] = {
                "side": signal.side,
                "quantity": filled,
                "opened_signal_day": signal_day,
            }
        else:
            new_state["last_action"] = result["action"]
        save_state(new_state)

    return finalize_run(result, state_after=new_state if not IGNORE_STATE else None)


def _cleared_state_for_snapshot(state: dict, close_result: dict) -> dict:
    """After close, state file snapshot should not show closed position."""
    sim = dict(state)
    if close_result.get("status") in {"CLOSED", "DRY_RUN_CLOSE"}:
        sim.pop("open_position", None)
    return sim


def seconds_until_next_utc_run() -> int:
    now = utc_now()
    if now.hour == 0 and now.minute < 5:
        return 2
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=2, microsecond=0
    )
    return max(5, int((next_midnight - now).total_seconds()))


def run_scheduler_loop() -> None:
    """Blocking loop: execute at UTC 00:00 every day."""
    print("FNG scheduler started. Waiting for UTC 00:00 ...")
    while True:
        sleep_seconds = seconds_until_next_utc_run()
        next_run = utc_now() + timedelta(seconds=sleep_seconds)
        print(f"Next run around {next_run.isoformat()} (sleep {sleep_seconds}s)")
        time.sleep(sleep_seconds)
        try:
            run_once()
        except Exception as exc:
            log_fatal_error(exc)


def main() -> int:
    mode = os.getenv("FNG_RUN_MODE", "once")  # once | schedule
    try:
        if mode == "schedule":
            run_scheduler_loop()
            return 0
        run_once()
        return 0
    except Exception as exc:
        log_fatal_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
