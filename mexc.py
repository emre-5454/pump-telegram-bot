import ccxt
import time
import requests
import math

# =========================================================
# BOT BİLGİSİ
# =========================================================
BOT_NAME = "☁️ RENDER MEXC BOT"

# =========================================================
# TELEGRAM
# =========================================================
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

def telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

    except Exception as e:

        print("Telegram hata:", e)

# =========================================================
# BORSA
# =========================================================
exchange = ccxt.mexc({
    "enableRateLimit": True
})

# =========================================================
# AYARLAR
# =========================================================
TIMEFRAME = "5m"

SLEEP_SECONDS = 90

COOLDOWN_PREP = 3 * 60 * 60
COOLDOWN_CONFIRM = 6 * 60 * 60

# =========================================================
# HAZIRLIK AYARLARI
# =========================================================
PREP_MIN_SCORE = 6

PREP_MIN_VOLUME_USDT = 20000
PREP_MIN_VOLUME_RATIO = 1.8

PREP_MAX_PRICE_CHANGE_15M = 1.2
PREP_MIN_PRICE_CHANGE_5M = 0.03

PREP_MIN_BODY_RATIO = 0.30
PREP_MAX_UPPER_WICK = 0.45

PREP_MIN_RSI = 48
PREP_MAX_RSI = 68

PREP_MAX_BB_WIDTH = 0.045

# =========================================================
# ONAY AYARLARI
# =========================================================
CONFIRM_MIN_SCORE = 9

CONFIRM_MIN_VOLUME_USDT = 50000
CONFIRM_MIN_VOLUME_RATIO = 4.0

CONFIRM_MIN_PRICE_CHANGE_5M = 0.25
CONFIRM_MAX_PRICE_CHANGE_15M = 4.0

CONFIRM_MIN_BODY_RATIO = 0.55
CONFIRM_MAX_UPPER_WICK = 0.25

CONFIRM_MIN_RSI = 55
CONFIRM_MAX_RSI = 78

# =========================================================
# CACHE
# =========================================================
sent_prep = {}
sent_confirm = {}

# =========================================================
# RSI
# =========================================================
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

# =========================================================
# SMA
# =========================================================
def sma(values, period):

    if len(values) < period:
        return None

    return sum(values[-period:]) / period

# =========================================================
# EMA
# =========================================================
def ema(values, period):

    if len(values) < period:
        return None

    k = 2 / (period + 1)

    ema_value = values[0]

    for price in values[1:]:

        ema_value = (
            price * k
            +
            ema_value * (1 - k)
        )

    return ema_value

# =========================================================
# BB WIDTH
# =========================================================
def bollinger_width(values, period=20):

    if len(values) < period:
        return None

    mid = sma(values, period)

    if mid == 0:
        return None

    variance = sum(
        (x - mid) ** 2
        for x in values[-period:]
    ) / period

    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std

    return (upper - lower) / mid

# =========================================================
# MUM GÜCÜ
# =========================================================
def candle_power(open_, high, low, close):

    rng = high - low

    if rng == 0:
        return 0, 1

    body_ratio = abs(close - open_) / rng

    upper_wick = (
        high - max(open_, close)
    ) / rng

    return body_ratio, upper_wick

# =========================================================
# PAIRS
# =========================================================
def get_pairs():

    markets = exchange.load_markets()

    pairs = []

    blacklist = [
        "UP/",
        "DOWN/",
        "BULL/",
        "BEAR/"
    ]

    for symbol in markets:

        if not symbol.endswith("/USDT"):
            continue

        if not markets[symbol].get("active", True):
            continue

        if any(x in symbol for x in blacklist):
            continue

        pairs.append(symbol)

    return pairs

