import argparse
import json
from datetime import datetime
from pathlib import Path

from fng_trading.core.data_fetch import fetch_fear_greed_chart

DEFAULT_START = "2025-01-07 00:00:00"
DEFAULT_END = "2026-05-19 23:59:59"
_BACKTEST_ROOT = Path(__file__).resolve().parent


def parse_time(value: str):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())


def main():
    default_out = _BACKTEST_ROOT / "test_data" / "fear_greed_chart.json"
    parser = argparse.ArgumentParser(description="Fetch CoinMarketCap fear-greed chart data.")
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)
    parser.add_argument("--convert-id", type=int, default=2781)
    parser.add_argument("--output", default=str(default_out))
    args = parser.parse_args()

    if args.start is None:
        args.start = parse_time(DEFAULT_START)
    if args.end is None:
        args.end = parse_time(DEFAULT_END)

    data = fetch_fear_greed_chart(args.start, args.end, args.convert_id)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
