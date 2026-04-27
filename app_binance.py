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
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot"
    }
})

TIMEFRAME = "5m"
LIMIT = 6

MIN_LAST_VOLUME_USDT = 100_000
MIN_VOLUME_MULTIPLIER = 3
MIN_PRICE_CHANGE_15M = 0.8
MAX_PRICE_CHANGE_15M = 4
COOLDOWN_SECONDS = 60 * 60

HEARTBEAT_SECONDS = 10 * 60

sent_coins = {}

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def scan_symbol(symbol):
    candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)

    if len(candles) < 6:
        return None

    last = candles[-1]
    prev = candles[-4:-1]

    open_15m = prev[0][1]
    close_now = last[4]

    change_15m = ((close_now - open_15m) / open_15m) * 100

    last_volume_usdt = last[5] * close_now
    avg_prev_volume_usdt = sum(c[5] * c[4] for c in prev) / len(prev)

    if avg_prev_volume_usdt == 0:
        return None

    volume_multiplier = last_volume_usdt / avg_prev_volume_usdt

    if (
        last_volume_usdt > MIN_LAST_VOLUME_USDT
        and volume_multiplier > MIN_VOLUME_MULTIPLIER
        and change_15m > MIN_PRICE_CHANGE_15M
        and change_15m < MAX_PRICE_CHANGE_15M
    ):
        return {
            "symbol": symbol,
            "price": close_now,
            "change": change_15m,
            "volume": last_volume_usdt,
            "multiplier": volume_multiplier
        }

    return None

def scan():
    telegram("✅ BINANCE erken pump scanner başladı hocam.")

    markets = exchange.load_markets()
    symbols = [
        s for s in markets
        if s.endswith("/USDT") and markets[s].get("spot")
    ]

    last_heartbeat = 0

    while True:
        now = time.time()

        if now - last_heartbeat > HEARTBEAT_SECONDS:
            telegram("🟢 BINANCE bot çalışıyor hocam")
            last_heartbeat = now

        for symbol in symbols:
            try:
                last_sent = sent_coins.get(symbol, 0)

                if now - last_sent < COOLDOWN_SECONDS:
                    continue

                result = scan_symbol(symbol)

                if result:
                    sent_coins[symbol] = now

                    msg = f"""🚨 BINANCE ERKEN PARA GİRİŞİ

Coin: {result['symbol']}
Fiyat: {result['price']}
Son 15dk Değişim: %{round(result['change'], 2)}
Son 5dk Hacim: {round(result['volume']):,} USDT
Hacim Artışı: {round(result['multiplier'], 2)}x

⚠️ Kontrol:
- 5m mum direnç kırıyor mu?
- Fitil mi bıraktı?
- Hacim devam ediyor mu?"""
                    telegram(msg)

                time.sleep(0.2)

            except Exception as e:
                print(symbol, e)
                continue

        time.sleep(60)

@app.route("/")
def home():
    return "BINANCE erken pump bot aktif", 200

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