# =========================================================
# ANALİZ
# =========================================================
def analyze(symbol):

    try:

        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=120
        )

        if len(candles) < 50:
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

        # =====================================================
        # FİYAT DEĞİŞİMİ
        # =====================================================
        price_change_5m = (
            (c - prev[4]) / prev[4]
        ) * 100

        price_change_15m = (
            (c - candles[-4][4]) / candles[-4][4]
        ) * 100

        # =====================================================
        # HACİM
        # =====================================================
        avg_volume = sum(
            volumes[-21:-1]
        ) / 20

        if avg_volume == 0:
            return None

        volume_ratio = v / avg_volume
        volume_usdt = v * c

        # =====================================================
        # RSI
        # =====================================================
        rsi_now = rsi(closes, 14)

        # =====================================================
        # BB
        # =====================================================
        bb_width = bollinger_width(closes, 20)

        # =====================================================
        # MUM
        # =====================================================
        body_ratio, upper_wick = candle_power(
            o, h, l, c
        )

        # =====================================================
        # EMA
        # =====================================================
        ema9 = ema(closes[-30:], 9)
        ema21 = ema(closes[-30:], 21)

        ema_trend = (
            c >= ema9
            and
            ema9 >= ema21
        )

        # =====================================================
        # HACİM YÜKSELİYOR MU
        # =====================================================
        volume_3_rising = (
            volumes[-1] > volumes[-2]
            and
            volumes[-2] > volumes[-3]
        )

        # =====================================================
        # SCORE
        # =====================================================
        score = 0
        reasons = []

        if volume_usdt >= PREP_MIN_VOLUME_USDT:
            score += 1
            reasons.append("hacim yeterli")

        if volume_ratio >= PREP_MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim artışı güçlü")

        if volume_ratio >= 4:
            score += 1
            reasons.append("agresif hacim")

        if 0 < price_change_15m <= PREP_MAX_PRICE_CHANGE_15M:
            score += 1
            reasons.append("fiyat henüz uçmamış")

        if price_change_5m >= PREP_MIN_PRICE_CHANGE_5M:
            score += 1
            reasons.append("momentum başlıyor")

        if PREP_MIN_RSI <= rsi_now <= PREP_MAX_RSI:
            score += 1
            reasons.append("RSI uygun")

        if bb_width <= PREP_MAX_BB_WIDTH:
            score += 1
            reasons.append("BB sıkışık")

        if body_ratio >= PREP_MIN_BODY_RATIO:
            score += 1
            reasons.append("mum güçlü")

        if upper_wick <= PREP_MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil düşük")

        if volume_3_rising:
            score += 1
            reasons.append("3 mum hacim artıyor")

        if ema_trend:
            score += 1
            reasons.append("EMA trend yukarı")

        # =====================================================
        # HAZIRLIK
        # =====================================================
        prep_valid = (

            score >= PREP_MIN_SCORE

            and
            volume_usdt >= PREP_MIN_VOLUME_USDT

            and
            volume_ratio >= PREP_MIN_VOLUME_RATIO

            and
            0 < price_change_15m <= PREP_MAX_PRICE_CHANGE_15M

            and
            PREP_MIN_RSI <= rsi_now <= PREP_MAX_RSI
        )

        # =====================================================
        # ONAY
        # =====================================================
        confirm_valid = (

            score >= CONFIRM_MIN_SCORE

            and
            volume_usdt >= CONFIRM_MIN_VOLUME_USDT

            and
            volume_ratio >= CONFIRM_MIN_VOLUME_RATIO

            and
            price_change_5m >= CONFIRM_MIN_PRICE_CHANGE_5M

            and
            0 < price_change_15m <= CONFIRM_MAX_PRICE_CHANGE_15M

            and
            body_ratio >= CONFIRM_MIN_BODY_RATIO

            and
            upper_wick <= CONFIRM_MAX_UPPER_WICK

            and
            CONFIRM_MIN_RSI <= rsi_now <= CONFIRM_MAX_RSI

            and
            ema_trend
        )

        return {

            "symbol": symbol,
            "price": c,

            "score": score,

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

            "prep_valid": prep_valid,
            "confirm_valid": confirm_valid,

            "reasons": reasons
        }

    except Exception as e:

        print("Analiz hata:", symbol, e)

        return None

# =========================================================
# RUN
# =========================================================
def run():

    telegram(
        f"{BOT_NAME} aktif edildi hocam 🚀"
    )

    while True:

        try:

            pairs = get_pairs()

            now = time.time()

            for symbol in pairs:

                result = analyze(symbol)

                if not result:
                    continue

                # =================================================
                # HAZIRLIK
                # =================================================
                if result["prep_valid"]:

                    if (
                        symbol not in sent_prep
                        or
                        now - sent_prep[symbol]
                        > COOLDOWN_PREP
                    ):

                        msg = f"""
{BOT_NAME}

🟡 MEXC HAZIRLIK

Coin:
{result['symbol']}

Fiyat:
{result['price']:.8f}

Skor:
{result['score']}/11

5dk Değişim:
%{result['price_change_5m']:.2f}

15dk Değişim:
%{result['price_change_15m']:.2f}

USDT Hacim:
{int(result['volume_usdt'])}

Hacim Artışı:
{result['volume_ratio']:.2f}x

RSI:
{result['rsi']:.2f}

BB Width:
{result['bb_width']:.4f}

Mum Gücü:
{result['body_ratio']:.2f}

Üst Fitil:
{result['upper_wick']:.2f}

EMA Trend:
{'YUKARI ✅' if result['ema_trend'] else 'ZAYIF ❌'}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Pump öncesi hazırlık olabilir.
Direkt giriş değil.
Takibe al.
"""

                        telegram(msg)

                        sent_prep[symbol] = now

                        print("PREP:", symbol)

                        time.sleep(0.2)

                # =================================================
                # ONAY
                # =================================================
                if result["confirm_valid"]:

                    if (
                        symbol not in sent_confirm
                        or
                        now - sent_confirm[symbol]
                        > COOLDOWN_CONFIRM
                    ):

                        msg = f"""
{BOT_NAME}

🔥 MEXC GÜÇLÜ SETUP

Coin:
{result['symbol']}

Fiyat:
{result['price']:.8f}

Skor:
{result['score']}/11

5dk Değişim:
%{result['price_change_5m']:.2f}

15dk Değişim:
%{result['price_change_15m']:.2f}

USDT Hacim:
{int(result['volume_usdt'])}

Hacim Artışı:
{result['volume_ratio']:.2f}x

RSI:
{result['rsi']:.2f}

BB Width:
{result['bb_width']:.4f}

Mum Gücü:
{result['body_ratio']:.2f}

Üst Fitil:
{result['upper_wick']:.2f}

3 Mum Hacim:
{'YÜKSELİYOR ✅' if result['volume_3_rising'] else 'ZAYIF ❌'}

EMA Trend:
{'YUKARI ✅' if result['ema_trend'] else 'ZAYIF ❌'}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Güçlü breakout setup.
Direkt FOMO değil.
Direnç kırılımı + retest bekle.
"""

                        telegram(msg)

                        sent_confirm[symbol] = now

                        print("CONFIRM:", symbol)

                        time.sleep(0.2)

            print("Tarama tamamlandı")

            time.sleep(SLEEP_SECONDS)

        except Exception as e:

            print("Genel hata:", e)

            time.sleep(10)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    run()
