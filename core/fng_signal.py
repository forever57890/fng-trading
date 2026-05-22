"""Fear & Greed daily signal evaluation (shared by backtest and live trader)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from fng_trading.core.strategy_logic import (
    get_ma_signal_at,
    get_position,
    get_stop_loss_rate,
    resolve_take_profit_rate,
)


@dataclass
class DailySignal:
    timestamp: pd.Timestamp
    score: float
    prev_score: float
    score_diff: float
    btc_price: float
    side: Optional[str]
    qty_btc: float
    position_type: Optional[int]
    take_profit_rate: float
    stop_loss_rate: float
    take_profit_price: Optional[float]
    stop_loss_price: Optional[float]
    ma_signal: Optional[int]
    ma: Optional[float]
    should_trade: bool


def parse_fear_greed_rows(data_list: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(data_list)
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["btcPrice"] = pd.to_numeric(df["btcPrice"], errors="coerce")
    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"], errors="coerce"), unit="s", utc=True
    )
    return df.sort_values("timestamp").reset_index(drop=True)


def filter_daily_midnight_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep finalized CMC daily candles (UTC 00:00:00).
    Drops intraday partial rows (e.g. historicalValues \"now\").
    """
    ts = df["timestamp"]
    mask = (
        (ts.dt.hour == 0)
        & (ts.dt.minute == 0)
        & (ts.dt.second == 0)
        & (ts.dt.microsecond == 0)
    )
    return df.loc[mask].reset_index(drop=True)


def _evaluate_signal_row(
    latest: pd.Series,
    prev: pd.Series,
    kline_df: Optional[pd.DataFrame],
    use_ma_tp: bool,
    ma_days: int,
) -> DailySignal:
    score = float(latest["score"])
    prev_score = float(prev["score"])
    score_diff = score - prev_score
    entry_price = float(latest["btcPrice"])
    ts = latest["timestamp"]

    side, qty_btc, position_type = get_position(score_diff)
    sl_rate = get_stop_loss_rate(position_type or 0)
    ma_signal, ma, _ = None, None, None

    if use_ma_tp and kline_df is not None and not kline_df.empty and side:
        ma_signal, ma, _ = get_ma_signal_at(
            kline_df, ts, entry_price, days=ma_days
        )

    tp_rate = resolve_take_profit_rate(
        position_type or 0,
        side,
        ma_signal,
        use_ma_tp=use_ma_tp and ma_signal is not None,
    )

    tp_price = sl_price = None
    if side == "LONG":
        tp_price = entry_price * (1 + tp_rate)
        sl_price = entry_price * (1 - sl_rate)
    elif side == "SHORT":
        tp_price = entry_price * (1 - tp_rate)
        sl_price = entry_price * (1 + sl_rate)

    should_trade = bool(side and qty_btc and qty_btc > 0)

    return DailySignal(
        timestamp=ts,
        score=score,
        prev_score=prev_score,
        score_diff=score_diff,
        btc_price=entry_price,
        side=side,
        qty_btc=float(qty_btc or 0),
        position_type=position_type,
        take_profit_rate=tp_rate,
        stop_loss_rate=sl_rate,
        take_profit_price=tp_price,
        stop_loss_price=sl_price,
        ma_signal=ma_signal,
        ma=ma,
        should_trade=should_trade,
    )


def evaluate_latest_signal(
    data_list: List[Dict[str, Any]],
    kline_df: Optional[pd.DataFrame] = None,
    use_ma_tp: bool = True,
    ma_days: int = 90,
) -> DailySignal:
    """
    Live signal: latest finalized daily candle vs the previous one.
    Ignores intraday partial rows so score_diff matches backtest (yesterday vs day before).
    """
    df = filter_daily_midnight_rows(parse_fear_greed_rows(data_list))
    if len(df) < 2:
        raise ValueError(
            "Need at least 2 finalized daily fear-greed rows to compute score_diff."
        )
    return _evaluate_signal_row(df.iloc[-1], df.iloc[-2], kline_df, use_ma_tp, ma_days)


def evaluate_signal_on_date(
    data_list: List[Dict[str, Any]],
    signal_day: str,
    kline_df: Optional[pd.DataFrame] = None,
    use_ma_tp: bool = True,
    ma_days: int = 90,
) -> DailySignal:
    """
    Evaluate signal for a specific UTC calendar day (YYYY-MM-DD).
    Uses the finalized daily row on that day and the previous daily row.
    """
    df = filter_daily_midnight_rows(parse_fear_greed_rows(data_list))
    df["signal_date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    matches = df.index[df["signal_date"] == signal_day].tolist()
    if not matches:
        available = df["signal_date"].tail(5).tolist()
        raise ValueError(
            f"No fear-greed row for signal_day={signal_day}. "
            f"Recent dates: {available}"
        )

    pos = df.index.get_loc(matches[-1])
    if pos < 1:
        raise ValueError(f"Need a previous row before signal_day={signal_day}")

    latest = df.iloc[pos]
    prev = df.iloc[pos - 1]
    return _evaluate_signal_row(latest, prev, kline_df, use_ma_tp, ma_days)


def signal_to_dict(signal: DailySignal) -> Dict[str, Any]:
    return {
        "timestamp": signal.timestamp.isoformat(),
        "score": signal.score,
        "prev_score": signal.prev_score,
        "score_diff": signal.score_diff,
        "btc_price": signal.btc_price,
        "side": signal.side,
        "qty_btc": signal.qty_btc,
        "position_type": signal.position_type,
        "take_profit_rate": signal.take_profit_rate,
        "stop_loss_rate": signal.stop_loss_rate,
        "take_profit_price": signal.take_profit_price,
        "stop_loss_price": signal.stop_loss_price,
        "ma_signal": signal.ma_signal,
        "ma": signal.ma,
        "should_trade": signal.should_trade,
    }
