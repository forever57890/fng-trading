import unittest
from unittest.mock import patch

import pandas as pd

from fng_trading.backtest.fng_backtest_with_binance_tp import (
    fetch_start_with_buffer,
    filter_to_backtest_period,
    parse_time,
    resolve_period,
)


class TestBacktestPeriod(unittest.TestCase):
    def test_resolve_period_defaults(self):
        start, end = resolve_period()
        self.assertLess(start, end)

    def test_fetch_start_with_buffer(self):
        start = parse_time("2025-01-07 00:00:00")
        buffered = fetch_start_with_buffer(start, buffer_days=2)
        self.assertEqual(buffered, start - 2 * 86400)

    def test_filter_to_backtest_period(self):
        ts = pd.to_datetime(
            ["2025-01-05", "2025-01-06", "2025-01-07"], utc=True
        )
        df = pd.DataFrame({"timestamp": ts, "score": [1, 2, 3]})
        trades = df.iloc[[1, 2]].copy()
        start = parse_time("2025-01-06 00:00:00")
        end = parse_time("2025-01-07 23:59:59")
        df2, tr2 = filter_to_backtest_period(df, trades, start, end)
        self.assertEqual(len(df2), 2)
        self.assertEqual(len(tr2), 2)

    @patch("fng_trading.backtest.fng_backtest_with_binance_tp.fetch_fear_greed_chart_to_file")
    def test_ensure_fear_greed_data_uses_buffered_start(self, mock_fetch_file):
        from fng_trading.backtest.fng_backtest_with_binance_tp import ensure_fear_greed_data

        start = parse_time("2025-06-01 00:00:00")
        end = parse_time("2025-06-30 23:59:59")
        ensure_fear_greed_data(start, end, convert_id=2781)

        mock_fetch_file.assert_called_once()
        call_start, call_end = mock_fetch_file.call_args[0][:2]
        self.assertEqual(mock_fetch_file.call_args[1]["convert_id"], 2781)
        self.assertEqual(call_start, fetch_start_with_buffer(start))
        self.assertEqual(call_end, end)


if __name__ == "__main__":
    unittest.main()
