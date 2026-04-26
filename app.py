from flask import Flask
import ccxt
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({
    "enableRateLimit": True
})

TIMEFRAME = "5m"
LIMIT = 40
VOLUME_MULTIPLIER = 1.5
PRICE_MIN = 0.4
PRICE_MAX = 6.0
MIN_USDT_VOLUME = 100000
COOLDOWN = 30 * 60

sent = {}

@app.route("/")
def home():
    return "MEXC pump scanner çalışıyor", 200

def telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)

def get_symbols():
    markets = exchange.load_markets()
    return [
        s for s in markets
        if s.endswith("/USDT") and markets[s].get("active")
    ]

def scan(symbol):
    candles = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=LIMIT)

    if len(candles) < 30:
        return

    volumes = []
    closes = []
    opens = []

    for c in candles:
        opens.append(c[1])
        closes.append(c[4])
        volumes.append(c[4] * c[5])

    avg_volume = sum(volumes[-25:-5]) / 20
    recent_volume = sum(volumes[-3:])
    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 0

    start_price = opens[-3]
    last_price = closes[-1]
    price_change = ((last_price - start_price) / start_price) * 100

    if recent_volume < MIN_USDT_VOLUME:
        return

    if volume_ratio >= VOLUME_MULTIPLIER and PRICE_MIN <= price_change <= PRICE_MAX:
        now = time.time()

        if symbol in sent and now - sent[symbol] < COOLDOWN:
            return

        sent[symbol] = now

        msg = f"""🚨 MEXC PARA GİRİŞİ

Coin: {symbol}
Fiyat: {last_price}
Son 15dk Değişim: %{price_change:.2f}
Hacim Artışı: {volume_ratio:.2f}x
Son 15dk Hacim: {recent_volume:,.0f} USDT

⚠️ Kontrol:
- 5m mum güçlü mü?
- Üst direnç yakın mı?
- Hacim devam ediyor mu?
"""
        telegram(msg)

def main():
    telegram("✅ MEXC pump scanner başladı hocam.")

    while True:
        try:
            symbols = get_symbols()
            print(f"{len(symbols)} coin taranıyor...")
            for symbol in symbols:
                try:
                    scan(symbol)
                except Exception as e:
                    print(symbol, e)

        except Exception as e:
            print("Ana tarama hatası:", e)

        time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
