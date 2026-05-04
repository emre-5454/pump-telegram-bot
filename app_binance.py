from flask import Flask
import ccxt
import time
import requests
import pandas as pd
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60
COOLDOWN = 6 * 60 * 60

exchange = ccxt.binance({"enableRateLimit": True})
sent_cache = {}

def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
    except Exception as e:
        print("TELEGRAM HATA:", e)

def calculate_rsi(series, period=14):
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
        lower = ma20 - 2 * std20

        bb_width = ((upper - lower) / ma20).iloc[-1]
        rsi = calculate_rsi(close).iloc[-1]

        vol_avg = volume.rolling(20).mean().iloc[-1]
        if vol_avg == 0 or pd.isna(vol_avg) or pd.isna(rsi):
            return None

        volume_ratio = volume.iloc[-1] / vol_avg

        last_open = df["open"].iloc[-1]
        last_high = df["high"].iloc[-1]
        last_low = df["low"].iloc[-1]
        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        price_change = ((last_close - prev_close) / prev_close) * 100

        candle_range = last_high - last_low
        if candle_range == 0:
            return None

        body = abs(last_close - last_open)
        upper_wick = last_high - max(last_close, last_open)

        body_ratio = body / candle_range
        upper_wick_ratio = upper_wick / candle_range

        upper_break = last_close > upper.iloc[-1]
        above_mid = last_close > ma20.iloc[-1]

        fake_pump = (
            upper_wick_ratio > 0.25
            or body_ratio < 0.55
            or rsi > 72
            or price_change <= 0
        )

        real_pump = (
            body_ratio > 0.60
            and upper_wick_ratio < 0.20
            and volume_ratio > 3.5
            and 55 < rsi < 70
            and price_change > 0
        )

        score = 0

        if bb_width < 0.05:
            score += 2
        if volume_ratio > 3.5:
            score += 3
        if 55 < rsi < 70:
            score += 2
        if upper_break:
            score += 2
        if above_mid:
            score += 1
        if body_ratio > 0.60:
            score += 1
        if upper_wick_ratio < 0.20:
            score += 1

        if score > 10:
            score = 10

        sniper = (
            score >= 8
            and volume_ratio > 3.5
            and 55 < rsi < 70
            and upper_break
            and above_mid
            and body_ratio > 0.60
            and upper_wick_ratio < 0.20
            and not fake_pump
            and real_pump
        )

        if not sniper:
            return None

        return {
            "symbol": symbol,
            "price": last_close,
            "price_change": price_change,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "bb_width": bb_width,
            "score": score,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio,
            "upper_break": upper_break,
            "above_mid": above_mid,
            "fake_pump": fake_pump,
            "real_pump": real_pump
        }

    except Exception as e:
        print("ANALIZ HATA:", symbol, e)
        return None

def get_pairs():
    markets = exchange.load_markets()
    return [
        symbol for symbol, info in markets.items()
        if symbol.endswith("/USDT") and info.get("spot") and info.get("active", True)
    ]

def run_bot():
    send_telegram("✅ Binance SNIPER / ONAY bot aktif hocam.")

    while True:
        try:
            pairs = get_pairs()

            for symbol in pairs:
                try:
                    now = time.time()

                    if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
                        continue

                    result = analyze(symbol)
                    if not result:
                        continue

                    para_girisi = (
                        result["volume_ratio"] > 3.5
                        and result["body_ratio"] > 0.60
                        and result["price_change"] > 0
                    )

                    message = f"""
🚨 BINANCE SNIPER SİNYAL

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

RSI: {result['rsi']:.2f}
Hacim: {result['volume_ratio']:.2f}x
BB: {result['bb_width']:.4f}
Puan: {result['score']}/10

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick_ratio']:.2f}

Üst Bant Kırılım: {'VAR ✅' if result['upper_break'] else 'YOK ❌'}
Orta Bant Üstü: {'VAR ✅' if result['above_mid'] else 'YOK ❌'}
Fake Pump: {'EVET ❌' if result['fake_pump'] else 'HAYIR ✅'}
Gerçek Pump Gücü: {'VAR ✅' if result['real_pump'] else 'ZAYIF ⚠️'}
Para Girişi: {'GÜÇLÜ 💰' if para_girisi else 'ZAYIF ⚠️'}

📍 Giriş: Retest bekle
🛑 Stop: Son 15m mum altı
🎯 Hedef: Risk x2
"""
                    send_telegram(message)
                    sent_cache[symbol] = now

                    time.sleep(0.3)

                except Exception as e:
                    print("PAIR HATA:", symbol, e)

            print("TARAMA BİTTİ")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "Binance SNIPER bot aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
