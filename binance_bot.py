import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

BOT_NAME = "🚀 BINANCE RAILWAY FUTURES BOT"

# TELEGRAM
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
TELEGRAM_CHAT_ID = "6977265844"

# PROXY
proxy_host = "p.webshare.io"
proxy_port = "80"
proxy_user = "maxwemri"
proxy_pass = "ashvrfdkt6r5"

proxies = {
    "http": f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}",
    "https": f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
}

# BINANCE
BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 60
TOP_SYMBOL_LIMIT = 120
COOLDOWN_SECONDS = 60 * 30

MIN_SCORE_PREP = 9
MIN_SCORE_CONFIRM = 14

MIN_24H_VOLUME_USDT = 10_000_000

sent_signals = {}

# TELEGRAM MESAJ
def telegram_send(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }

        response = requests.post(
            url,
            data=payload,
            timeout=10
        )

        print("Telegram cevap:", response.status_code)

    except Exception as e:
        print("Telegram hata:", e)

# TEST MESAJI
telegram_send("🧪 TEST MESAJI: Binance bot Railway üzerinde başladı hocam.")

# BINANCE TEST
try:
    response = requests.get(
        f"{BASE_URL}/fapi/v1/ticker/24hr",
        timeout=15,
        proxies=proxies
    )

    data = response.json()

    print("Binance bağlantı başarılı.")
    print("Coin sayısı:", len(data))

    telegram_send("✅ Binance proxy bağlantısı başarılı hocam.")

except Exception as e:
    print("API hata:", e)

    telegram_send(
        f"⚠️ Binance verisi gelmedi hocam.\n\nHata:\n{e}"
    )

while True:

    try:

        response = requests.get(
            f"{BASE_URL}/fapi/v1/ticker/24hr",
            timeout=15,
            proxies=proxies
        )

        tickers = response.json()

        print("Taranan coin:", len(tickers), datetime.now())

    except Exception as e:

        print("Binance ticker veri hatası:", e)

        telegram_send(
            f"⚠️ Binance veri hatası hocam:\n{e}"
        )

    time.sleep(SCAN_INTERVAL)
