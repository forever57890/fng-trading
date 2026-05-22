"""
將本 repo 的父目錄加入 sys.path，使 ``import fng_trading`` 可用。

僅供在專案根目錄執行 ``python -m backtest.*`` 時使用。
Cron / ``python -m fng_trading.trade.*`` 請依賴 PYTHONPATH 或 run_fng_daily_cron.sh，
勿 import 本模組（path_setup 不在套件路徑上會報錯）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


def ensure() -> None:
    parent = str(_REPO_ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)


ensure()
