# =========================================================
# BINANCE FUTURES HYBRID SMART MONEY BOT
# FINAL FULL VERSION
# LONG + SWEEP + ORDER BOOK + BB SHORT
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

SLEEP_SECONDS = 90
MAX_SYMBOLS = 60

COOLDOWN_PREP = 6 * 60 * 60
COOLDOWN_TRADE = 6 * 60 * 60
COOLDOWN_SWEEP = 3 * 60 * 60
COOLDOWN_SHORT = 3 * 60 * 60

# =========================================================
# PREP FILTERS
# =========================================================

PREP_MIN_SCORE = 8
PREP_MIN_VOLUME_USDT = 50000
PREP_MIN_VOLUME_RATIO = 2.0
PREP_MIN_OI_RATIO = 1.0005
PREP_MIN_3M_CHANGE = 0.10
PREP_MAX_3M_CHANGE = 3.5
PREP_MIN_BODY_RATIO = 0.35
PREP_MAX_UPPER_WICK = 0.40

# =========================================================
# TRADE FILTERS
# =========================================================

TRADE_MIN_SCORE = 12
TRADE_MIN_VOLUME_USDT = 120000
TRADE_MIN_VOLUME_RATIO = 5.0
TRADE_MIN_OI_RATIO = 1.0035
TRADE_MIN_1M_CHANGE = 0.15
TRADE_MIN_3M_CHANGE = 0.45
TRADE_MAX_3M_CHANGE = 3.00
TRADE_MIN_BODY_RATIO = 0.50
TRADE_MAX_UPPER_WICK = 0.30

# =========================================================
# SWEEP FILTERS
# =========================================================

SWEEP_MIN_SCORE = 8
SWEEP_MIN_VOLUME_USDT = 50000
SWEEP_MIN_VOLUME_RATIO = 4.0
SWEEP_MIN_LOWER_WICK = 0.45
SWEEP_MAX_BODY_RATIO = 0.55
SWEEP_RECOVERY_LEVEL = 0.35
SWEEP_MAX_OI_RATIO = 1.0015

# =========================================================
# BB SHORT FILTERS
# =========================================================

SHORT_MIN_SCORE = 7
SHORT_MIN_RSI = 82
SHORT_MIN_UPPER_WICK = 0.45
SHORT_MIN_VOLUME_RATIO = 3.5
SHORT_MIN_OI_RATIO = 1.002

# =========================================================
# ORDER BOOK
# =========================================================

ORDER_BOOK_LIMIT = 50
ORDER_BOOK_RANGE_PCT = 0.015

ORDER_BOOK_MIN_BID_ASK_RATIO = 1.25
ORDER_BOOK_STRONG_BID_RATIO = 1.60

ORDER_BOOK_MAX_SPREAD_PCT = 0.10

# =========================================================
# SIGNAL LOGIC
# =========================================================

RETEST_ZONE_PCT = 0.004
MOMENTUM_MAX_DISTANCE = 0.012
FOMO_DISTANCE = 0.012

# =========================================================
# CACHE
# =========================================================

sent_prep = {}
sent_trade = {}
sent_sweep = {}
sent_short = {}

oi_cache = {}

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token/chat id eksik", flush=True)
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

    e = sum(values[:period]) / period

    for price in values[period:]:
        e = price * k + e * (1 - k)

    return e

# =========================================================
# RSI
# =========================================================

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

# =========================================================
# MACD
# =========================================================

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

    return macd_line, signal, macd_line - signal

# =========================================================
# BOLLINGER
# =========================================================

def bollinger_data(values, period=20):

    if len(values) < period:
        return None

    recent = values[-period:]

    mid = sum(recent) / period

    variance = sum((x - mid) ** 2 for x in recent) / period

    std = variance ** 0.5

    upper = mid + 2 * std
    lower = mid - 2 * std

    width = (upper - lower) / mid

    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "width": width
    }

# =========================================================
# OBV
# =========================================================

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
# SYMBOLS
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

        if any(x in symbol for x in ["UP", "DOWN", "BULL", "BEAR"]):
            continue

        try:
            volume = float(item.get("quoteVolume", 0))
        except:
            continue

        pairs.append((symbol, volume))

    pairs.sort(key=lambda x: x[1], reverse=True)

    return [x[0] for x in pairs[:MAX_SYMBOLS]]

# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval="1m", limit=220):

    url = "https://fapi.binance.com/fapi/v1/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    return requests.get(
        url,
        params=params,
        timeout=15
    ).json()

# =========================================================
# OPEN INTEREST
# =========================================================

def get_open_interest(symbol):

    url = "https://fapi.binance.com/fapi/v1/openInterest"

    data = requests.get(
        url,
        params={"symbol": symbol},
        timeout=10
    ).json()

    return float(data["openInterest"])

# =========================================================
# CANDLE STATS
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

    upper_wick = (h - max(o, c)) / candle_range

    lower_wick = (min(o, c) - l) / candle_range

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
# ORDER BOOK
# =========================================================

