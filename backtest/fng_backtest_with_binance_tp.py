import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from fng_trading.core.data_fetch import fetch_binance_futures_klines, load_fear_greed_from_file
from fng_trading.core.strategy_logic import apply_trade_logic, get_position

SYMBOL = "BTCUSDT"
INTERVAL = "1d"
_BACKTEST_ROOT = Path(__file__).resolve().parent
DATA_PATH = _BACKTEST_ROOT / "test_data" / "fear_greed_chart.json"


def normalize_to_datalist():
    return load_fear_greed_from_file(str(DATA_PATH))


def build_base_trades(data_list):
    df = pd.DataFrame(data_list)
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["btcPrice"] = pd.to_numeric(df["btcPrice"], errors="coerce")
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="s", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

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
    equity_path = out / "test_data/equity_drawdown.png"
    fig.savefig(equity_path, dpi=150)
    plt.close(fig)
    outputs.append(equity_path)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(trades["net_pnl"].dropna(), bins=50, color="steelblue", alpha=0.8)
    ax.set_title("Net PnL Distribution")
    ax.set_xlabel("Net PnL")
    ax.set_ylabel("Trades")
    fig.tight_layout()
    hist_path = out / "test_data/net_pnl_hist.png"
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
    price_path = out / "test_data/price_with_trades.png"
    fig.savefig(price_path, dpi=150)
    plt.close(fig)
    outputs.append(price_path)

    return outputs


def main(output_dir=None, use_ma_tp: bool = True):
    out_dir = Path(output_dir) if output_dir is not None else _BACKTEST_ROOT

    data_list = normalize_to_datalist()

    df, trades = build_base_trades(data_list)
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

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "test_data").mkdir(parents=True, exist_ok=True)
    trades[cols].to_json(out_dir / "test_data/trade_details_with_5pct_tp.json", orient="records", date_format="iso", indent=4)
    summary = summarize(trades)
    (out_dir / "test_data/summary_with_5pct_tp.json").write_text(
        json.dumps(summary, indent=4),
        encoding="utf-8",
    )
    side_summary(trades).to_json(out_dir / "test_data/side_summary_with_5pct_tp.json", orient="records", date_format="iso", indent=4)
    kline_df.to_json(out_dir / "test_data/binance_btcusdt_1d_klines.json", orient="records", date_format="iso", indent=4)
    chart_paths = plot_results(df, trades, out_dir)

    print("Saved:")
    print(out_dir / "test_data/trade_details_with_5pct_tp.json")
    print(out_dir / "test_data/summary_with_5pct_tp.json")
    print(out_dir / "test_data/side_summary_with_5pct_tp.json")
    print(out_dir / "test_data/binance_btcusdt_1d_klines.json")
    for chart in chart_paths:
        print(chart)
    print("\nSummary:")
    print(json.dumps(summary, indent=4))


if __name__ == "__main__":
    main(use_ma_tp=True)
