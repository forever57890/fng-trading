"""
Structured + human-readable logging for fng_daily_trader runs.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fng_trading.trade.binance_futures_trader import BinanceFuturesTrader

OPENED_STATUSES = frozenset(
    {
        "OPENED",
        "OPENED_IOC",
        "OPENED_IOC_THEN_MARKET",
        "OPENED_PRE_LIMIT",
        "DRY_RUN_OPEN",
    }
)

CLOSED_STATUSES = frozenset(
    {
        "CLOSED",
        "CLOSED_IOC",
        "CLOSED_IOC_THEN_MARKET",
        "CLOSED_PRE_LIMIT",
        "DRY_RUN_CLOSE",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_config_snapshot() -> Dict[str, Any]:
    """Runtime parameters included in every run log."""
    return {
        "symbol": os.getenv("FNG_SYMBOL", "BTCUSDT"),
        "dry_run": os.getenv("FNG_DRY_RUN", "1") == "1",
        "order_qty_override": os.getenv("FNG_ORDER_QTY"),
        "use_ma_tp": os.getenv("FNG_USE_MA_TP", "1") == "1",
        "ma_days": int(os.getenv("FNG_MA_DAYS", "90")),
        "lookback_days": int(os.getenv("FNG_LOOKBACK_DAYS", "120")),
        "signal_day_override": os.getenv("FNG_SIGNAL_DAY"),
        "ignore_state": os.getenv("FNG_IGNORE_STATE", "0") == "1",
        "pre_ioc_limit_wait_ms": int(os.getenv("FNG_PRE_IOC_LIMIT_WAIT_MS", "2000")),
        "ioc_interval_ms": int(
            os.getenv(
                "FNG_IOC_INTERVAL_MS",
                os.getenv("FNG_CLOSE_IOC_INTERVAL_MS", "100"),
            )
        ),
        "ioc_max_attempts": int(
            os.getenv(
                "FNG_IOC_MAX_ATTEMPTS",
                os.getenv("FNG_CLOSE_IOC_MAX_ATTEMPTS", "100"),
            )
        ),
        "has_api_keys": bool(os.getenv("bn_api_key") and os.getenv("bn_api_secret")),
    }


def build_state_account_snapshot(
    state: dict,
    symbol: str,
    mark_price: Optional[float] = None,
) -> Dict[str, Any]:
    """When API keys are missing: infer position from state file only."""
    open_pos = state.get("open_position")
    positions: List[Dict[str, Any]] = []
    if open_pos:
        qty = float(open_pos.get("quantity") or 0)
        side = open_pos.get("side")
        amt = qty if side == "LONG" else -qty
        positions.append(
            {
                "symbol": symbol,
                "position_side": side,
                "position_amt": amt,
                "entry_price": None,
                "mark_price": mark_price,
                "unrealized_pnl": None,
                "leverage": None,
                "liquidation_price": None,
                "margin_type": None,
                "source": "state_file",
            }
        )
    return {
        "captured_at": utc_now_iso(),
        "source": "state_file",
        "mark_price": mark_price,
        "balance_usdt": {"found": False, "note": "No API keys; balance not fetched"},
        "positions": positions,
        "open_orders": [],
        "algo_open_orders": [],
        "tracked_open_position": open_pos,
        "last_action": state.get("last_action"),
        "last_signal_day": state.get("last_signal_day"),
    }


def capture_account_snapshot(
    trader: Optional[BinanceFuturesTrader],
    symbol: str,
    state: Optional[dict] = None,
    mark_price: Optional[float] = None,
    phase: str = "",
) -> Dict[str, Any]:
    """Live account from API, or state-file fallback."""
    if trader is not None:
        try:
            snap = trader.get_account_snapshot(symbol)
            if phase:
                snap["phase"] = phase
            return snap
        except Exception as exc:
            return {
                "captured_at": utc_now_iso(),
                "source": "api_error",
                "phase": phase,
                "symbol": symbol,
                "error": str(exc),
            }
    return build_state_account_snapshot(state or {}, symbol, mark_price)


def summarize_execution_leg(leg: dict) -> Dict[str, Any]:
    """Condensed view of one open/close execution leg (pre-limit → IOC → market)."""
    if not leg:
        return {}
    pre = leg.get("pre_limit") or {}
    ioc_attempts = leg.get("ioc_attempts") or []
    last_ioc = ioc_attempts[-1] if ioc_attempts else {}
    return {
        "mode": leg.get("mode"),
        "status": leg.get("status"),
        "position_side": leg.get("position_side"),
        "target_qty": leg.get("target_qty"),
        "initial_qty": leg.get("initial_qty"),
        "final_qty": leg.get("final_qty"),
        "execution_mode": leg.get("execution_mode"),
        "pre_ioc_limit_wait_ms": leg.get("pre_ioc_limit_wait_ms"),
        "pre_limit_filled_qty": leg.get("pre_limit_filled_qty", 0),
        "pre_limit": None
        if pre.get("skipped")
        else {
            "status": pre.get("status"),
            "pricing": pre.get("pricing", "passive_queue"),
            "wait_ms": pre.get("wait_ms"),
            "side": pre.get("side"),
            "price": pre.get("price"),
            "order_qty": pre.get("order_qty"),
            "filled_qty": pre.get("filled_qty"),
            "order_id": pre.get("order_id"),
        },
        "ioc_filled_qty": leg.get("ioc_filled_qty", 0),
        "ioc_attempt_count": len(ioc_attempts),
        "last_ioc_price": last_ioc.get("price"),
        "market_remainder_qty": leg.get("market_remainder_qty", 0),
        "market_order_id": (leg.get("market_order") or {}).get("orderId"),
    }


def summarize_signal(signal: dict) -> Dict[str, Any]:
    return {
        "signal_day": (signal.get("timestamp") or "")[:10],
        "score": signal.get("score"),
        "prev_score": signal.get("prev_score"),
        "score_diff": signal.get("score_diff"),
        "btc_price": signal.get("btc_price"),
        "side": signal.get("side"),
        "qty_btc": signal.get("qty_btc"),
        "position_type": signal.get("position_type"),
        "should_trade": signal.get("should_trade"),
        "take_profit_rate": signal.get("take_profit_rate"),
        "stop_loss_rate": signal.get("stop_loss_rate"),
        "take_profit_price": signal.get("take_profit_price"),
        "stop_loss_price": signal.get("stop_loss_price"),
        "ma_signal": signal.get("ma_signal"),
        "ma": signal.get("ma"),
    }


def summarize_close(close: Optional[dict]) -> Dict[str, Any]:
    if not close:
        return {}
    closed_legs = close.get("closed") or []
    return {
        "status": close.get("status"),
        "symbol": close.get("symbol"),
        "mark_price": close.get("mark_price"),
        "close_mode": close.get("close_mode"),
        "pre_ioc_limit_wait_ms": close.get("pre_ioc_limit_wait_ms"),
        "ioc_interval_ms": close.get("ioc_interval_ms"),
        "ioc_max_attempts": close.get("ioc_max_attempts"),
        "dry_run": close.get("dry_run"),
        "positions_before": close.get("positions_before"),
        "positions_after": close.get("positions_after"),
        "note": close.get("note"),
        "leg_count": len(closed_legs),
        "legs": [summarize_execution_leg(leg) for leg in closed_legs],
        "closed_sides": [
            leg.get("position_side")
            for leg in closed_legs
            if leg.get("position_side")
        ],
    }


def summarize_trade(trade: Optional[dict]) -> Dict[str, Any]:
    if not trade:
        return {}
    entry = trade.get("entry") or {}
    return {
        "status": trade.get("status"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "target_quantity": trade.get("target_quantity"),
        "filled_quantity": trade.get("filled_quantity"),
        "open_mode": trade.get("open_mode"),
        "take_profit_price": trade.get("take_profit_price"),
        "stop_loss_price": trade.get("stop_loss_price"),
        "planned_brackets": trade.get("planned_brackets"),
        "dry_run": trade.get("dry_run"),
        "note": trade.get("note"),
        "mark_price_used": trade.get("mark_price_used"),
        "entry": summarize_execution_leg(entry),
        "bracket_api": trade.get("bracket_api", "algo"),
        "take_profit_algo_id": (trade.get("take_profit_order") or {}).get("algoId"),
        "stop_loss_algo_id": (trade.get("stop_loss_order") or {}).get("algoId"),
        "open_orders_after": trade.get("open_orders_after"),
        "algo_open_orders_after": trade.get("algo_open_orders_after"),
    }


def _fmt_balance(bal: dict) -> str:
    if not bal or not bal.get("found"):
        return bal.get("note", "balance N/A") if bal else "balance N/A"
    return (
        f"wallet={bal.get('wallet_balance')} "
        f"avail={bal.get('available_balance')} "
        f"cross_un_pnl={bal.get('cross_un_pnl')}"
    )


def _fmt_positions(positions: List[dict]) -> str:
    if not positions:
        return "(flat)"
    parts = []
    for p in positions:
        parts.append(
            f"{p.get('position_side')} amt={p.get('position_amt')} "
            f"entry={p.get('entry_price')} uPnL={p.get('unrealized_pnl')}"
        )
    return "; ".join(parts)


def _fmt_orders(orders: List[dict]) -> str:
    if not orders:
        return "(none)"
    parts = []
    for o in orders:
        sp = o.get("stop_price") or o.get("price")
        parts.append(
            f"{o.get('type')} {o.get('side')}/{o.get('position_side')} "
            f"qty={o.get('orig_qty')} stop={sp}"
        )
    return "; ".join(parts)


def _fmt_algo_orders(orders: List[dict]) -> str:
    if not orders:
        return "(none)"
    parts = []
    for o in orders:
        parts.append(
            f"{o.get('order_type')} {o.get('side')}/{o.get('position_side')} "
            f"qty={o.get('quantity')} trigger={o.get('trigger_price')} "
            f"algo_id={o.get('algo_id')} status={o.get('algo_status')}"
        )
    return "; ".join(parts)


def build_action_detail(result: dict) -> Dict[str, Any]:
    """Per-action fields useful when scanning jsonl."""
    action = result.get("action", "")
    detail: Dict[str, Any] = {"action": action}

    if action == "SKIPPED_ALREADY_RAN":
        detail.update(
            {
                "reason": "last_signal_day matches today",
                "last_signal_day": (result.get("state_before") or {}).get(
                    "last_signal_day"
                ),
                "last_action": (result.get("state_before") or {}).get("last_action"),
            }
        )
    elif action == "NO_SIGNAL":
        detail["reason"] = "score_diff not in trade zone"
        detail["close"] = summarize_close(result.get("close"))
    elif str(action).startswith("DRY_RUN"):
        detail["trade"] = summarize_trade(result.get("trade"))
        detail["order_qty"] = result.get("order_qty")
        detail["mark_price"] = result.get("mark_price")
    elif action in OPENED_STATUSES or action in {
        "OPENED",
        "OPEN_INCOMPLETE",
        "OPENED_IOC",
        "OPENED_IOC_THEN_MARKET",
        "OPENED_PRE_LIMIT",
    }:
        detail["trade"] = summarize_trade(result.get("trade"))
        detail["order_qty"] = result.get("order_qty")
        detail["planned_entry"] = result.get("planned_entry")
    if result.get("close"):
        detail.setdefault("close", summarize_close(result.get("close")))
    if result.get("error"):
        detail["error"] = result.get("error")
    return detail


def build_run_summary_lines(result: dict) -> List[str]:
    """Human-readable lines for console / fng_cron.log."""
    lines = [
        "",
        "=" * 72,
        f"FNG Daily Run | {result.get('run_at')} | action={result.get('action')}",
        "=" * 72,
    ]

    cfg = result.get("config") or {}
    lines.append(
        f"Config: symbol={cfg.get('symbol')} dry_run={cfg.get('dry_run')} "
        f"qty_override={cfg.get('order_qty_override')} "
        f"pre_limit_ms={cfg.get('pre_ioc_limit_wait_ms')} "
        f"ioc={cfg.get('ioc_interval_ms')}ms×{cfg.get('ioc_max_attempts')}"
    )

    sig = summarize_signal(result.get("signal") or {})
    lines.append(
        f"Signal [{sig.get('signal_day')}]: score={sig.get('score')} "
        f"prev={sig.get('prev_score')} diff={sig.get('score_diff')} "
        f"should_trade={sig.get('should_trade')} side={sig.get('side')} "
        f"qty_btc={sig.get('qty_btc')} tp%={sig.get('take_profit_rate')} "
        f"sl%={sig.get('stop_loss_rate')}"
    )
    if sig.get("ma") is not None:
        lines.append(f"  MA: value={sig.get('ma')} ma_signal={sig.get('ma_signal')}")

    state_before = result.get("state_before") or {}
    if state_before:
        lines.append(
            f"State(before): last_day={state_before.get('last_signal_day')} "
            f"last_action={state_before.get('last_action')} "
            f"tracked={state_before.get('open_position')}"
        )

    for phase_key, label in (
        ("account_at_start", "Account@start"),
        ("account_after_close", "Account@after_close"),
        ("account_after_trade", "Account@after_trade"),
        ("account_at_end", "Account@end"),
    ):
        acc = result.get(phase_key)
        if not acc:
            continue
        mp = acc.get("mark_price")
        lines.append(f"{label}: mark={mp} | USDT {_fmt_balance(acc.get('balance_usdt') or {})}")
        lines.append(f"  Positions: {_fmt_positions(acc.get('positions') or [])}")
        oo = acc.get("open_orders")
        if oo is not None:
            lines.append(f"  Open orders: {_fmt_orders(oo)}")
        algo_oo = acc.get("algo_open_orders")
        if algo_oo is not None:
            lines.append(f"  Algo orders (TP/SL): {_fmt_algo_orders(algo_oo)}")

    close_sum = summarize_close(result.get("close"))
    if close_sum:
        lines.append(
            f"Close: status={close_sum.get('status')} legs={close_sum.get('leg_count')} "
            f"sides={close_sum.get('closed_sides')} mode={close_sum.get('close_mode')}"
        )
        for i, leg in enumerate(close_sum.get("legs") or [], 1):
            lines.append(
                f"  leg#{i} {leg.get('position_side')}: {leg.get('status')} "
                f"pre_fill={leg.get('pre_limit_filled_qty')} "
                f"ioc_fill={leg.get('ioc_filled_qty')} market={leg.get('market_remainder_qty')}"
            )

    trade_sum = summarize_trade(result.get("trade"))
    if trade_sum:
        lines.append(
            f"Open: status={trade_sum.get('status')} side={trade_sum.get('side')} "
            f"target={trade_sum.get('target_quantity')} filled={trade_sum.get('filled_quantity')}"
        )
        if trade_sum.get("take_profit_price"):
            lines.append(
                f"  Brackets: TP={trade_sum.get('take_profit_price')} "
                f"SL={trade_sum.get('stop_loss_price')} "
                f"tp_algo_id={trade_sum.get('take_profit_algo_id')} "
                f"sl_algo_id={trade_sum.get('stop_loss_algo_id')}"
            )
        entry = trade_sum.get("entry") or {}
        if entry:
            lines.append(
                f"  Entry leg: {entry.get('status')} pre={entry.get('pre_limit_filled_qty')} "
                f"ioc={entry.get('ioc_filled_qty')} market={entry.get('market_remainder_qty')}"
            )

    if result.get("order_qty") is not None:
        lines.append(
            f"Order: qty={result.get('order_qty')} mark={result.get('mark_price')} "
            f"planned_entry={result.get('planned_entry')}"
        )

    state_after = result.get("state_after")
    if state_after:
        lines.append(
            f"State(after): last_action={state_after.get('last_action')} "
            f"open_position={state_after.get('open_position')}"
        )

    ad = result.get("action_detail") or {}
    if ad.get("reason"):
        lines.append(f"Detail: {ad.get('reason')}")
    if result.get("error"):
        lines.append(f"ERROR: {result['error']}")

    lines.append("=" * 72)
    return lines


def enrich_run_record(result: dict) -> dict:
    """Add summaries and snapshots before persisting / printing."""
    result.setdefault("logged_at", utc_now_iso())
    result["config"] = result.get("config") or build_config_snapshot()
    result["signal_summary"] = summarize_signal(result.get("signal") or {})
    if result.get("close") is not None:
        result["close_summary"] = summarize_close(result.get("close"))
    if result.get("trade") is not None:
        result["trade_summary"] = summarize_trade(result.get("trade"))
    result["action_detail"] = build_action_detail(result)
    result["summary_lines"] = build_run_summary_lines(result)
    return result


def print_run_output(result: dict, *, include_json: bool = True) -> None:
    for line in result.get("summary_lines") or build_run_summary_lines(result):
        print(line)
    if include_json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
