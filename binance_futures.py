# =========================================================
# BINANCE FUTURES RENDER ELITE PUMP + SHORT BOT
# ULTRA SIKI FILTRE + BOOKMAP-LITE
# =========================================================

from flask import Flask
import requests
import threading
import time
import os

app = Flask(__name__)

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

# =========================================================
# SETTINGS
# =========================================================

SLEEP_SECONDS = 60

# Daha az coin tara
MAX_SYMBOLS = 50

# Spam azalt
COOLDOWN_PUMP = 12 * 60 * 60
COOLDOWN_SHORT = 12 * 60 * 60

# =========================================================
# ELITE FILTERS
# =========================================================

PUMP_MIN_SCORE = 20
SHORT_MIN_SCORE = 20

PUMP_MIN_VOLUME_USDT = 500000
SHORT_MIN_VOLUME_USDT = 500000

# Çok güçlü hacim ister
PUMP_MIN_VOLUME_RATIO = 6.0
SHORT_MIN_VOLUME_RATIO = 6.0

# Çok güçlü RSI ister
PUMP_MIN_RSI = 78
SHORT_MIN_RSI = 88

# OI
PUMP_MIN_OI_RATIO = 1.0000
PUMP_STRONG_OI_RATIO = 1.0020

SHORT_MIN_OI_RATIO = 1.0030

# =========================================================
# BOOKMAP-LITE
# =========================================================

ORDER_BOOK_LIMIT = 100
ORDER_BOOK_RANGE_PCT = 0.015

ORDER_BOOK_MIN_BID_ASK_RATIO = 1.35
ORDER_BOOK_SHORT_RATIO = 0.65

ORDER_BOOK_MAX_SPREAD_PCT = 0.10

# Büyük duvar zorunlu
WALL_MULTIPLIER = 6.0

WALL_NEAR_PCT = 0.80

# =========================================================
# CACHE
# =========================================================

sent_pump = {}
sent_short = {}
oi_cache = {}

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram eksik", flush=True)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

    except Exception as e:
        print("Telegram hata:", e, flush=True)

# =========================================================
# INDICATORS
# =========================================================

def sma(values, period):

    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema(values, period):

    if len(values) < period:
        return None

    k = 2 / (period + 1)

    e = sum(values[:period]) / period

    for price in values[period:]:
        e = price * k + e * (1 - k)

    return e


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(-period, 0):

        diff = values[i] - values[i - 1]

        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def macd(values):

    if len(values) < 35:
        return None, None, None

    macd_line = ema(values, 12) - ema(values, 26)

    macd_series = []

    for i in range(35, len(values) + 1):

        part = values[:i]

        macd_series.append(
            ema(part, 12) - ema(part, 26)
        )

    signal = ema(macd_series, 9)

    if signal is None:
        return None, None, None

    return macd_line, signal, macd_line - signal


def bollinger_data(values, period=20):

    if len(values) < period:
        return None

    recent = values[-period:]

    mid = sum(recent) / period

    variance = (
        sum((x - mid) ** 2 for x in recent)
        / period
    )

    std = variance ** 0.5

    upper = mid + 2 * std
    lower = mid - 2 * std

    width = (
        (upper - lower) / mid
        if mid != 0 else 0
    )

    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "width": width
    }


def obv(closes, volumes):

    if len(closes) < 21:
        return None, None

    values = [0]

    for i in range(1, len(closes)):

        if closes[i] > closes[i - 1]:
            values.append(values[-1] + volumes[i])

        elif closes[i] < closes[i - 1]:
            values.append(values[-1] - volumes[i])

        else:
            values.append(values[-1])

    return values[-1], sum(values[-20:]) / 20

# =========================================================
# BINANCE
# =========================================================

def get_symbols():

    try:
        data = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            timeout=20
        ).json()

    except Exception as e:
        print("Symbol hata:", e, flush=True)
        return []

    pairs = []

    for item in data:

        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in [
            "UP", "DOWN", "BULL", "BEAR"
        ]):
            continue

        try:
            volume = float(item.get("quoteVolume", 0))

        except:
            continue

        pairs.append((symbol, volume))

    pairs.sort(key=lambda x: x[1], reverse=True)

    return [x[0] for x in pairs[:MAX_SYMBOLS]]


