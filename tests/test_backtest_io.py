import tempfile
import unittest
from pathlib import Path

from fng_trading.backtest.backtest_io import ensure_test_data_dir


class TestBacktestIo(unittest.TestCase):
    def test_ensure_test_data_dir_creates_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "test_data"
            self.assertFalse(target.exists())
            created = ensure_test_data_dir(target)
            self.assertTrue(created.is_dir())
            self.assertEqual(created, target)

    def test_ensure_test_data_dir_from_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test_data" / "out.json"
            parent = ensure_test_data_dir(file_path)
            self.assertTrue(parent.is_dir())
            self.assertEqual(parent, file_path.parent)


if __name__ == "__main__":
    unittest.main()
