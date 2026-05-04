import ccxt
import time
import requests

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

# 🔥 MEXC GEVŞEK AYARLAR
MIN_LAST_VOLUME_USDT = 20000
MIN_VOLUME_MULTIPLIER = 2.5
MIN_PRICE_CHANGE_15M = 0.5
MAX_PRICE_CHANGE_15M = 5
MIN_BODY_RATIO = 0.4

COOLDOWN_SECONDS = 3 * 60 * 60
SLEEP_SECONDS = 60

sent_coins = {}

def telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

def scan_symbol(symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=12)
        if len(candles) < 12:
            return None

        last = candles[-1]
        prev = candles[-2]

        last_open = last[1]
        last_high = last[2]
        last_low = last[3]
        last_close = last[4]
        last_volume = last[5]

        prev_close = prev[4]

        price_change = ((last_close - prev_close) / prev_close) * 100

        candle_range = last_high - last_low
        if candle_range == 0:
            return None

        body = abs(last_close - last_open)
        body_ratio = body / candle_range

        volumes = [c[5] for c in candles[:-1]]
        avg_volume = sum(volumes) / len(volumes)

        if avg_volume == 0:
            return None

        volume_ratio = last_volume / avg_volume

        volume_usdt = last_volume * last_close

        # 🎯 ANA FİLTRE
        if volume_usdt < MIN_LAST_VOLUME_USDT:
            return None

        if volume_ratio < MIN_VOLUME_MULTIPLIER:
            return None

        if price_change < MIN_PRICE_CHANGE_15M or price_change > MAX_PRICE_CHANGE_15M:
            return None

        if body_ratio < MIN_BODY_RATIO:
            return None

        return {
            "symbol": symbol,
            "price": last_close,
            "price_change": price_change,
            "volume_ratio": volume_ratio,
            "volume_usdt": volume_usdt,
            "body_ratio": body_ratio
        }

    except:
        return None

def get_pairs():
    markets = exchange.load_markets()
    return [
        symbol for symbol in markets
        if symbol.endswith("/USDT")
    ]

def run():
    telegram("🚀 MEXC ERKEN PUMP SCANNER başladı hocam")

    while True:
        try:
            pairs = get_pairs()

            for symbol in pairs:
                try:
                    now = time.time()

                    if symbol in sent_coins and now - sent_coins[symbol] < COOLDOWN_SECONDS:
                        continue

                    result = scan_symbol(symbol)
                    if not result:
                        continue

                    msg = f"""
🚨 MEXC PARA GİRİŞİ

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

5dk Değişim: %{result['price_change']:.2f}
Hacim: {int(result['volume_usdt'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

Mum Gücü: {result['body_ratio']:.2f}

⚠️ Kontrol:
- 5m mum güçlü mü?
- Direnç yakın mı?
- Hacim devam ediyor mu?
"""

                    telegram(msg)
                    sent_coins[symbol] = now

                    time.sleep(0.2)

                except:
                    continue

            print("MEXC tarama bitti")
            time.sleep(SLEEP_SECONDS)

        except:
            time.sleep(10)

if __name__ == "__main__":
    run()
