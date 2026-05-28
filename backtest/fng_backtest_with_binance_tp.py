import path_setup  # noqa: F401, E402

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd

from fng_trading.backtest.backtest_io import FEAR_GREED_CHART_PATH, ensure_test_data_dir
from fng_trading.backtest.fear_greed_chart_fetch import fetch_fear_greed_chart_to_file
from fng_trading.core.data_fetch import fetch_binance_futures_klines, load_fear_greed_from_file
from fng_trading.core.fng_signal import filter_daily_midnight_rows, parse_fear_greed_rows
from fng_trading.core.strategy_logic import apply_trade_logic, get_position

SYMBOL = "BTCUSDT"
INTERVAL = "1d"
_BACKTEST_ROOT = Path(__file__).resolve().parent

# --- backtest period (passed into fear_greed_chart_fetch when fetching) ---
DEFAULT_START = "2025-05-26 00:00:00"
DEFAULT_END = "2026-05-30 23:59:59"
DEFAULT_CONVERT_ID = 2781
FNG_FETCH_BUFFER_DAYS = 2


def parse_time(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())


def resolve_period(
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> tuple[int, int]:
    if start is None:
        start = parse_time(DEFAULT_START)
    if end is None:
        end = parse_time(DEFAULT_END)
    return start, end


def fetch_start_with_buffer(
    start: int, buffer_days: int = FNG_FETCH_BUFFER_DAYS
) -> int:
    return start - int(timedelta(days=buffer_days).total_seconds())


def ensure_fear_greed_data(
    start: int,
    end: int,
    *,
    convert_id: int = DEFAULT_CONVERT_ID,
    output: Path = FEAR_GREED_CHART_PATH,
) -> Path:
    """Fetch fear-greed JSON for the backtest window (+ buffer before start)."""
    fetch_start = fetch_start_with_buffer(start)
    print(
        f"Fetching Fear & Greed chart for backtest "
        f"(buffered start={fetch_start}, end={end}, convert_id={convert_id}) ..."
    )
    path = fetch_fear_greed_chart_to_file(
        fetch_start, end, output=output, convert_id=convert_id
    )
    print(f"Saved fear-greed data: {path}")
    return path


def normalize_to_datalist():
    ensure_test_data_dir(FEAR_GREED_CHART_PATH)
    return load_fear_greed_from_file(str(FEAR_GREED_CHART_PATH))


def build_base_trades(data_list):
    df = filter_daily_midnight_rows(parse_fear_greed_rows(data_list))

    df["prev_score"] = df["score"].shift(1)
    df["score_diff"] = df["score"] - df["prev_score"]
    df["normal_exit_time"] = df["timestamp"].shift(-1)
    df["normal_exit_price"] = df["btcPrice"].shift(-1)

    positions = df["score_diff"].apply(get_position)
    df["side"] = positions.apply(lambda x: x[0])
    df["qty_btc"] = positions.apply(lambda x: x[1])
    df["position_type"] = positions.apply(lambda x: x[2])

    trades = df[
        (df["side"].notna())
        & (df["qty_btc"] > 0)
        & (df["normal_exit_price"].notna())
    ].copy()
    return df, trades


def filter_to_backtest_period(
    df: pd.DataFrame, trades: pd.DataFrame, start: int, end: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start_ts = pd.to_datetime(start, unit="s", utc=True)
    end_ts = pd.to_datetime(end, unit="s", utc=True)
    in_range = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
    df = df.loc[in_range].reset_index(drop=True)
    trades = trades.loc[trades["timestamp"].between(start_ts, end_ts)].copy()
    return df, trades


def summarize(trades):
    if trades.empty:
        return {"total_trades": 0}
    return {
        "total_trades": len(trades),
        "wins": int(trades["win"].sum()),
        "losses": int((~trades["win"]).sum()),
        "win_rate": trades["win"].mean(),
        "tp_hits": int(trades["take_profit_hit"].sum()),
        "tp_hit_rate": trades["take_profit_hit"].mean(),
        "net_pnl": trades["net_pnl"].sum(),
        "max_profit": trades["net_pnl"].max(),
        "max_loss": trades["net_pnl"].min(),
        "max_drawdown": trades["drawdown"].min(),
    }


def side_summary(trades):
    return trades.groupby("side").agg(
        trades=("net_pnl", "count"),
        wins=("win", "sum"),
        win_rate=("win", "mean"),
        tp_hits=("take_profit_hit", "sum"),
        tp_hit_rate=("take_profit_hit", "mean"),
        gross_pnl=("gross_pnl", "sum"),
        fees=("fee", "sum"),
        net_pnl=("net_pnl", "sum"),
        avg_net_pnl=("net_pnl", "mean"),
        avg_net_return=("net_return", "mean"),
    ).reset_index()


def plot_results(df, trades, output_dir):
    if trades.empty:
        return []

    out = Path(output_dir)
    test_data_dir = ensure_test_data_dir(out / "test_data")
    outputs = []

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(trades["timestamp"], trades["cum_net_pnl"], label="Cumulative net PnL", color="tab:blue")
    axes[0].axhline(0, color="gray", linewidth=1, linestyle="--")
    axes[0].set_ylabel("PnL")
    axes[0].set_title("Equity Curve")
    axes[0].legend(loc="best")

    axes[1].plot(trades["timestamp"], trades["drawdown"], label="Drawdown", color="tab:red")
    axes[1].set_ylabel("PnL")
    axes[1].set_title("Drawdown")
    axes[1].legend(loc="best")

    fig.tight_layout()
    equity_path = test_data_dir / "equity_drawdown.png"
    fig.savefig(equity_path, dpi=150)
    plt.close(fig)
    outputs.append(equity_path)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(trades["net_pnl"].dropna(), bins=50, color="steelblue", alpha=0.8)
    ax.set_title("Net PnL Distribution")
    ax.set_xlabel("Net PnL")
    ax.set_ylabel("Trades")
    fig.tight_layout()
    hist_path = test_data_dir / "net_pnl_hist.png"
    fig.savefig(hist_path, dpi=150)
    plt.close(fig)
    outputs.append(hist_path)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df["timestamp"], df["btcPrice"], color="black", linewidth=1, label="BTC Price")
    long_trades = trades[trades["side"] == "LONG"]
    short_trades = trades[trades["side"] == "SHORT"]
    ax.scatter(long_trades["timestamp"], long_trades["btcPrice"], marker="^", color="green", label="LONG", s=30)
    ax.scatter(short_trades["timestamp"], short_trades["btcPrice"], marker="v", color="red", label="SHORT", s=30)
    ax.set_title("BTC Price with Trades")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    ax.legend(loc="best")
    fig.tight_layout()
    price_path = test_data_dir / "price_with_trades.png"
    fig.savefig(price_path, dpi=150)
    plt.close(fig)
    outputs.append(price_path)

    return outputs


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fear & Greed backtest with Binance TP/SL simulation."
    )
    parser.add_argument(
        "--start",
        type=parse_time,
        help=f"Backtest start (UTC), e.g. {DEFAULT_START}",
    )
    parser.add_argument(
        "--end",
        type=parse_time,
        help=f"Backtest end (UTC), e.g. {DEFAULT_END}",
    )
    parser.add_argument("--convert-id", type=int, default=DEFAULT_CONVERT_ID)
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Do not call CMC API; use existing fear_greed_chart.json",
    )
    parser.add_argument("--output-dir", default=None, help="Backtest output root directory")
    parser.add_argument(
        "--no-ma-tp",
        action="store_true",
        help="Disable MA-adjusted take-profit",
    )
    return parser.parse_args(argv)


