import pandas as pd


FEE_RATE = 0.0003  # 0.03%


def get_position(score_diff: float):
    if pd.isna(score_diff):
        return None, 0, None

    if 4 <= score_diff <= 10:
        return "LONG", 3, 3

    elif 10 <= score_diff <= 16:
        return "LONG", 3, 3

    if -20 <= score_diff <= -4:
        return "SHORT", 3, 3
    elif score_diff < -20:
        return "SHORT", 3, 3

    return None, 0, None


def get_take_profit_rate(position_type: int):
    tp_map = {1: 0.04, 2: 0.04, 3: 0.04, 4: 0.02}
    return tp_map.get(int(position_type or 0), 0.0)


def get_stop_loss_rate(position_type: int):
    sl_map = {1: 0.06, 2: 0.06, 3: 0.06, 4: 0.06}
    return sl_map.get(int(position_type or 0), 0.0)


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
            ma_signal, ma, close_price = get_ma_signal_at(kline_df, entry_time, entry, days=90)
        else:
            ma_signal, ma, close_price = None, None, None
        tp_rate = get_take_profit_rate(position_type)
        if use_ma_tp:
            if ma_signal == 1 and side == "LONG":
                tp_rate = 0.06
            elif ma_signal == 0 and side == "SHORT":
                tp_rate = 0.03

        sl_rate = get_stop_loss_rate(qty)
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
