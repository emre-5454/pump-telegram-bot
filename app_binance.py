import ccxt, time, requests
import pandas as pd
import numpy as np

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60

exchanges = {
    "BINANCE": ccxt.binance(),
    "MEXC": ccxt.mexc()
}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(df):
    close = df["close"]
    volume = df["volume"]

    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()

    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20

    bb_width = (upper - lower) / ma20
    rsi_val = rsi(close)

    vol_avg = volume.rolling(20).mean()
    volume_ratio = volume / vol_avg

    last = df.iloc[-1]

    score = 0

    bb_squeeze = bb_width.iloc[-1] < 0.08
    vol_early = volume_ratio.iloc[-1] > 1.5
    vol_pump = volume_ratio.iloc[-1] > 2
    rsi_early = rsi_val.iloc[-1] > 45
    rsi_pump = rsi_val.iloc[-1] > 50
    above_mid = close.iloc[-1] > ma20.iloc[-1]
    upper_break = close.iloc[-1] > upper.iloc[-1]

    if bb_squeeze:
        score += 2
    if vol_early:
        score += 3
    if rsi_early:
        score += 2
    if upper_break:
        score += 3

    return {
        "price": close.iloc[-1],
        "rsi": rsi_val.iloc[-1],
        "bb_width": bb_width.iloc[-1],
        "volume_ratio": volume_ratio.iloc[-1],
        "score": score,
        "early": bb_squeeze and vol_early and rsi_early and above_mid,
        "pump": bb_squeeze and vol_pump and rsi_pump and upper_break
    }

def get_usdt_pairs(exchange):
    markets = exchange.load_markets()
    return [
        s for s in markets
        if s.endswith("/USDT") and markets[s].get("active", True)
    ]

sent_cache = {}

while True:
    for ex_name, exchange in exchanges.items():
        try:
            pairs = get_usdt_pairs(exchange)

            for symbol in pairs:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
                    df = pd.DataFrame(
                        ohlcv,
                        columns=["time", "open", "high", "low", "close", "volume"]
                    )

                    result = analyze(df)
                    cache_key = f"{ex_name}-{symbol}"

                    if result["pump"] and sent_cache.get(cache_key) != "pump":
                        msg = f"""
🚨 PUMP HAZIRLIĞI

Borsa: {ex_name}
Coin: {symbol}
Fiyat: {result['price']:.6f}
RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
BB Width: {result['bb_width']:.4f}
Puan: {result['score']}/10

Sinyal: ÜST BANT KIRILIM + HACİM
"""
                        send_telegram(msg)
                        sent_cache[cache_key] = "pump"

                    elif result["early"] and result["score"] >= 5 and sent_cache.get(cache_key) != "early":
                        msg = f"""
🟡 ERKEN PARA GİRİŞİ

Borsa: {ex_name}
Coin: {symbol}
Fiyat: {result['price']:.6f}
RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
BB Width: {result['bb_width']:.4f}
Puan: {result['score']}/10

Sinyal: ORTA BANT ÜSTÜ + HACİM ARTIŞI
"""
                        send_telegram(msg)
                        sent_cache[cache_key] = "early"

                    time.sleep(0.2)

                except Exception:
                    continue

        except Exception as e:
            send_telegram(f"⚠️ {ex_name} hata: {str(e)}")

    time.sleep(SLEEP_SECONDS)
