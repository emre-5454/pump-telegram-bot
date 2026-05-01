import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"
exchange = ccxt.binance({
    "options": {"defaultType": "future"}
})

def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def safe_oi_funding(symbol):
    oi = 0
    funding = 0

    try:
        oi_data = exchange.fetch_open_interest(symbol)
        oi = oi_data.get("openInterestAmount", 0)
    except:
        pass

    try:
        f = exchange.fetch_funding_rate(symbol)
        funding = f.get("fundingRate", 0)
    except:
        pass

    return oi, funding

def analyze(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, "15m", limit=50)
        df = pd.DataFrame(ohlcv, columns=["t","o","h","l","c","v"])

        close = df["c"]
        volume = df["v"]

        ma20 = close.rolling(20).mean()
        std = close.rolling(20).std()

        upper = ma20 + 2 * std

        r = rsi(close).iloc[-1]
        vol_ratio = volume.iloc[-1] / volume.rolling(20).mean().iloc[-1]
        price = close.iloc[-1]

        oi, funding = safe_oi_funding(symbol)

        # şartlar
        if (
            vol_ratio > 2
            and 50 < r < 75
            and price > upper.iloc[-1]
            and funding < 0.01
        ):
            send(f"""
🚨 BALİNA SİNYALİ

Coin: {symbol}
Fiyat: {price}

RSI: {r:.2f}
Hacim: {vol_ratio:.2f}x
Funding: {funding:.5f}
OI: {oi}
""")

    except:
        pass

def run():
    send("✅ Bot aktif (STABLE)")

    while True:
        try:
            markets = exchange.load_markets()

            for s in markets:
                if "/USDT" in s and markets[s]["swap"]:
                    analyze(s)
                    time.sleep(0.2)

        except Exception as e:
            send(f"HATA: {str(e)}")

        time.sleep(60)

run()
