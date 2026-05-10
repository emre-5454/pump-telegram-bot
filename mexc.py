import ccxt
import time
import requests
import math

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

SLEEP_SECONDS = 90
COOLDOWN = 4 * 60 * 60

# Daha gevşek test ayarı
MIN_SCORE = 7

MIN_VOLUME_USDT = 15000
MIN_VOLUME_RATIO = 2.0
MAX_PRICE_CHANGE_15M = 2.5
MIN_PRICE_CHANGE_5M = 0.05
MIN_BODY_RATIO = 0.35
MAX_UPPER_WICK = 0.45
MIN_RSI = 48
MAX_RSI = 75
MAX_BB_WIDTH = 0.080

sent_cache = {}

def telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains, losses = [], []

    for i in range(1, period + 1):
        diff = values[-i] - values[-i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def bollinger_width(values, period=20):
    if len(values) < period:
        return None

    mid = sma(values, period)
    if mid == 0:
        return None

    variance = sum((x - mid) ** 2 for x in values[-period:]) / period
    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std

    return (upper - lower) / mid

def candle_power(open_, high, low, close):
    rng = high - low
    if rng == 0:
        return 0, 1

    body_ratio = abs(close - open_) / rng
    upper_wick = (high - max(open_, close)) / rng

    return body_ratio, upper_wick

def get_pairs():
    markets = exchange.load_markets()
    pairs = []

    blacklist = ["UP/", "DOWN/", "BULL/", "BEAR/"]

    for symbol in markets:
        if not symbol.endswith("/USDT"):
            continue

        if not markets[symbol].get("active", True):
            continue

        if any(x in symbol for x in blacklist):
            continue

        pairs.append(symbol)

    print("MEXC PARİTE SAYISI:", len(pairs), flush=True)
    return pairs

def scan_symbol(symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=60)

        if len(candles) < 30:
            return None

        last = candles[-1]
        prev = candles[-2]

        o = last[1]
        h = last[2]
        l = last[3]
        c = last[4]
        v = last[5]

        closes = [x[4] for x in candles]
        volumes = [x[5] for x in candles]

        price_change_5m = ((c - prev[4]) / prev[4]) * 100
        price_change_15m = ((c - candles[-4][4]) / candles[-4][4]) * 100

        avg_volume = sum(volumes[-21:-1]) / 20
        if avg_volume == 0:
            return None

        volume_ratio = v / avg_volume
        volume_usdt = v * c

        rsi_now = rsi(closes, 14)
        bb_width = bollinger_width(closes, 20)
        body_ratio, upper_wick = candle_power(o, h, l, c)

        ema9 = sma(closes, 9)
        ema21 = sma(closes, 21)

        if rsi_now is None or bb_width is None or ema9 is None or ema21 is None:
            return None

        volume_3_rising = (
            volumes[-1] > volumes[-2]
            and volumes[-2] > volumes[-3]
        )

        ema_trend = c >= ema9 and ema9 >= ema21

        score = 0
        reasons = []

        if volume_usdt >= MIN_VOLUME_USDT:
            score += 1
            reasons.append("hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim artışı güçlü")

        if volume_ratio >= 4:
            score += 1
            reasons.append("hacim agresif")

        if 0 < price_change_15m <= MAX_PRICE_CHANGE_15M:
            score += 1
            reasons.append("fiyat henüz uçmamış")

        if price_change_5m >= MIN_PRICE_CHANGE_5M:
            score += 1
            reasons.append("5dk momentum var")

        if MIN_RSI <= rsi_now <= MAX_RSI:
            score += 1
            reasons.append("RSI uygun")

        if bb_width <= MAX_BB_WIDTH:
            score += 1
            reasons.append("BB uygun")

        if body_ratio >= MIN_BODY_RATIO:
            score += 1
            reasons.append("mum gövdesi yeterli")

        if upper_wick <= MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil kabul edilebilir")

        if volume_3_rising:
            score += 1
            reasons.append("3 mum hacim artıyor")

        if ema_trend:
            score += 1
            reasons.append("EMA trend yukarı")

        valid_setup = (
            score >= MIN_SCORE
            and volume_usdt >= MIN_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and 0 < price_change_15m <= MAX_PRICE_CHANGE_15M
            and body_ratio >= MIN_BODY_RATIO
            and upper_wick <= MAX_UPPER_WICK
            and MIN_RSI <= rsi_now <= MAX_RSI
        )

        if not valid_setup:
            return None

        return {
            "symbol": symbol,
            "price": c,
            "score": min(score, 10),
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "volume_usdt": volume_usdt,
            "volume_ratio": volume_ratio,
            "rsi": rsi_now,
            "bb_width": bb_width,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "volume_3_rising": volume_3_rising,
            "ema_trend": ema_trend,
            "reasons": reasons
        }

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)
        return None

def run():
    telegram("🚀 MEXC TEK MESAJ GÜÇLÜ SETUP BOTU başladı hocam")
    print("MEXC BOT ÇALIŞTI", flush=True)

    while True:
        try:
            pairs = get_pairs()
            now = time.time()

            for symbol in pairs:
                print("Taranıyor:", symbol, flush=True)

                if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
                    continue

                result = scan_symbol(symbol)

                if not result:
                    continue

                msg = f"""
🔥 MEXC GÜÇLÜ SETUP

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/10

5dk Değişim: %{result['price_change_5m']:.2f}
15dk Değişim: %{result['price_change_15m']:.2f}

Hacim: {int(result['volume_usdt'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

RSI: {result['rsi']:.2f}
BB Genişlik: {result['bb_width']:.4f}

3 Mum Hacim Artışı: {'VAR ✅' if result['volume_3_rising'] else 'YOK ❌'}
EMA Trend: {'YUKARI ✅' if result['ema_trend'] else 'ZAYIF ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Tek mesaj güçlü setup.
Direkt FOMO değil.
Direnç kırılımı + retest bekle.
"""
                telegram(msg)
                sent_cache[symbol] = now

                print("MEXC GÜÇLÜ SETUP:", symbol, "PUAN:", result["score"], flush=True)
                time.sleep(0.25)

            print("MEXC tarama bitti", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(10)

if __name__ == "__main__":
    run()
