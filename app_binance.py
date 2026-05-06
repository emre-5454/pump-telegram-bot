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

exchange = ccxt.binance({"enableRateLimit": True})

TIMEFRAME = "15m"
LIMIT = 120
SLEEP_SECONDS = 75

PREP_COOLDOWN = 4 * 60 * 60
CONFIRM_COOLDOWN = 6 * 60 * 60

# 🟡 SIKI ERKEN HAZIRLIK AYARLARI
PREP_MIN_VOLUME_RATIO = 2.2
PREP_MAX_VOLUME_RATIO = 4.5
PREP_MIN_RSI = 54
PREP_MAX_RSI = 65
PREP_MAX_BB_WIDTH = 0.030
PREP_MAX_PRICE_CHANGE = 1.0
PREP_MIN_BODY_RATIO = 0.35
PREP_MAX_UPPER_WICK = 0.40

# 🟢 SNIPER ONAY AYARLARI
CONFIRM_MIN_VOLUME_RATIO = 4.5
CONFIRM_MIN_BODY_RATIO = 0.65
CONFIRM_MAX_UPPER_WICK = 0.15
CONFIRM_MIN_SCORE = 9

prep_cache = {}
confirm_cache = {}

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

def detect_structure(df, lookback=20):
    recent = df.tail(lookback)

    prev_high = recent["high"].iloc[:-1].max()
    prev_low = recent["low"].iloc[:-1].min()

    last_close = recent["close"].iloc[-1]
    last_low = recent["low"].iloc[-1]

    bos = last_close > prev_high
    msb = last_low > prev_low and last_close > recent["close"].rolling(5).mean().iloc[-1]

    return bos, msb, prev_high, prev_low

def analyze(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)

        if not ohlcv or len(ohlcv) < 60:
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

        if vol_avg == 0 or pd.isna(vol_avg) or pd.isna(rsi) or pd.isna(bb_width):
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

        body_ratio = abs(last_close - last_open) / candle_range
        upper_wick_ratio = (last_high - max(last_close, last_open)) / candle_range

        upper_break = last_close > upper.iloc[-1]
        above_mid = last_close > ma20.iloc[-1]

        bos, msb, prev_high, prev_low = detect_structure(df)

        volume_3_candle_rising = (
            volume.iloc[-1] > volume.iloc[-2]
            and volume.iloc[-2] > volume.iloc[-3]
        )

        fake_pump = (
            upper_wick_ratio > CONFIRM_MAX_UPPER_WICK
            or body_ratio < CONFIRM_MIN_BODY_RATIO
            or rsi > 75
            or price_change <= 0
        )

        score = 0

        if volume_ratio >= CONFIRM_MIN_VOLUME_RATIO:
            score += 2
        if volume_ratio >= 5:
            score += 1
        if body_ratio >= CONFIRM_MIN_BODY_RATIO:
            score += 2
        if upper_wick_ratio <= CONFIRM_MAX_UPPER_WICK:
            score += 1
        if 55 <= rsi <= 70:
            score += 1
        if upper_break:
            score += 1
        if above_mid:
            score += 1
        if bos:
            score += 1
        if msb:
            score += 1

        score = min(score, 10)

        # 🟡 ERKEN HAZIRLIK
        prep_setup = (
            PREP_MIN_VOLUME_RATIO <= volume_ratio <= PREP_MAX_VOLUME_RATIO
            and PREP_MIN_RSI <= rsi <= PREP_MAX_RSI
            and bb_width <= PREP_MAX_BB_WIDTH
            and price_change <= PREP_MAX_PRICE_CHANGE
            and price_change > -0.30
            and body_ratio >= PREP_MIN_BODY_RATIO
            and upper_wick_ratio <= PREP_MAX_UPPER_WICK
            and above_mid
            and volume_3_candle_rising
            and not upper_break
        )

        # 🟢 SNIPER ONAY
        confirm_setup = (
            score >= CONFIRM_MIN_SCORE
            and volume_ratio >= CONFIRM_MIN_VOLUME_RATIO
            and body_ratio >= CONFIRM_MIN_BODY_RATIO
            and upper_wick_ratio <= CONFIRM_MAX_UPPER_WICK
            and above_mid
            and not fake_pump
            and (bos or upper_break)
        )

        if not prep_setup and not confirm_setup:
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
            "bos": bos,
            "msb": msb,
            "prev_high": prev_high,
            "prev_low": prev_low,
            "fake_pump": fake_pump,
            "prep_setup": prep_setup,
            "confirm_setup": confirm_setup,
            "volume_3_candle_rising": volume_3_candle_rising
        }

    except Exception as e:
        print("ANALIZ HATA:", symbol, e)
        return None