def main(
    output_dir=None,
    use_ma_tp: bool = True,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    skip_fetch: bool = False,
    convert_id: int = DEFAULT_CONVERT_ID,
):
    start, end = resolve_period(start, end)
    out_dir = Path(output_dir) if output_dir is not None else _BACKTEST_ROOT
    test_data_dir = ensure_test_data_dir(out_dir / "test_data")

    if not skip_fetch:
        ensure_fear_greed_data(start, end, convert_id=convert_id)
    else:
        print("Skipping Fear & Greed fetch (--skip-fetch); using local JSON.")

    data_list = normalize_to_datalist()

    df, trades = build_base_trades(data_list)
    df, trades = filter_to_backtest_period(df, trades, start, end)

    if df.empty:
        raise ValueError(
            f"No fear-greed daily rows in backtest period "
            f"({datetime.fromtimestamp(start, tz=timezone.utc)} .. "
            f"{datetime.fromtimestamp(end, tz=timezone.utc)}). "
            "Check --start/--end or run fetch without --skip-fetch."
        )

    start_ms = int(df["timestamp"].min().timestamp() * 1000)
    ma_start_ms = start_ms - int(pd.Timedelta(days=30).total_seconds() * 1000)
    end_ms = int((df["timestamp"].max() + pd.Timedelta(days=1)).timestamp() * 1000)

    print(f"Fetching Binance klines: {SYMBOL}, {INTERVAL}, {ma_start_ms} -> {end_ms}")
    kline_df = fetch_binance_futures_klines(SYMBOL, INTERVAL, ma_start_ms, end_ms)
    trades = apply_trade_logic(trades, kline_df, use_ma_tp=use_ma_tp)

    cols = [
        "timestamp", "normal_exit_time", "prev_score", "score", "score_diff", "side", "qty_btc",
        "position_type",
        "btcPrice", "take_profit_price", "kline_high", "kline_low", "normal_exit_price",
        "stop_loss_price", "ma_signal", "ma", "ma_entry_price",
        "exit_price", "exit_reason", "take_profit_hit", "stop_loss_hit",
        "gross_pnl", "fee", "net_pnl", "net_return", "win",
        "cum_net_pnl", "drawdown",
    ]

    trades[cols].to_json(
        test_data_dir / "trade_details_with_5pct_tp.json",
        orient="records",
        date_format="iso",
        indent=4,
    )
    summary = summarize(trades)
    (test_data_dir / "summary_with_5pct_tp.json").write_text(
        json.dumps(summary, indent=4),
        encoding="utf-8",
    )
    side_summary(trades).to_json(
        test_data_dir / "side_summary_with_5pct_tp.json",
        orient="records",
        date_format="iso",
        indent=4,
    )
    kline_df.to_json(
        test_data_dir / "binance_btcusdt_1d_klines.json",
        orient="records",
        date_format="iso",
        indent=4,
    )
    chart_paths = plot_results(df, trades, out_dir)

    print("Saved:")
    print(test_data_dir / "trade_details_with_5pct_tp.json")
    print(test_data_dir / "summary_with_5pct_tp.json")
    print(test_data_dir / "side_summary_with_5pct_tp.json")
    print(test_data_dir / "binance_btcusdt_1d_klines.json")
    for chart in chart_paths:
        print(chart)
    print("\nSummary:")
    print(json.dumps(summary, indent=4))


if __name__ == "__main__":
    cli = parse_args()
    main(
        output_dir=cli.output_dir,
        use_ma_tp=not cli.no_ma_tp,
        start=cli.start,
        end=cli.end,
        skip_fetch=cli.skip_fetch,
        convert_id=cli.convert_id,
    )
