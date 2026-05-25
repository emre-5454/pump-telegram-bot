# =========================================================
# BINANCE FUTURES PLAY STYLE PUMP BOT
# HAZIRLIK + PUMP ONAY SISTEMI
# Railway uyumlu tek parca kod
# =========================================================

from flask import Flask
import requests
import threading
import time
import os

app = Flask(__name__)

# =========================================================
# TELEGRAM - Railway Variables kullan
# TELEGRAM_TOKEN
# CHAT_ID
# =========================================================

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

# =========================================================
# SETTINGS
# =========================================================

SLEEP_SECONDS = 45
MAX_SYMBOLS = 120

COOLDOWN_PREP = 3 * 60 * 60
COOLDOWN_PUMP = 6 * 60 * 60

# =========================================================
# PREP FILTERS - Pump oncesi hazirlik
# =========================================================

PREP_MIN_SCORE = 8
PREP_MIN_VOLUME_USDT = 40000
PREP_MIN_VOLUME_RATIO = 1.8
PREP_MIN_3M_CHANGE = 0.10
PREP_MAX_3M_CHANGE = 2.50
PREP_MIN_RSI = 55
PREP_MAX_RSI = 74
PREP_MAX_BB_WIDTH = 0.055
PREP_MIN_BODY_RATIO = 0.35
PREP_MAX_UPPER_WICK = 0.45

# =========================================================
# PUMP CONFIRM FILTERS - PLAY tarzi yakalama
# =========================================================

PUMP_MIN_SCORE = 13
PUMP_MIN_VOLUME_USDT = 100000
PUMP_MIN_VOLUME_RATIO = 3.5
PUMP_MIN_1M_CHANGE = 0.20
PUMP_MIN_3M_CHANGE = 0.60
PUMP_MAX_3M_CHANGE = 6.50
PUMP_MIN_RSI = 75
PUMP_STRONG_RSI = 82
PUMP_MIN_BODY_RATIO = 0.50
PUMP_MAX_UPPER_WICK = 0.35

# =========================================================
# ORDER BOOK
# =========================================================

ORDER_BOOK_LIMIT = 50
ORDER_BOOK_RANGE_PCT = 0.015
ORDER_BOOK_MIN_BID_ASK_RATIO = 1.20
ORDER_BOOK_MAX_SPREAD_PCT = 0.12

# =========================================================
# CACHE
# =========================================================

sent_prep = {}
sent_pump = {}
oi_cache = {}

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token veya chat id eksik.", flush=True)
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
        macd_series.append(ema(part, 12) - ema(part, 26))

    signal = ema(macd_series, 9)

    if signal is None:
        return None, None, None

    hist = macd_line - signal

    return macd_line, signal, hist


def bollinger_data(values, period=20):
    if len(values) < period:
        return None

    recent = values[-period:]
    mid = sum(recent) / period
    variance = sum((x - mid) ** 2 for x in recent) / period
    std = variance ** 0.5

    upper = mid + 2 * std
    lower = mid - 2 * std
    width = (upper - lower) / mid if mid != 0 else 0

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

    obv_now = values[-1]
    obv_avg = sum(values[-20:]) / 20

    return obv_now, obv_avg

# =========================================================
# BINANCE API
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


