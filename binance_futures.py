from flask import Flask
import requests
import threading
import time
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

SLEEP_SECONDS = 75
COOLDOWN = 8 * 60 * 60

MAX_SYMBOLS = 80

# Günlük 8-10 civarı daha kaliteli sinyal hedefi
MIN_SCORE = 8

MIN_1M_VOLUME_USDT = 50000
MIN_VOLUME_RATIO = 4.0
MIN_OI_RATIO = 1.002

MIN_PRICE_CHANGE_1M = 0.05
MIN_3M_CHANGE = 0.20
MAX_PRICE_CHANGE_3M = 2.50

MIN_BODY_RATIO = 0.35
MAX_UPPER_WICK = 0.45

sent_cache = {}
oi_cache = {}

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def get_symbols():
    try:
        data = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            timeout=20
        ).json()
    except Exception as e:
        print("Sembol listeleme hata:", e, flush=True)
        return []

    pairs = []

    for item in data:
        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in ["UP", "DOWN", "BULL", "BEAR"]):
            continue

        try:
            volume = float(item.get("quoteVolume", 0))
        except:
            continue

        pairs.append((symbol, volume))

    pairs.sort(key=lambda x: x[1], reverse=True)

    return [x[0] for x in pairs[:MAX_SYMBOLS]]

def get_klines(symbol, interval="1m", limit=30):
    url = "https://fapi.binance.com/fapi/v1/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    return requests.get(url, params=params, timeout=15).json()

def get_open_interest(symbol):
    url = "https://fapi.binance.com/fapi/v1/openInterest"

    params = {
        "symbol": symbol
    }

    data = requests.get(url, params=params, timeout=10).json()

    return float(data["openInterest"])

def get_1h_trend(symbol):
    try:
        candles = get_klines(symbol, interval="1h", limit=220)

        if not candles or len(candles) < 205:
            return None

        closes = [float(x[4]) for x in candles]

        price = closes[-2]  # kapanmış son 1H mum
        ema9 = sma(closes[:-1], 9)
        ema21 = sma(closes[:-1], 21)
        ma200 = sma(closes[:-1], 200)

        if ema9 is None or ema21 is None or ma200 is None:
            return None

        trend_up = ema9 > ema21
        ma200_above = price > ma200

        return {
            "trend_up": trend_up,
            "ma200_above": ma200_above,
            "price_1h": price,
            "ema9": ema9,
            "ema21": ema21,
            "ma200": ma200
        }

    except Exception as e:
        print("1H trend hata:", symbol, e, flush=True)
        return None

