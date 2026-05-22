import json
import unittest
from pathlib import Path

from fng_trading.core.fng_signal import (
    evaluate_latest_signal,
    evaluate_signal_on_date,
    filter_daily_midnight_rows,
    parse_fear_greed_rows,
)

_CHART_PATH = (
    Path(__file__).resolve().parent.parent
    / "backtest"
    / "test_data"
    / "fear_greed_chart.json"
)


def _load_data_list() -> list:
    raw = json.loads(_CHART_PATH.read_text(encoding="utf-8"))
    return raw["data"]["dataList"]


class TestFngSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_list = _load_data_list()

    def test_filter_daily_midnight_drops_intraday_now(self):
        df = parse_fear_greed_rows(self.data_list)
        daily = filter_daily_midnight_rows(df)
        self.assertLess(len(daily), len(df))
        last = daily.iloc[-1]
        self.assertEqual(str(last["timestamp"]), "2026-05-21 00:00:00+00:00")

    def test_evaluate_latest_uses_yesterday_vs_day_before(self):
        signal = evaluate_latest_signal(self.data_list, use_ma_tp=False)
        self.assertEqual(str(signal.timestamp), "2026-05-21 00:00:00+00:00")
        self.assertEqual(signal.score, 40.0)
        self.assertEqual(signal.prev_score, 39.0)
        self.assertEqual(signal.score_diff, 1.0)

    def test_evaluate_signal_on_date_ignores_intraday_same_calendar_day(self):
        with self.assertRaises(ValueError):
            evaluate_signal_on_date(
                self.data_list, "2026-05-22", use_ma_tp=False
            )

    def test_evaluate_signal_on_date_matches_latest_daily(self):
        signal = evaluate_signal_on_date(
            self.data_list, "2026-05-21", use_ma_tp=False
        )
        latest = evaluate_latest_signal(self.data_list, use_ma_tp=False)
        self.assertEqual(signal.score_diff, latest.score_diff)
        self.assertEqual(signal.score, latest.score)


if __name__ == "__main__":
    unittest.main()
