from flask import Flask
import ccxt
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.binance({
    "enableRateLimit": True
})

MIN_USDT_VOLUME = 100000
MIN_PRICE_CHANGE = 0.5

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def scan():
    telegram("✅ BINANCE pump scanner başladı hocam.")
    while True:
        try:
            tickers = exchange.fetch_tickers()
sent_coins = set()
            for coin, data in tickers.items():
                if "/USDT" not in coin:
                    continue

                volume = data.get("quoteVolume") or 0
                change = data.get("percentage") or 0
                price = data.get("last") or 0

                if (
    volume > 15000000
    and change > 5
):
                    msg = f"""🚨 BINANCE PARA GİRİŞİ

Coin: {coin}
Fiyat: {price}
24s Değişim: %{round(change, 2)}
24s Hacim: {round(volume):,} USDT

⚠️ Kontrol:
- 5m mum güçlü mü?
- Üst direnç yakın mı?
- Hacim devam ediyor mu?"""
                    telegram(msg)

            time.sleep(60)

        except Exception as e:
            print("Hata:", e)
            time.sleep(20)

@app.route("/")
def home():
    return "BINANCE bot aktif"

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
