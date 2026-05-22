"""
Fetch CMC fear-greed chart JSON to disk.

Period defaults and CLI wiring live in fng_backtest_with_binance_tp; this module
only performs the HTTP fetch and file write when called with explicit parameters.
"""

import argparse
import json
from pathlib import Path
from typing import Optional, Union

from backtest.backtest_io import FEAR_GREED_CHART_PATH, ensure_test_data_dir
from core.data_fetch import fetch_fear_greed_chart

PathLike = Union[str, Path]


def fetch_fear_greed_chart_to_file(
    start: int,
    end: int,
    output: PathLike,
    convert_id: int,
) -> Path:
    """Fetch CMC fear-greed chart JSON and write to *output*."""
    output_path = Path(output)
    ensure_test_data_dir(output_path)
    data = fetch_fear_greed_chart(start, end, convert_id)
    output_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return output_path


def main(argv: Optional[list[str]] = None) -> Path:
    from fng_trading.backtest.fng_backtest_with_binance_tp import (
        DEFAULT_CONVERT_ID,
        DEFAULT_END,
        DEFAULT_START,
        parse_time,
        resolve_period,
    )

    parser = argparse.ArgumentParser(description="Fetch CoinMarketCap fear-greed chart data.")
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)
    parser.add_argument("--convert-id", type=int, default=DEFAULT_CONVERT_ID)
    parser.add_argument("--output", default=str(FEAR_GREED_CHART_PATH))
    args = parser.parse_args(argv)

    start, end = resolve_period(args.start, args.end)
    print(f"Fetching Fear & Greed: start={start} end={end} convert_id={args.convert_id}")
    path = fetch_fear_greed_chart_to_file(
        start, end, output=args.output, convert_id=args.convert_id
    )
    print(path)
    return path


if __name__ == "__main__":
    main()