def get_klines(symbol, interval="1m", limit=220):

    try:
        data = requests.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },
            timeout=15
        ).json()

        if isinstance(data, list):
            return data

        return []

    except Exception as e:
        print("Kline hata:", symbol, e, flush=True)
        return []


def get_open_interest(symbol):

    try:
        data = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=10
        ).json()

        return float(data["openInterest"])

    except Exception as e:
        print("OI hata:", symbol, e, flush=True)
        return None

# =========================================================
# CANDLE
# =========================================================

def candle_stats(candle):

    o = float(candle[1])
    h = float(candle[2])
    l = float(candle[3])
    c = float(candle[4])

    candle_range = h - l

    if candle_range <= 0:
        return None

    body_ratio = abs(c - o) / candle_range

    upper_wick = (
        (h - max(o, c)) / candle_range
    )

    lower_wick = (
        (min(o, c) - l) / candle_range
    )

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick
    }

# =========================================================
# BOOKMAP-LITE
# =========================================================

def get_bookmap_lite(symbol, price):

    try:
        data = requests.get(
            "https://fapi.binance.com/fapi/v1/depth",
            params={
                "symbol": symbol,
                "limit": ORDER_BOOK_LIMIT
            },
            timeout=10
        ).json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        spread_pct = (
            (best_ask - best_bid)
            / price
        ) * 100

        low_range = (
            best_bid * (1 - ORDER_BOOK_RANGE_PCT)
        )

        high_range = (
            best_ask * (1 + ORDER_BOOK_RANGE_PCT)
        )

        bid_liq = 0
        ask_liq = 0

        bid_orders = []
        ask_orders = []

        for bid in bids:

            p = float(bid[0])
            q = float(bid[1])

            usdt = p * q

            if low_range <= p <= best_bid:

                bid_liq += usdt
                bid_orders.append((p, usdt))

        for ask in asks:

            p = float(ask[0])
            q = float(ask[1])

            usdt = p * q

            if best_ask <= p <= high_range:

                ask_liq += usdt
                ask_orders.append((p, usdt))

        bid_liq = max(bid_liq, 1)
        ask_liq = max(ask_liq, 1)

        bid_ask_ratio = bid_liq / ask_liq

        spread_ok = (
            spread_pct <= ORDER_BOOK_MAX_SPREAD_PCT
        )

        avg_bid_order = (
            bid_liq / max(len(bid_orders), 1)
        )

        avg_ask_order = (
            ask_liq / max(len(ask_orders), 1)
        )

        biggest_bid = (
            max(bid_orders, key=lambda x: x[1])
            if bid_orders else (0, 0)
        )

        biggest_ask = (
            max(ask_orders, key=lambda x: x[1])
            if ask_orders else (0, 0)
        )

        bid_wall = (
            biggest_bid[1]
            >= avg_bid_order * WALL_MULTIPLIER
        )

        ask_wall = (
            biggest_ask[1]
            >= avg_ask_order * WALL_MULTIPLIER
        )

        bid_wall_near = False
        ask_wall_near = False

        if bid_wall:

            bid_pct = abs(
                (price - biggest_bid[0]) / price
            ) * 100

            bid_wall_near = (
                bid_pct <= WALL_NEAR_PCT
            )

        if ask_wall:

            ask_pct = abs(
                (biggest_ask[0] - price) / price
            ) * 100

            ask_wall_near = (
                ask_pct <= WALL_NEAR_PCT
            )

        return {
            "bid_ask_ratio": bid_ask_ratio,
            "long_confirm":
                bid_ask_ratio >= ORDER_BOOK_MIN_BID_ASK_RATIO
                and spread_ok,

            "short_confirm":
                bid_ask_ratio <= ORDER_BOOK_SHORT_RATIO
                and spread_ok,

            "bid_wall_near": bid_wall_near,
            "ask_wall_near": ask_wall_near
        }

    except Exception as e:
        print("Bookmap hata:", symbol, e, flush=True)
        return None

# =========================================================
# ANALYZE
# =========================================================

