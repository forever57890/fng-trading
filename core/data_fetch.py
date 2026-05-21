import json
import time
from datetime import datetime

import pandas as pd
import requests


BASE_URL = "https://api.coinmarketcap.com/data-api/v3/fear-greed/chart"
BN_BASE_URL = "https://fapi.binance.com"


def parse_time(value: str):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())


def fetch_fear_greed_chart(start: int, end: int, convert_id: int):
    params = {"start": start, "end": end, "convertId": convert_id}
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def load_fear_greed_from_file(path: str):
    with open(path, encoding="utf-8") as f:
        raw_data = json.load(f)
    return raw_data["data"]["dataList"]


def fetch_binance_futures_klines(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1500):
    """Fetch Binance USD-M Futures klines. Returns open/high/low/close by UTC open_time."""
    url = f"{BN_BASE_URL}/fapi/v1/klines"
    all_rows = []
    cursor = start_ms

    while cursor <= end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": limit,
        }
        last_err = None
        for attempt in range(5):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                rows = r.json()
                break
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Binance API failed: {last_err}")

        if not rows:
            break

        all_rows.extend(rows)
        last_open_time = int(rows[-1][0])
        next_cursor = last_open_time + 24 * 60 * 60 * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.15)

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trade_count", "taker_buy_base_volume",
        "taker_buy_quote_volume", "ignore",
    ]
    k = pd.DataFrame(all_rows, columns=cols).drop_duplicates("open_time")
    k["open_time"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
    k["close_time"] = pd.to_datetime(k["close_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        k[c] = pd.to_numeric(k[c], errors="coerce")
    return k.sort_values("open_time").reset_index(drop=True)
