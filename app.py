import ccxt
import requests
import time
import os

TELEGRAM_TOKEN = "BURAYA_TOKEN"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({
    "enableRateLimit": True
})

TIMEFRAME = "5m"
LIMIT = 40

VOLUME_MULTIPLIER = 2.5
PRICE_MIN = 1.0
PRICE_MAX = 8.0
MIN_USDT_VOLUME = 300000
COOLDOWN = 30 * 60

sent = {}

def telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

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

        msg = f"""
🚨 MEXC PARA GİRİŞİ

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

    symbols = get_symbols()

    while True:
        for symbol in symbols:
            try:
                scan(symbol)
            except Exception as e:
                print(symbol, e)

        time.sleep(60)

main()
import threading
import os

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
