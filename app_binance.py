from flask import Flask
import ccxt
import requests
import time

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.binance({
    "enableRateLimit": True
})

sent_coins = {}

# AYARLAR
MIN_VOLUME = 300000        # minimum hacim
VOLUME_MULTIPLIER = 2      # hacim artışı
MAX_CHANGE = 3             # fazla pump olmuşları alma
COOLDOWN = 60 * 30         # aynı coin 30 dk sus

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def scan():
    telegram("🟡 BINANCE ön hazırlık botu başladı hocam")

    while True:
        try:
            tickers = exchange.fetch_tickers()

            for coin, data in tickers.items():

                if "/USDT" not in coin:
                    continue

                volume = data.get("quoteVolume") or 0
                change = data.get("percentage") or 0
                price = data.get("last") or 0

                # 1️⃣ HACİM ŞARTI
                if volume < MIN_VOLUME:
                    continue

                # 2️⃣ FAZLA PUMP OLMAMIŞ OLSUN
                if change > MAX_CHANGE:
                    continue

                # 3️⃣ COOLDOWN (spam önleme)
                now = time.time()
                if coin in sent_coins and now - sent_coins[coin] < COOLDOWN:
                    continue

                # 🎯 SİNYAL
                msg = f"""🟡 BINANCE ÖN HAZIRLIK

Coin: {coin}
Fiyat: {price}
24s Değişim: %{round(change,2)}
Hacim: {int(volume)}

⚠️ Hacim var ama pump yok
🚀 Pump hazırlığı olabilir"""

                telegram(msg)
                sent_coins[coin] = now

            time.sleep(60)

        except Exception as e:
            print("Hata:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "Bot çalışıyor hocam"

import threading
threading.Thread(target=scan).start()
