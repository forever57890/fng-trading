import requests
from datetime import datetime

DEFAULT_START = "2024-05-07 00:00:00"
DEFAULT_END = "2026-05-06 23:59:59"
BASE_URL = "https://api.coinmarketcap.com/data-api/v3/fear-greed/chart"



def parse_time(value: str):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())

def fetch_fear_greed_chart(start: int, end: int, convert_id: int):
    
    start = parse_time(start)
    end = parse_time(end)
    params = {"start": start, "end": end, "convertId": convert_id}
    response = requests.get(BASE_URL, params=params)
    response.raise_for_status()
    return response.json()
    
data = fetch_fear_greed_chart(DEFAULT_START, DEFAULT_END, 2781)
print(data)