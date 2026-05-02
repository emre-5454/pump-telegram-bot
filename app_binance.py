import ccxt
import time
import requests
import pandas as pd
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60
COOLDOWN = 7200  # aynı coin aynı modda 2 saat tekrar atmaz

exchange = ccxt.binance()
sent_cache = {}

def send_telegram(message):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        print("TELEGRAM:", r.status_code, r.text)
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
        above_mid = last_close > ma20.iloc[-1]

        fake_pump = (
            upper_wick_ratio > 0.45
            or body_ratio < 0.35
            or rsi > 80
        )

        real_pump = (
            body_ratio > 0.50
            and upper_wick_ratio < 0.25
            and volume_ratio > 2
            and rsi < 80
        )

        score = 0
        if bb_width < 0.06:
            score += 2
        if volume_ratio > 2:
            score += 3
        if 50 < rsi < 72:
            score += 2
        if upper_break:
            score += 3

        mode = None

        orta = (
            bb_width < 0.06
            and volume_ratio > 2.0
            and 50 < rsi < 72
            and score >= 7
            and above_mid
            and not fake_pump
        )

        sniper = (
            bb_width < 0.05
            and volume_ratio > 2.5
            and 55 < rsi < 70
            and score >= 9
            and upper_break
            and body_ratio > 0.50
            and upper_wick_ratio < 0.25
            and not fake_pump
            and real_pump
        )

        if sniper:
            mode = "SNIPER"
        elif orta:
            mode = "ORTA"

        if not mode:
            return None

        return {
            "symbol": symbol,
            "mode": mode,
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
        if symbol.endswith("/USDT") and info.get("active", True)
    ]

def run_bot():
    send_telegram("✅ Binance ORTA + SNIPER bot aktif hocam.")

    while True:
        try:
            pairs = get_pairs()

            for symbol in pairs:
                try:
                    result = analyze(symbol)
                    if not result:
                        continue

                    cache_key = f"{result['symbol']}-{result['mode']}"
                    now = time.time()

                    if cache_key in sent_cache and now - sent_cache[cache_key] < COOLDOWN:
                        continue

                    if result["mode"] == "SNIPER":
                        title = "🚨 PUMP HAZIRLIĞI"
                    else:
                        title = "🟡 GÜÇLÜ SETUP"

                    message = f"""
{title}

Mod: {result['mode']}
Borsa: BINANCE
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
"""
                    send_telegram(message)
                    sent_cache[cache_key] = now

                    time.sleep(0.25)

                except Exception as e:
                    print("PAIR HATA:", symbol, e)

            print("TARAMA BİTTİ")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