def get_klines(symbol, interval="1m", limit=220):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        data = requests.get(
            url,
            params=params,
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
        url = "https://fapi.binance.com/fapi/v1/openInterest"
        data = requests.get(
            url,
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

        spread_pct = ((best_ask - best_bid) / price) * 100

        low_range = best_bid * (1 - ORDER_BOOK_RANGE_PCT)
        high_range = best_ask * (1 + ORDER_BOOK_RANGE_PCT)

        bid_liq = 0
        ask_liq = 0

        for bid in bids:
            p = float(bid[0])
            q = float(bid[1])
            usdt = p * q

            if low_range <= p <= best_bid:
                bid_liq += usdt

        for ask in asks:
            p = float(ask[0])
            q = float(ask[1])
            usdt = p * q

            if best_ask <= p <= high_range:
                ask_liq += usdt

        if ask_liq <= 0:
            ask_liq = 1

        if bid_liq <= 0:
            bid_liq = 1

        bid_ask_ratio = bid_liq / ask_liq
        spread_ok = spread_pct <= ORDER_BOOK_MAX_SPREAD_PCT

        long_confirm = (
            bid_ask_ratio >= ORDER_BOOK_MIN_BID_ASK_RATIO
            and spread_ok
        )

        return {
            "bid_ask_ratio": bid_ask_ratio,
            "spread_pct": spread_pct,
            "long_confirm": long_confirm
        }

    except Exception as e:
        print("Orderbook hata:", symbol, e, flush=True)
        return None

# =========================================================
# ANALYZE
# =========================================================

def analyze(symbol):
    try:
        candles = get_klines(symbol, "1m", 220)

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
        volumes = [float(x[7]) for x in candles]

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

        rsi_value = rsi(closes, 14)
        bb = bollinger_data(closes, 20)
        macd_line, macd_signal, macd_hist = macd(closes)
        obv_value, obv_avg = obv(closes, volumes)

        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma100 = sma(closes, 100)
        ma200 = sma(closes, 200)

        oi_now = get_open_interest(symbol)

        if oi_now is None:
            return None

        prev_oi = oi_cache.get(symbol)
        oi_cache[symbol] = oi_now

        if prev_oi is None or prev_oi <= 0:
            return None

        oi_ratio = oi_now / prev_oi

        orderbook = get_order_book_signal(symbol, c)

        recent_high = max(highs[-20:-2])
        breakout = c > recent_high

        bb_upper_break = False
        bb_squeeze = False

        if bb:
            bb_upper_break = c > bb["upper"]
            bb_squeeze = bb["width"] <= PREP_MAX_BB_WIDTH

        above_ma200 = ma200 is not None and c > ma200
        ma_trend_ok = ma20 is not None and ma50 is not None and ma20 > ma50
        macd_positive = macd_hist is not None and macd_hist > 0
        obv_positive = obv_value is not None and obv_avg is not None and obv_value > obv_avg

        # =================================================
        # PREP SCORE
        # =================================================

        prep_score = 0
        prep_reasons = []

        if quote_volume >= PREP_MIN_VOLUME_USDT:
            prep_score += 1
            prep_reasons.append("hacim yeterli")

        if volume_ratio >= PREP_MIN_VOLUME_RATIO:
            prep_score += 2
            prep_reasons.append("hacim artıyor")

        if PREP_MIN_3M_CHANGE <= price_change_3m <= PREP_MAX_3M_CHANGE:
            prep_score += 2
            prep_reasons.append("erken momentum")

        if rsi_value is not None and PREP_MIN_RSI <= rsi_value <= PREP_MAX_RSI:
            prep_score += 2
            prep_reasons.append("RSI hazırlık bölgesi")

        if bb_squeeze:
            prep_score += 2
            prep_reasons.append("BB sıkışma")

        if ma_trend_ok:
            prep_score += 1
            prep_reasons.append("MA20 MA50 üstü")

        if macd_positive:
            prep_score += 1
            prep_reasons.append("MACD pozitif")

        if obv_positive:
            prep_score += 2
            prep_reasons.append("OBV para girişi")

        if stats["body_ratio"] >= PREP_MIN_BODY_RATIO and stats["upper_wick"] <= PREP_MAX_UPPER_WICK:
            prep_score += 1
            prep_reasons.append("mum yapısı iyi")

        if orderbook and orderbook["long_confirm"]:
            prep_score += 2
            prep_reasons.append("orderbook destekli")

        # =================================================
        # PUMP SCORE - PLAY tarzi hareket
        # =================================================

        pump_score = 0
        pump_reasons = []

        if quote_volume >= PUMP_MIN_VOLUME_USDT:
            pump_score += 1
            pump_reasons.append("yüksek hacim")

        if volume_ratio >= PUMP_MIN_VOLUME_RATIO:
            pump_score += 3
            pump_reasons.append("hacim patlaması")

        if price_change_1m >= PUMP_MIN_1M_CHANGE:
            pump_score += 1
            pump_reasons.append("1dk momentum")

        if PUMP_MIN_3M_CHANGE <= price_change_3m <= PUMP_MAX_3M_CHANGE:
            pump_score += 2
            pump_reasons.append("3dk güçlü momentum")

        if rsi_value is not None and rsi_value >= PUMP_MIN_RSI:
            pump_score += 2
            pump_reasons.append("RSI güçlü")

        if rsi_value is not None and rsi_value >= PUMP_STRONG_RSI:
            pump_score += 1
            pump_reasons.append("RSI 82+ pump modu")

        if bb_upper_break:
            pump_score += 3
            pump_reasons.append("BB üst bant kırılımı")

        if above_ma200:
            pump_score += 3
            pump_reasons.append("MA200 üstü güç")

        if breakout:
            pump_score += 2
            pump_reasons.append("direnç kırılımı")

        if macd_positive:
            pump_score += 1
            pump_reasons.append("MACD pozitif")

        if obv_positive:
            pump_score += 2
            pump_reasons.append("OBV para girişi")

        if stats["body_ratio"] >= PUMP_MIN_BODY_RATIO:
            pump_score += 1
            pump_reasons.append("güçlü mum gövdesi")

        if stats["upper_wick"] <= PUMP_MAX_UPPER_WICK:
            pump_score += 1
            pump_reasons.append("üst fitil düşük")

        if oi_ratio >= 1.0015:
            pump_score += 2
            pump_reasons.append("OI artışı")

        if orderbook and orderbook["long_confirm"]:
            pump_score += 2
            pump_reasons.append("bookmap long destek")

        now = time.time()

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
                "volume_ratio": volume_ratio,
                "quote_volume": quote_volume,
                "oi_ratio": oi_ratio,
                "price_change_1m": price_change_1m,
                "price_change_3m": price_change_3m,
                "rsi": rsi_value,
                "bb_width": bb["width"] if bb else None,
                "ma200": ma200,
                "macd_hist": macd_hist,
                "obv_value": obv_value,
                "obv_avg": obv_avg,
                "body_ratio": stats["body_ratio"],
                "upper_wick": stats["upper_wick"],
                "breakout": breakout,
                "bb_upper_break": bb_upper_break,
                "above_ma200": above_ma200,
                "reasons": pump_reasons
            }

        # =================================================
        # PREP SIGNAL
        # =================================================

        if prep_score >= PREP_MIN_SCORE:
            last_sent = sent_prep.get(symbol)

            if last_sent and now - last_sent < COOLDOWN_PREP:
                return None

            sent_prep[symbol] = now

            return {
                "mode": "PREP",
                "symbol": symbol,
                "price": c,
                "score": prep_score,
                "volume_ratio": volume_ratio,
                "quote_volume": quote_volume,
                "oi_ratio": oi_ratio,
                "price_change_1m": price_change_1m,
                "price_change_3m": price_change_3m,
                "rsi": rsi_value,
                "bb_width": bb["width"] if bb else None,
                "ma200": ma200,
                "macd_hist": macd_hist,
                "obv_value": obv_value,
                "obv_avg": obv_avg,
                "body_ratio": stats["body_ratio"],
                "upper_wick": stats["upper_wick"],
                "breakout": breakout,
                "bb_upper_break": bb_upper_break,
                "above_ma200": above_ma200,
                "reasons": prep_reasons
            }

        return None

    except Exception as e:
        print("Analyze hata:", symbol, e, flush=True)
        return None

# =========================================================
# FORMAT SIGNAL
# =========================================================

def format_signal(result):
    if result["mode"] == "PUMP":
        title = "🚀 BINANCE FUTURES PUMP ONAY"
        note = "PLAY tarzı hareket yakalandı. Direkt FOMO değil; mümkünse 1m/3m retest bekle."
    else:
        title = "🟡 BINANCE FUTURES HAZIRLIK"
        note = "Pump hazırlığı var. Direnç kırılımı + hacim devamı beklenmeli."

    rsi_text = f"{result['rsi']:.2f}" if result["rsi"] is not None else "YOK"
    bb_text = f"{result['bb_width']:.4f}" if result["bb_width"] is not None else "YOK"
    ma200_text = f"{result['ma200']:.6f}" if result["ma200"] is not None else "YOK"
    macd_text = f"{result['macd_hist']:.6f}" if result["macd_hist"] is not None else "YOK"

    return f"""
{title}

Coin: {result['symbol']}
Fiyat: {result['price']:.8f}

Skor: {result['score']}/25

1dk Değişim: %{result['price_change_1m']:.2f}
3dk Değişim: %{result['price_change_3m']:.2f}

Hacim Artışı: {result['volume_ratio']:.2f}x
Son Mum Hacmi: {result['quote_volume']:.0f} USDT

OI Artışı: {result['oi_ratio']:.4f}x

RSI: {rsi_text}
BB Width: {bb_text}
MA200: {ma200_text}
MACD Hist: {macd_text}

Mum Gövde: %{result['body_ratio'] * 100:.1f}
Üst Fitil: %{result['upper_wick'] * 100:.1f}

BB Üst Bant Kırılımı: {"VAR ✅" if result["bb_upper_break"] else "YOK ❌"}
MA200 Üstü: {"VAR ✅" if result["above_ma200"] else "YOK ❌"}
Direnç Kırılımı: {"VAR ✅" if result["breakout"] else "YOK ❌"}

Sebep:
{", ".join(result['reasons'])}

Not:
{note}
""".strip()

# =========================================================
# BOT LOOP
# =========================================================

def run_bot():
    send_telegram("🚀 BINANCE FUTURES PLAY STYLE PUMP BOT AKTIF")

    while True:
        try:
            symbols = get_symbols()

            print("Taranan coin sayısı:", len(symbols), flush=True)

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
                    "SKOR:",
                    result["score"],
                    flush=True
                )

                time.sleep(0.20)

            print("Tarama bitti.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(10)

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "BINANCE FUTURES PLAY STYLE PUMP BOT AKTIF", 200

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