def analyze(symbol):

    try:

        candles = get_klines(symbol)

        if not candles or len(candles) < 210:
            return None

        last = candles[-2]
        prev = candles[-3]
        prev3 = candles[-5]

        stats = candle_stats(last)

        if not stats:
            return None

        c = stats["close"]

        closes = [float(x[4]) for x in candles]
        highs = [float(x[2]) for x in candles]
        lows = [float(x[3]) for x in candles]
        volumes = [float(x[7]) for x in candles]

        quote_volume = float(last[7])

        prev_close = float(prev[4])
        prev3_close = float(prev3[4])

        price_change_1m = (
            (c - prev_close)
            / prev_close
        ) * 100

        price_change_3m = (
            (c - prev3_close)
            / prev3_close
        ) * 100

        old_volumes = [
            float(x[7])
            for x in candles[-22:-2]
        ]

        avg_volume = (
            sum(old_volumes)
            / len(old_volumes)
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            quote_volume / avg_volume
        )

        rsi_value = rsi(closes, 14)

        bb = bollinger_data(closes, 20)

        macd_line, macd_signal, macd_hist = macd(closes)

        obv_value, obv_avg = obv(closes, volumes)

        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma200 = sma(closes, 200)

        oi_now = get_open_interest(symbol)

        if oi_now is None:
            return None

        prev_oi = oi_cache.get(symbol)

        oi_cache[symbol] = oi_now

        if prev_oi is None or prev_oi <= 0:
            return None

        oi_ratio = oi_now / prev_oi

        bookmap = get_bookmap_lite(symbol, c)

        recent_high = max(highs[-20:-2])
        recent_low = min(lows[-20:-2])

        breakout = c > recent_high
        breakdown = c < recent_low

        bb_upper_break = False

        if bb:
            bb_upper_break = c > bb["upper"]

        above_ma200 = (
            ma200 is not None
            and c > ma200
        )

        ma_bull = (
            ma20 is not None
            and ma50 is not None
            and ma20 > ma50
        )

        macd_positive = (
            macd_hist is not None
            and macd_hist > 0
        )

        macd_negative = (
            macd_hist is not None
            and macd_hist < 0
        )

        obv_positive = (
            obv_value is not None
            and obv_avg is not None
            and obv_value > obv_avg
        )

        obv_negative = (
            obv_value is not None
            and obv_avg is not None
            and obv_value < obv_avg
        )

        # =================================================
        # HARD FILTER
        # =================================================

        pump_allowed = True

        if oi_ratio < PUMP_MIN_OI_RATIO:
            pump_allowed = False

        if rsi_value is None or rsi_value < PUMP_MIN_RSI:
            pump_allowed = False

        if volume_ratio < PUMP_MIN_VOLUME_RATIO:
            pump_allowed = False

        # En önemli filtre
        if not breakout:
            pump_allowed = False

        # =================================================
        # PUMP SCORE
        # =================================================

        pump_score = 0
        pump_reasons = []

        if pump_allowed:

            if quote_volume >= PUMP_MIN_VOLUME_USDT:
                pump_score += 1
                pump_reasons.append("yüksek hacim")

            if volume_ratio >= PUMP_MIN_VOLUME_RATIO:
                pump_score += 4
                pump_reasons.append("hacim patlaması")

            # Daha güçlü momentum ister
            if price_change_1m >= 0.80:
                pump_score += 2
                pump_reasons.append("1dk sert momentum")

            if 1.80 <= price_change_3m <= 6.50:
                pump_score += 3
                pump_reasons.append("3dk sert momentum")

            if rsi_value >= PUMP_MIN_RSI:
                pump_score += 3
                pump_reasons.append("RSI elit güç")

            if bb_upper_break:
                pump_score += 3
                pump_reasons.append("BB üst bant kırılımı")

            if above_ma200:
                pump_score += 3
                pump_reasons.append("MA200 üstü")

            if ma_bull:
                pump_score += 1
                pump_reasons.append("MA trend pozitif")

            if breakout:
                pump_score += 4
                pump_reasons.append("direnç kırılımı")

            if macd_positive:
                pump_score += 2
                pump_reasons.append("MACD expansion")

            if obv_positive:
                pump_score += 2
                pump_reasons.append("OBV para girişi")

            if stats["body_ratio"] >= 0.65:
                pump_score += 2
                pump_reasons.append("çok güçlü mum")

            if stats["upper_wick"] <= 0.15:
                pump_score += 2
                pump_reasons.append("üst fitil çok düşük")

            if oi_ratio >= PUMP_STRONG_OI_RATIO:
                pump_score += 3
                pump_reasons.append("OI güçlü artış")

            if bookmap and bookmap["long_confirm"]:
                pump_score += 2
                pump_reasons.append("bookmap long baskı")

            if bookmap and bookmap["bid_wall_near"]:
                pump_score += 2
                pump_reasons.append("yakın bid duvarı")

            if bookmap and bookmap["ask_wall_near"]:
                pump_score -= 3
                pump_reasons.append("yakın ask duvarı risk")

        # =================================================
        # SHORT SCORE
        # =================================================

        short_score = 0
        short_reasons = []

        if quote_volume >= SHORT_MIN_VOLUME_USDT:
            short_score += 1
            short_reasons.append("yüksek hacim")

        if volume_ratio >= SHORT_MIN_VOLUME_RATIO:
            short_score += 4
            short_reasons.append("hacim spike")

        if rsi_value is not None and rsi_value >= SHORT_MIN_RSI:
            short_score += 4
            short_reasons.append("RSI aşırı şişmiş")

        if bb_upper_break:
            short_score += 3
            short_reasons.append("BB üst bant dışı")

        if stats["upper_wick"] >= 0.50:
            short_score += 4
            short_reasons.append("üst fitil satış")

        if oi_ratio >= SHORT_MIN_OI_RATIO:
            short_score += 3
            short_reasons.append("OI şişiyor")

        if macd_negative:
            short_score += 2
            short_reasons.append("MACD zayıflıyor")

        if obv_negative:
            short_score += 2
            short_reasons.append("OBV çıkış")

        if bookmap and bookmap["short_confirm"]:
            short_score += 3
            short_reasons.append("bookmap short baskı")

        if bookmap and bookmap["ask_wall_near"]:
            short_score += 3
            short_reasons.append("yakın ask duvarı")

        if bookmap and bookmap["bid_wall_near"]:
            short_score -= 3
            short_reasons.append("yakın bid duvarı risk")

        if breakdown:
            short_score += 3
            short_reasons.append("destek kırılımı")

        now = time.time()

        # =================================================
        # SHORT SIGNAL
        # =================================================

        if short_score >= SHORT_MIN_SCORE:

            last_sent = sent_short.get(symbol)

            if last_sent and now - last_sent < COOLDOWN_SHORT:
                return None

            sent_short[symbol] = now

            return {
                "mode": "SHORT",
                "symbol": symbol,
                "price": c,
                "score": short_score,
                "reasons": short_reasons
            }

        # =================================================
        # PUMP SIGNAL
        # =================================================

        if pump_score >= PUMP_MIN_SCORE:

            last_sent = sent_pump.get(symbol)

            if last_sent and now - last_sent < COOLDOWN_PUMP:
                return None

            sent_pump[symbol] = now

            return {
                "mode": "PUMP",
                "symbol": symbol,
                "price": c,
                "score": pump_score,
                "reasons": pump_reasons
            }

        return None

    except Exception as e:
        print("Analyze hata:", symbol, e, flush=True)
        return None

