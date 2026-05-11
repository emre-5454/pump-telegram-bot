import ccxt
import time
import requests
import math

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

SLEEP_SECONDS = 90
COOLDOWN = 4 * 60 * 60

# =====================
# MEXC CONTINUATION AYARLARI
# =====================
MIN_SCORE = 4

MIN_VOLUME_USDT = 5000
MIN_VOLUME_RATIO = 1.3

MIN_PRICE_CHANGE_5M = 0.00
MAX_PRICE_CHANGE_15M = 2.20

MIN_BODY_RATIO = 0.15
MAX_UPPER_WICK = 0.80

MIN_RSI = 50
MAX_RSI = 72
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

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

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

def bollinger_width(values, period=20):
    if len(values) < period:
        return None

    mid = sma(values, period)
    if not mid:
        return None

    variance = sum((x - mid) ** 2 for x in values[-period:]) / period
    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std

    return (upper - lower) / mid

def candle_power(o, h, l, c):
    rng = h - l
    if rng == 0:
        return 0, 1

    body_ratio = abs(c - o) / rng
    upper_wick = (h - max(o, c)) / rng

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
        candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=240)

        if len(candles) < 220:
            return None

        last = candles[-1]
        prev = candles[-2]

        o = last[1]
        h = last[2]
        l = last[3]
        c = last[4]
        v = last[5]

        closes = [x[4] for x in candles]
        highs = [x[2] for x in candles]
        lows = [x[3] for x in candles]
        volumes = [x[5] for x in candles]

        price_change_5m = ((c - prev[4]) / prev[4]) * 100
        price_change_15m = ((c - candles[-4][4]) / candles[-4][4]) * 100

        avg_volume = sum(volumes[-21:-1]) / 20
        if avg_volume <= 0:
            return None

        volume_ratio = v / avg_volume
        volume_usdt = v * c

        rsi_now = rsi(closes, 14)
        bb_width = bollinger_width(closes, 20)

        ema9 = sma(closes, 9)
        ema21 = sma(closes, 21)
        ema50 = sma(closes, 50)
        ema200 = sma(closes, 200)

        if None in [rsi_now, bb_width, ema9, ema21, ema50, ema200]:
            return None

        body_ratio, upper_wick = candle_power(o, h, l, c)

        # =====================
        # GÜÇLÜ CONTINUATION FİLTRELERİ
        # =====================

        ema_trend = ema9 > ema21 > ema50
        ma200_above = c > ema200

        # Son 5 mumun tepesini kırmış mı?
        recent_high = max(highs[-6:-1])
        breakout = c > recent_high

        # 3 mum hacim artışı
        volume_3_rising = (
            volumes[-1] > volumes[-2]
            and volumes[-2] > volumes[-3]
        )

        # Son dip korundu mu?
        recent_low = min(lows[-6:-1])
        higher_low = l > recent_low

        score = 0
        reasons = []

        if volume_usdt >= MIN_VOLUME_USDT:
            score += 1
            reasons.append("hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim artışı güçlü")

        if volume_ratio >= 5:
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
            reasons.append("mum gövdesi güçlü")

        if upper_wick <= MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil düşük")

        if volume_3_rising:
            score += 1
            reasons.append("3 mum hacim artıyor")

        if ema_trend:
            score += 1
            reasons.append("EMA trend güçlü")

        if ma200_above:
            score += 1
            reasons.append("MA200 üstü")

        if breakout:
            score += 2
            reasons.append("son direnç kırıldı")

        if higher_low:
            score += 1
            reasons.append("son dip korunuyor")

           valid_setup = (
    score >= MIN_SCORE
    and quote_volume >= MIN_1M_VOLUME_USDT
    and volume_ratio >= MIN_VOLUME_RATIO
)

        if not valid_setup:
            return None

        return {
            "symbol": symbol,
            "price": c,
            "score": min(score, 12),
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "volume_usdt": volume_usdt,
            "volume_ratio": volume_ratio,
            "rsi": rsi_now,
            "bb_width": bb_width,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "ema_trend": ema_trend,
            "ma200_above": ma200_above,
            "breakout": breakout,
            "volume_3_rising": volume_3_rising,
            "higher_low": higher_low,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "ema200": ema200,
            "reasons": reasons
        }

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)
        return None

def run():
    telegram("🚀 MEXC CONTINUATION SETUP BOTU başladı hocam")
    print("MEXC CONTINUATION BOT ÇALIŞTI", flush=True)

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
🔥 MEXC CONTINUATION SETUP

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/12

5dk Değişim: %{result['price_change_5m']:.2f}
15dk Değişim: %{result['price_change_15m']:.2f}

Hacim: {int(result['volume_usdt'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

RSI: {result['rsi']:.2f}
BB Genişlik: {result['bb_width']:.4f}

EMA Trend: {'GÜÇLÜ ✅' if result['ema_trend'] else 'ZAYIF ❌'}
MA200 Üstü: {'EVET ✅' if result['ma200_above'] else 'HAYIR ❌'}
Breakout: {'VAR ✅' if result['breakout'] else 'YOK ❌'}
3 Mum Hacim Artışı: {'VAR ✅' if result['volume_3_rising'] else 'YOK ❌'}
Son Dip Korunuyor: {'EVET ✅' if result['higher_low'] else 'HAYIR ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

Kırılan Seviye: {result['recent_high']:.6f}
MA200: {result['ema200']:.6f}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Continuation setup.
Direkt FOMO değil.
Kırılan seviye üstünde kalıcılık + retest bekle.
"""
                telegram(msg)
                sent_cache[symbol] = now

                print("MEXC CONTINUATION:", symbol, "PUAN:", result["score"], flush=True)
                time.sleep(0.25)

            print("MEXC tarama bitti", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(10)

if __name__ == "__main__":
    run()
