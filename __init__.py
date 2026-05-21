"""
fng_trading — Fear & Greed（恐慌指數）策略套件。

- fng_trading.core：共用邏輯（訊號、資料抓取、回測用 PnL 規則）。
- fng_trading.backtest：歷史資料與回測腳本。
- fng_trading.trade：每日 UTC 00:00 實盤排程與 Binance 合約下單。

請從專案根目錄執行模組，例如：
python -m fng_trading.backtest.fng_backtest_with_binance_tp
"""

__all__ = ["__doc__"]