def analyze(symbol):
    try:
        candles = get_klines(symbol, interval="1m", limit=30)

        if not candles or len(candles) < 25:
            return None

        last = candles[-2]
        prev = candles[-3]
        prev3 = candles[-5]

        o = float(last[1])
        h = float(last[2])
        l = float(last[3])
        c = float(last[4])

        quote_volume = float(last[7])

        prev_close = float(prev[4])
        prev3_close = float(prev3[4])

        price_change_1m = ((c - prev_close) / prev_close) * 100
        price_change_3m = ((c - prev3_close) / prev3_close) * 100

        old_volumes = [float(x[7]) for x in candles[-22:-2]]
        avg_volume = sum(old_volumes) / len(old_volumes)

        if avg_volume <= 0:
            return None

        volume_ratio = quote_volume / avg_volume

        candle_range = h - l
        if candle_range <= 0:
            return None

        body_ratio = abs(c - o) / candle_range
        upper_wick = (h - max(o, c)) / candle_range

        oi_now = get_open_interest(symbol)
        prev_oi = oi_cache.get(symbol)
        oi_cache[symbol] = oi_now

        if prev_oi is None or prev_oi <= 0:
            return None

        oi_ratio = oi_now / prev_oi

        trend = get_1h_trend(symbol)

        if not trend:
            return None

        now = time.time()

        if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
            return None

        score = 0
        reasons = []

        if quote_volume >= MIN_1M_VOLUME_USDT:
            score += 1
            reasons.append("1dk futures hacim güçlü")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim artışı güçlü")

        if volume_ratio >= 6:
            score += 1
            reasons.append("hacim agresif")

        if oi_ratio >= MIN_OI_RATIO:
            score += 2
            reasons.append("open interest artıyor")

        if oi_ratio >= 1.01:
            score += 1
            reasons.append("OI güçlü artıyor")

        if price_change_1m >= MIN_PRICE_CHANGE_1M:
            score += 1
            reasons.append("1dk momentum var")

        if MIN_3M_CHANGE <= price_change_3m <= MAX_PRICE_CHANGE_3M:
            score += 1
            reasons.append("3dk momentum uygun")

        if body_ratio >= MIN_BODY_RATIO:
            score += 1
            reasons.append("mum gövdesi yeterli")

        if upper_wick <= MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil kabul edilebilir")

        if trend["trend_up"]:
            score += 1
            reasons.append("1H EMA trend yukarı")

        if trend["ma200_above"]:
            score += 1
            reasons.append("1H MA200 üstü")

        valid_setup = (
            score >= MIN_SCORE
            and quote_volume >= MIN_1M_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and oi_ratio >= MIN_OI_RATIO
            and price_change_1m >= MIN_PRICE_CHANGE_1M
            and price_change_3m >= MIN_3M_CHANGE
            and price_change_3m <= MAX_PRICE_CHANGE_3M
            and body_ratio >= MIN_BODY_RATIO
            and upper_wick <= MAX_UPPER_WICK
            and trend["trend_up"]
            and trend["ma200_above"]
        )

        if not valid_setup:
            return None

        sent_cache[symbol] = now

        return {
            "symbol": symbol,
            "price": c,
            "score": score,
            "quote_volume": quote_volume,
            "volume_ratio": volume_ratio,
            "oi_ratio": oi_ratio,
            "price_change_1m": price_change_1m,
            "price_change_3m": price_change_3m,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "trend_up": trend["trend_up"],
            "ma200_above": trend["ma200_above"],
            "ema9": trend["ema9"],
            "ema21": trend["ema21"],
            "ma200": trend["ma200"],
            "reasons": reasons
        }

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)
        return None

def run_bot():
    send_telegram("🚀 BINANCE FUTURES OI + 1H TREND BOT başladı hocam")
    print("BINANCE FUTURES OI + 1H TREND BOT ÇALIŞTI", flush=True)

    while True:
        try:
            symbols = get_symbols()

            print("Taranan futures coin:", len(symbols), flush=True)

            for symbol in symbols:
                print("Taranıyor:", symbol, flush=True)

                result = analyze(symbol)

                if not result:
                    continue

                msg = f"""
🔥 BINANCE FUTURES OI + 1H TREND SETUP

Coin: {result['symbol'].replace('USDT', '/USDT')}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/12

1dk Değişim: %{result['price_change_1m']:.2f}
3dk Değişim: %{result['price_change_3m']:.2f}

1dk Futures Hacim: {int(result['quote_volume'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

OI Artışı: {result['oi_ratio']:.3f}x

1H EMA Trend: {'YUKARI ✅' if result['trend_up'] else 'ZAYIF ❌'}
1H MA200 Üstü: {'EVET ✅' if result['ma200_above'] else 'HAYIR ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

1H EMA9: {result['ema9']:.6f}
1H EMA21: {result['ema21']:.6f}
1H MA200: {result['ma200']:.6f}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Futures hacim + OI + 1H trend uyumlu.
Direkt FOMO değil.
Direnç kırılımı + retest bekle.
"""
                send_telegram(msg)

                print("TREND OI SETUP:", result["symbol"], "PUAN:", result["score"], flush=True)

                time.sleep(0.2)

            print("Futures tarama bitti", flush=True)

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(10)

@app.route("/")
def home():
    return "Binance Futures OI + 1H Trend Scanner Aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