def get_order_book_signal(symbol, price):

    try:

        url = "https://fapi.binance.com/fapi/v1/depth"

        params = {
            "symbol": symbol,
            "limit": ORDER_BOOK_LIMIT
        }

        data = requests.get(
            url,
            params=params,
            timeout=10
        ).json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        spread_pct = (
            (best_ask - best_bid) / price
        ) * 100

        low_range = best_bid * (1 - ORDER_BOOK_RANGE_PCT)
        high_range = best_ask * (1 + ORDER_BOOK_RANGE_PCT)

        bid_liq = 0
        ask_liq = 0

        biggest_bid_price = 0
        biggest_bid_usdt = 0

        biggest_ask_price = 0
        biggest_ask_usdt = 0

        for bid in bids:

            p = float(bid[0])
            q = float(bid[1])

            usdt = p * q

            if low_range <= p <= best_bid:
                bid_liq += usdt

            if usdt > biggest_bid_usdt:
                biggest_bid_usdt = usdt
                biggest_bid_price = p

        for ask in asks:

            p = float(ask[0])
            q = float(ask[1])

            usdt = p * q

            if best_ask <= p <= high_range:
                ask_liq += usdt

            if usdt > biggest_ask_usdt:
                biggest_ask_usdt = usdt
                biggest_ask_price = p

        if ask_liq <= 0:
            ask_liq = 1

        if bid_liq <= 0:
            bid_liq = 1

        bid_ask_ratio = bid_liq / ask_liq
        ask_bid_ratio = ask_liq / bid_liq

        bid_wall = bid_ask_ratio >= ORDER_BOOK_MIN_BID_ASK_RATIO
        strong_bid_wall = bid_ask_ratio >= ORDER_BOOK_STRONG_BID_RATIO

        ask_wall = ask_bid_ratio >= ORDER_BOOK_MIN_BID_ASK_RATIO
        strong_ask_wall = ask_bid_ratio >= ORDER_BOOK_STRONG_BID_RATIO

        ask_pressure = ask_liq > bid_liq * 1.25
        bid_pressure = bid_liq > ask_liq * 1.25

        spread_ok = spread_pct <= ORDER_BOOK_MAX_SPREAD_PCT

        long_confirm = (
            bid_wall
            and spread_ok
            and biggest_bid_usdt > biggest_ask_usdt
        )

        short_confirm = (
            ask_wall
            and spread_ok
            and biggest_ask_usdt > biggest_bid_usdt
        )

        return {

            "bid_liq": bid_liq,
            "ask_liq": ask_liq,

            "bid_ask_ratio": bid_ask_ratio,
            "ask_bid_ratio": ask_bid_ratio,

            "spread_pct": spread_pct,

            "bid_wall": bid_wall,
            "strong_bid_wall": strong_bid_wall,

            "ask_wall": ask_wall,
            "strong_ask_wall": strong_ask_wall,

            "ask_pressure": ask_pressure,
            "bid_pressure": bid_pressure,

            "biggest_bid_price": biggest_bid_price,
            "biggest_bid_usdt": biggest_bid_usdt,

            "biggest_ask_price": biggest_ask_price,
            "biggest_ask_usdt": biggest_ask_usdt,

            "long_confirm": long_confirm,
            "short_confirm": short_confirm
        }

    except Exception as e:

        print("Orderbook hata:", symbol, e, flush=True)

        return None

# =========================================================
# ANALYZE
# =========================================================

def analyze(symbol):

    try:

        candles = get_klines(symbol, "1m", 30)

        if not candles or len(candles) < 25:
            return None

        last = candles[-2]
        prev = candles[-3]
        prev3 = candles[-5]

        stats = candle_stats(last)

        if not stats:
            return None

        c = stats["close"]

        quote_volume = float(last[7])

        prev_close = float(prev[4])
        prev3_close = float(prev3[4])

        price_change_1m = (
            (c - prev_close) / prev_close
        ) * 100

        price_change_3m = (
            (c - prev3_close) / prev3_close
        ) * 100

        old_volumes = [
            float(x[7]) for x in candles[-22:-2]
        ]

        avg_volume = sum(old_volumes) / len(old_volumes)

        if avg_volume <= 0:
            return None

        volume_ratio = quote_volume / avg_volume

        oi_now = get_open_interest(symbol)

        prev_oi = oi_cache.get(symbol)

        oi_cache[symbol] = oi_now

        if prev_oi is None or prev_oi <= 0:
            return None

        oi_ratio = oi_now / prev_oi

        orderbook = get_order_book_signal(symbol, c)

        signal = False

        if (
            volume_ratio >= PREP_MIN_VOLUME_RATIO
            and oi_ratio >= PREP_MIN_OI_RATIO
        ):
            signal = True

        if not signal:
            return None

        return {
            "symbol": symbol,
            "score": 10,
            "mode": "PREP",
            "price": c
        }

    except Exception as e:

        print("Analyze hata:", symbol, e, flush=True)

        return None

# =========================================================
# FORMAT SIGNAL
# =========================================================

def format_signal(result):

    return f"""
🟡 BINANCE FUTURES HAZIRLIK

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/20
""".strip()

# =========================================================
# BOT
# =========================================================

def run_bot():

    send_telegram(
        "🚀 BINANCE FUTURES HYBRID SMART MONEY BOT AKTIF"
    )

    while True:

        try:

            symbols = get_symbols()

            print("Coin:", len(symbols), flush=True)

            for symbol in symbols:

                print("Taranıyor:", symbol, flush=True)

                result = analyze(symbol)

                if not result:
                    continue

                msg = format_signal(result)

                send_telegram(msg)

                print(
                    result["mode"],
                    "SINYAL:",
                    result["symbol"],
                    flush=True
                )

                time.sleep(0.25)

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
    return "BOT AKTIF", 200

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
