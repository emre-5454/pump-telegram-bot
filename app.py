from flask import Flask
import ccxt
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

MIN_LAST_VOLUME_USDT = 80_000
MIN_VOLUME_MULTIPLIER = 5
MIN_PRICE_CHANGE_15M = 0.2
MAX_PRICE_CHANGE_15M = 2.5
MIN_BODY_RATIO = 0.6

COOLDOWN_SECONDS = 3*60 * 60
HEARTBEAT_SECONDS = 30 * 60

sent_coins = {}

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)

def scan_symbol(symbol):
    candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=12)

    if len(candles) < 12:
        return None

    last = candles[-1]
    prev = candles[-7:-1]

    open_15m = candles[-4][1]
    close_now = last[4]

    change_15m = ((close_now - open_15m) / open_15m) * 100

    open_price = last[1]
    high = last[2]
    low = last[3]
    close_price = last[4]

    candle_range = high - low
    body = abs(close_price - open_price)

    if candle_range == 0:
        return None

    body_ratio = body / candle_range

    if body_ratio < MIN_BODY_RATIO:
        return None

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
        and close_price > open_price
    ):
        return {
            "symbol": symbol,
            "price": close_now,
            "change": change_15m,
            "volume": last_volume_usdt,
            "multiplier": volume_multiplier,
            "body_ratio": body_ratio
        }

    return None

def scan():
    telegram("✅ MEXC erken pump scanner başladı hocam.")

    markets = exchange.load_markets()
    symbols = [
        s for s in markets
        if s.endswith("/USDT") and markets[s].get("spot")
    ]

    last_heartbeat = 0

    while True:
        try:
            now = time.time()

            if now - last_heartbeat > HEARTBEAT_SECONDS:
                telegram("🟢 MEXC bot çalışıyor hocam")
                last_heartbeat = now

            for symbol in symbols:
                try:
                    if now - sent_coins.get(symbol, 0) < COOLDOWN_SECONDS:
                        continue

                    result = scan_symbol(symbol)

                    if result:
                        sent_coins[symbol] = now

                        msg = f"""🟡 MEXC ERKEN PARA GİRİŞİ

Coin: {result['symbol']}
Fiyat: {result['price']}
Son 15dk Değişim: %{round(result['change'], 2)}
Son 5dk Hacim: {round(result['volume']):,} USDT
Hacim Artışı: {round(result['multiplier'], 2)}x
Mum Gövde Gücü: %{round(result['body_ratio'] * 100, 1)}

⚠️ Kontrol:
- 5m mum güçlü mü?
- Fitil uzun mu?
- Direnç kırıldı mı?
- Hacim devam ediyor mu?"""
                        telegram(msg)

                    time.sleep(0.25)

                except Exception as e:
                    print("COIN HATA:", symbol, e)
                    continue

            time.sleep(60)

        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "MEXC erken pump bot aktif", 200

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
