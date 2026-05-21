from __future__ import annotations

from typing import Optional

import pandas as pd

# --- fees ---
FEE_RATE = 0.0001  # 0.01%

# --- position sizing ---
QTY_BTC = 1
POSITION_TYPE = 3

# --- entry zones (score_diff = today - yesterday) ---
LONG_DIFF_MIN = 4
LONG_DIFF_MAX = 20
SHORT_DIFF_MIN = -20
SHORT_DIFF_MAX = -4

# --- take-profit / stop-loss by position_type ---
TAKE_PROFIT_RATE_BY_TYPE = {1: 0.04, 2: 0.04, 3: 0.04, 4: 0.02}
STOP_LOSS_RATE_BY_TYPE = {1: 0.06, 2: 0.06, 3: 0.06, 4: 0.06}

# --- MA-adjusted take-profit overrides (use_ma_tp=True) ---
MA_TP_LONG_LOW_VS_MA = 0.06   # entry below MA, LONG
MA_TP_SHORT_HIGH_VS_MA = 0.03  # entry above MA, SHORT
MA_DAYS_BACKTEST = 90


def get_position(score_diff: float):
    if pd.isna(score_diff):
        return None, 0, None

    if LONG_DIFF_MIN <= score_diff <= LONG_DIFF_MAX:
        return "LONG", QTY_BTC, POSITION_TYPE

    if SHORT_DIFF_MIN <= score_diff <= SHORT_DIFF_MAX:
        return "SHORT", QTY_BTC, POSITION_TYPE
    if score_diff < SHORT_DIFF_MIN:
        return "SHORT", QTY_BTC, POSITION_TYPE

    return None, 0, None


def get_take_profit_rate(position_type: int) -> float:
    return TAKE_PROFIT_RATE_BY_TYPE.get(int(position_type or 0), 0.0)


def get_stop_loss_rate(position_type: int) -> float:
    return STOP_LOSS_RATE_BY_TYPE.get(int(position_type or 0), 0.0)


def resolve_take_profit_rate(
    position_type: int,
    side: Optional[str],
    ma_signal: Optional[int],
    *,
    use_ma_tp: bool = False,
) -> float:
    tp_rate = get_take_profit_rate(position_type)
    if not use_ma_tp or side is None or ma_signal is None:
        return tp_rate
    if ma_signal == 1 and side == "LONG":
        return MA_TP_LONG_LOW_VS_MA
    if ma_signal == 0 and side == "SHORT":
        return MA_TP_SHORT_HIGH_VS_MA
    return tp_rate


def get_ma_signal_at(kline_df: pd.DataFrame, timestamp: pd.Timestamp, entry_price: float, days: int = 30):
    window = kline_df[kline_df["open_time"] <= timestamp].tail(days)
    if len(window) < days:
        return None, None, None
    ma = window["close"].mean()
    entry_price = float(entry_price)
    ma_signal = int(entry_price < ma)
    return ma_signal, ma, entry_price


def apply_trade_logic(trades: pd.DataFrame, kline_df: pd.DataFrame, use_ma_tp: bool = True):
    trades = trades.copy()
    out = []

    for _, row in trades.iterrows():
        entry_time = row["timestamp"]
        exit_time = row["normal_exit_time"]
        side = row["side"]
        qty = row["qty_btc"]
        position_type = row["position_type"]
        entry = row["btcPrice"]
        normal_exit = row["normal_exit_price"]

        holding = kline_df[(kline_df["open_time"] >= entry_time) & (kline_df["open_time"] < exit_time)]
        if holding.empty:
            holding = kline_df[kline_df["open_time"].dt.date == entry_time.date()]

        k_high = float(holding["high"].max()) if not holding.empty else float(entry)
        k_low = float(holding["low"].min()) if not holding.empty else float(entry)

        if use_ma_tp:
            ma_signal, ma, close_price = get_ma_signal_at(
                kline_df, entry_time, entry, days=MA_DAYS_BACKTEST
            )
        else:
            ma_signal, ma, close_price = None, None, None

        tp_rate = resolve_take_profit_rate(
            position_type, side, ma_signal, use_ma_tp=use_ma_tp
        )
        sl_rate = get_stop_loss_rate(position_type)
        tp_price = entry * (1 + tp_rate) if side == "LONG" else entry * (1 - tp_rate)
        sl_price = entry * (1 - sl_rate) if side == "LONG" else entry * (1 + sl_rate)

        if side == "LONG":
            tp_hit = k_high >= tp_price
            sl_hit = k_low <= sl_price
            if sl_hit and tp_hit:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
            elif tp_hit:
                exit_price = tp_price
                exit_reason = "TAKE_PROFIT"
            elif sl_hit:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
            else:
                exit_price = normal_exit
                exit_reason = "NORMAL_EXIT"
        else:
            tp_hit = k_low <= tp_price
            sl_hit = k_high >= sl_price
            if sl_hit and tp_hit:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
            elif tp_hit:
                exit_price = tp_price
                exit_reason = "TAKE_PROFIT"
            elif sl_hit:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
            else:
                exit_price = normal_exit
                exit_reason = "NORMAL_EXIT"

        gross = qty * (exit_price - entry) if side == "LONG" else qty * (entry - exit_price)
        fee = (qty * entry + qty * exit_price) * FEE_RATE
        net = gross - fee
        net_return = net / (qty * entry) if qty * entry else 0

        out.append({
            "kline_high": k_high,
            "kline_low": k_low,
            "take_profit_price": tp_price,
            "stop_loss_price": sl_price,
            "ma_signal": ma_signal,
            "ma": ma,
            "ma_entry_price": close_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "take_profit_hit": exit_reason == "TAKE_PROFIT",
            "stop_loss_hit": exit_reason == "STOP_LOSS",
            "gross_pnl": gross,
            "fee": fee,
            "net_pnl": net,
            "net_return": net_return,
            "win": net > 0,
        })

    res = pd.DataFrame(out, index=trades.index)
    trades = pd.concat([trades, res], axis=1)
    trades["cum_net_pnl"] = trades["net_pnl"].cumsum()
    trades["cum_peak"] = trades["cum_net_pnl"].cummax()
    trades["drawdown"] = trades["cum_net_pnl"] - trades["cum_peak"]
    return trades
