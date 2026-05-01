import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"
# AYARLAR
TIMEFRAME = "15m"
SLEEP = 60
COOLDOWN = 3600  # aynı coin 1 saat tekrar atmaz

exchange = ccxt.binance({
    "options": {"defaultType": "future"}
})

sent_cache = {}

# TELEGRAM
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# RSI
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# OI + FUNDING (GÜVENLİ)
def get_oi_funding(symbol):
    oi = 0
    funding = 0

    try:
        data = exchange.fetch_open_interest(symbol)
        oi = data.get("openInterestAmount", 0)
    except:
        pass

    try:
        f = exchange.fetch_funding_rate(symbol)
        funding = f.get("fundingRate", 0)
    except:
        pass

    return oi, funding

# ANALİZ
def analyze(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=50)
        df = pd.DataFrame(ohlcv, columns=["t","o","h","l","c","v"])

        close = df["c"]
        volume = df["v"]

        ma20 = close.rolling(20).mean()
        std = close.rolling(20).std()

        upper = ma20 + 2 * std

        last_price = close.iloc[-1]
        prev_price = close.iloc[-2]

        price_change = ((last_price - prev_price) / prev_price) * 100

        r = rsi(close).iloc[-1]
        vol_ratio = volume.iloc[-1] / volume.rolling(20).mean().iloc[-1]

        oi, funding = get_oi_funding(symbol)

        # FAKE PUMP ENGELİ
        candle_range = df["h"].iloc[-1] - df["l"].iloc[-1]
        body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])

        body_ratio = body / candle_range if candle_range != 0 else 0

        fake = body_ratio < 0.3 or r > 80

        # SİNYAL ŞARTI (BALİNA)
        if (
            vol_ratio > 2.2
            and 52 < r < 72
            and last_price > upper.iloc[-1]
            and funding < 0.01
            and not fake
            and price_change > 0
        ):
            return {
                "price": last_price,
                "rsi": r,
                "vol": vol_ratio,
                "funding": funding,
                "oi": oi
            }

    except:
        return None

    return None

# BOT
def run():
    send("✅ BOT AKTİF (BALİNA MODU)")

    markets = exchange.load_markets()

    while True:
        for symbol in markets:
            try:
                if "/USDT" not in symbol:
                    continue

                if not markets[symbol].get("swap", False):
                    continue

                result = analyze(symbol)

                if not result:
                    continue

                now = time.time()

                if symbol in sent_cache:
                    if now - sent_cache[symbol] < COOLDOWN:
                        continue

                msg = f"""
🚨 BALİNA SİNYALİ

Coin: {symbol}
Fiyat: {result['price']:.6f}

RSI: {result['rsi']:.2f}
Hacim: {result['vol']:.2f}x
Funding: {result['funding']:.5f}
OI: {result['oi']}
"""

                send(msg)
                sent_cache[symbol] = now

                time.sleep(0.2)

            except Exception as e:
                print("PAIR HATA:", symbol, e)

        time.sleep(SLEEP)

# ÇÖKME ENGEL
if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)