def get_pairs():
    markets = exchange.load_markets()

    blacklist = ["UP/", "DOWN/", "BULL/", "BEAR/"]

    pairs = []

    for symbol, info in markets.items():
        if not symbol.endswith("/USDT"):
            continue

        if not info.get("spot"):
            continue

        if not info.get("active", True):
            continue

        if any(x in symbol for x in blacklist):
            continue

        pairs.append(symbol)

    return pairs

def run_bot():
    send_telegram("✅ BINANCE SIKI ERKEN PUMP + STRUCTURE SNIPER aktif hocam.")

    while True:
        try:
            pairs = get_pairs()
            now = time.time()

            for symbol in pairs:
                try:
                    result = analyze(symbol)

                    if not result:
                        continue

                    # 🟡 HAZIRLIK SİNYALİ
                    if result["prep_setup"]:
                        if symbol not in prep_cache or now - prep_cache[symbol] > PREP_COOLDOWN:
                            message = f"""
🟡 BINANCE PUMP HAZIRLIĞI

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}
15m Değişim: %{result['price_change']:.2f}

RSI: {result['rsi']:.2f}
Hacim: {result['volume_ratio']:.2f}x
BB Genişlik: {result['bb_width']:.4f}

3 Mum Hacim Artışı: {'VAR ✅' if result['volume_3_candle_rising'] else 'YOK ❌'}
Orta Bant Üstü: {'VAR ✅' if result['above_mid'] else 'YOK ❌'}
BB Üst Bant Kırılım: {'VAR ✅' if result['upper_break'] else 'YOK ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick_ratio']:.2f}

📍 Karar:
Erken hazırlık var.
Direkt long değil.
Direnç kırılımı + retest bekle.
"""
                            send_telegram(message)
                            prep_cache[symbol] = now
                            time.sleep(0.3)

                    # 🟢 ONAY SİNYALİ
                    if result["confirm_setup"]:
                        if symbol not in confirm_cache or now - confirm_cache[symbol] > CONFIRM_COOLDOWN:
                            message = f"""
🟢 BINANCE STRUCTURE SETUP

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}
15m Değişim: %{result['price_change']:.2f}

Skor: {result['score']}/10

RSI: {result['rsi']:.2f}
Hacim: {result['volume_ratio']:.2f}x
BB Genişlik: {result['bb_width']:.4f}

BOS: {'VAR ✅' if result['bos'] else 'YOK ❌'}
MSB: {'VAR ✅' if result['msb'] else 'YOK ❌'}
BB Üst Bant Kırılım: {'VAR ✅' if result['upper_break'] else 'YOK ❌'}
Orta Bant Üstü: {'VAR ✅' if result['above_mid'] else 'YOK ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick_ratio']:.2f}
Fake Pump: {'EVET ❌' if result['fake_pump'] else 'HAYIR ✅'}

Kırılan Seviye: {result['prev_high']:.6f}

📍 Karar: Retest bekle
🛑 Stop: Kırılan seviye altı / son dip
🎯 Hedef: Risk x2
"""
                            send_telegram(message)
                            confirm_cache[symbol] = now
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
    return "Binance sıkı erken pump + structure sniper aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