# =========================================================
# FORMAT
# =========================================================

def format_signal(result):

    if result["mode"] == "SHORT":

        title = "🔴 ELITE SHORT"

    else:

        title = "🚀 ELITE PUMP"

    return f"""
{title}

Coin: {result['symbol']}
Fiyat: {result['price']:.8f}

Skor: {result['score']}

Sebep:
{", ".join(result['reasons'])}
""".strip()

# =========================================================
# LOOP
# =========================================================

def run_bot():

    send_telegram(
        "🚀 ELITE BOOKMAP-LITE BOT AKTIF"
    )

    while True:

        try:

            symbols = get_symbols()

            print(
                "Taranan:",
                len(symbols),
                flush=True
            )

            for symbol in symbols:

                print(
                    "Taraniyor:",
                    symbol,
                    flush=True
                )

                result = analyze(symbol)

                if not result:
                    continue

                msg = format_signal(result)

                send_telegram(msg)

                print(
                    result["mode"],
                    result["symbol"],
                    result["score"],
                    flush=True
                )

                time.sleep(0.30)

            print("Tarama bitti", flush=True)

            time.sleep(SLEEP_SECONDS)

        except Exception as e:

            print("Genel hata:", e, flush=True)

            time.sleep(10)

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "ELITE BOT AKTIF", 200

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
