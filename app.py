from flask import Flask
import ccxt
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

MIN_LAST_VOLUME_USDT = 80_000
MIN_VOLUME_MULTIPLIER = 5
MIN_PRICE_CHANGE_15M = 0.2
MAX_PRICE_CHANGE_15M = 2.0
MIN_BODY_RATIO = 0.6

WATCH_CONFIRM_SECONDS = 30 * 60
COOLDOWN_SECONDS = 3 * 60 * 60
HEARTBEAT_SECONDS = 30 * 60

watchlist = {}
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

    if close_price <= open_price:
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
    telegram("✅ MEXC DOUBLE scanner başladı hocam.")

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

                    if not result:
                        continue

                    first_seen = watchlist.get(symbol)

                    if first_seen and now - first_seen <= WATCH_CONFIRM_SECONDS:
                        sent_coins[symbol] = now
                        watchlist.pop(symbol, None)

                        msg = f"""🔥 MEXC ONAY GELDİ

Coin: {result['symbol']}
Fiyat: {result['price']}
Son 15dk Değişim: %{round(result['change'], 2)}
Son 5dk Hacim: {round(result['volume']):,} USDT
Hacim Artışı: {round(result['multiplier'], 2)}x
Mum Gövde Gücü: %{round(result['body_ratio'] * 100, 1)}

✅ İkinci hacim geldi.
🚀 Gerçek pump ihtimali güçlendi.

⚠️ Kontrol:
- Direnç kırıldı mı?
- Fitil uzun mu?
- Hacim devam ediyor mu?"""
                        telegram(msg)

                    else:
                        watchlist[symbol] = now

                        msg = f"""🟡 MEXC İZLEMEYE ALINDI

Coin: {result['symbol']}
Fiyat: {result['price']}
Son 15dk Değişim: %{round(result['change'], 2)}
Son 5dk Hacim: {round(result['volume']):,} USDT
Hacim Artışı: {round(result['multiplier'], 2)}x
Mum Gövde Gücü: %{round(result['body_ratio'] * 100, 1)}

⚠️ İlk para girişi görüldü.
İkinci sinyal gelirse ONAY sayacağız."""
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
    return "MEXC double scanner aktif", 200

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
