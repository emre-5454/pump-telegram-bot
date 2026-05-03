import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60
COOLDOWN = 14400  # 4 saat

exchange = ccxt.binance()
sent_cache = {}

def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
    except:
        pass

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        if not ohlcv or len(ohlcv) < 30:
            return None

        df = pd.DataFrame(
            ohlcv,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        close = df["close"]
        volume = df["volume"]

        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20

        bb_width = ((upper - (ma20 - 2 * std20)) / ma20).iloc[-1]
        r = rsi(close).iloc[-1]

        vol_avg = volume.rolling(20).mean().iloc[-1]
        if vol_avg == 0 or pd.isna(vol_avg):
            return None

        volume_ratio = volume.iloc[-1] / vol_avg

        last_open = df["open"].iloc[-1]
        last_high = df["high"].iloc[-1]
        last_low = df["low"].iloc[-1]
        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        price_change = ((last_close - prev_close) / prev_close) * 100

        candle_range = last_high - last_low
        body = abs(last_close - last_open)
        upper_wick = last_high - max(last_close, last_open)

        body_ratio = body / candle_range if candle_range != 0 else 0
        upper_wick_ratio = upper_wick / candle_range if candle_range != 0 else 0

        upper_break = last_close > upper.iloc[-1]

        fake_pump = (
            upper_wick_ratio > 0.45
            or body_ratio < 0.35
            or r > 80
        )

        real_pump = (
            body_ratio > 0.60
            and upper_wick_ratio < 0.20
            and volume_ratio > 3.5
            and r < 80
        )

        score = 0
        if bb_width < 0.05:
            score += 2
        if volume_ratio > 3.0:
            score += 3
        if 52 < r < 70:
            score += 2
        if upper_break:
            score += 3

        sniper = (
            bb_width < 0.04
            and volume_ratio > 3.5
            and 57 < r < 65
            and score >= 9
            and upper_break
            and body_ratio > 0.55
            and upper_wick_ratio < 0.20
            and not fake_pump
            and real_pump
            and price_change > 0
        )

        if not sniper:
            return None

        return {
            "symbol": symbol,
            "price": last_close,
            "price_change": price_change,
            "rsi": r,
            "volume_ratio": volume_ratio,
            "bb_width": bb_width,
            "score": score,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio
        }

    except Exception as e:
        print("HATA:", symbol, e)

    return None

def get_pairs():
    markets = exchange.load_markets()
    return [
        symbol for symbol, info in markets.items()
        if symbol.endswith("/USDT") and info.get("active", True)
    ]

def run_bot():
    send_telegram("🚨 SNIPER BOT AKTİF")

    while True:
        try:
            pairs = get_pairs()

            for symbol in pairs:
                try:
                    now = time.time()

                    if symbol in sent_cache:
                        if now - sent_cache[symbol] < COOLDOWN:
                            continue

                    result = analyze(symbol)
                    if not result:
                        continue

                    message = f"""
🚨 SNIPER SİNYAL

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

RSI: {result['rsi']:.2f}
Hacim: {result['volume_ratio']:.2f}x
Puan: {result['score']}/10

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick_ratio']:.2f}

🔥 GERÇEK PUMP ADAYI
"""
                    send_telegram(message)
                    sent_cache[symbol] = now

                    time.sleep(0.3)

                except Exception as e:
                    print("PAIR HATA:", symbol, e)

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
