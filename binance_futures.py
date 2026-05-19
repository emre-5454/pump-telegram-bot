from flask import Flask
import requests
import threading
import time
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

SLEEP_SECONDS = 90
MAX_SYMBOLS = 60

COOLDOWN_PREP = 6 * 60 * 60
COOLDOWN_TRADE = 6 * 60 * 60

PREP_MIN_SCORE = 8
PREP_MIN_VOLUME_USDT = 50000
PREP_MIN_VOLUME_RATIO = 2.5
PREP_MIN_OI_RATIO = 1.001
PREP_MIN_3M_CHANGE = 0.10
PREP_MAX_3M_CHANGE = 2.20
PREP_MIN_BODY_RATIO = 0.35
PREP_MAX_UPPER_WICK = 0.40

TRADE_MIN_SCORE = 12
TRADE_MIN_VOLUME_USDT = 120000
TRADE_MIN_VOLUME_RATIO = 5.0
TRADE_MIN_OI_RATIO = 1.0035
TRADE_MIN_1M_CHANGE = 0.15
TRADE_MIN_3M_CHANGE = 0.45
TRADE_MAX_3M_CHANGE = 3.00
TRADE_MIN_BODY_RATIO = 0.50
TRADE_MAX_UPPER_WICK = 0.30

RETEST_ZONE_PCT = 0.004
MOMENTUM_MAX_DISTANCE = 0.012
FOMO_DISTANCE = 0.012

sent_prep = {}
sent_trade = {}
oi_cache = {}


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token veya chat id eksik", flush=True)
        return

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

    return macd_line, signal, macd_line - signal


def bollinger_width(values, period=20):
    if len(values) < period:
        return None

    recent = values[-period:]
    mid = sum(recent) / period

    if mid == 0:
        return None

    variance = sum((x - mid) ** 2 for x in recent) / period
    std = variance ** 0.5

    return ((mid + 2 * std) - (mid - 2 * std)) / mid


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


def fib_targets(highs, lows, lookback=60):
    if len(highs) < lookback or len(lows) < lookback:
        return None

    swing_high = max(highs[-lookback:])
    swing_low = min(lows[-lookback:])
    impulse = swing_high - swing_low

    if impulse <= 0:
        return None

    return {
        "low": swing_low,
        "high": swing_high,
        "tp1": swing_high,
        "tp2": swing_low + impulse * 1.272,
        "tp3": swing_low + impulse * 1.618,
        "tp4": swing_low + impulse * 2.0,
        "invalid": swing_low
    }


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


def get_klines(symbol, interval="1m", limit=220):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    return requests.get(url, params=params, timeout=15).json()


def get_open_interest(symbol):
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    data = requests.get(url, params={"symbol": symbol}, timeout=10).json()
    return float(data["openInterest"])


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

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick
    }


def get_1h_trend(symbol):
    try:
        candles = get_klines(symbol, "1h", 220)

        if not candles or len(candles) < 205:
            return None

        closes = [float(x[4]) for x in candles]

        price = closes[-2]
        ema9 = ema(closes[:-1], 9)
        ema21 = ema(closes[:-1], 21)
        ma200 = sma(closes[:-1], 200)

        if ema9 is None or ema21 is None or ma200 is None:
            return None

        return {
            "trend_up": ema9 > ema21,
            "ma200_above": price > ma200,
            "ema9": ema9,
            "ema21": ema21,
            "ma200": ma200
        }

    except Exception as e:
        print("1H trend hata:", symbol, e, flush=True)
        return None


def get_5m_confirm(symbol, resistance):
    try:
        candles = get_klines(symbol, "5m", 40)

        if not candles or len(candles) < 25:
            return None

        last = candles[-2]
        stats = candle_stats(last)

        if not stats:
            return None

        close_5m = stats["close"]

        return {
            "close": close_5m,
            "breakout_close": close_5m > resistance,
            "body_ratio": stats["body_ratio"],
            "upper_wick": stats["upper_wick"],
            "strong": (
                close_5m > resistance
                and stats["body_ratio"] >= 0.45
                and stats["upper_wick"] <= 0.35
            )
        }

    except Exception as e:
        print("5M onay hata:", symbol, e, flush=True)
        return None


def get_15m_indicators(symbol):
    try:
        candles = get_klines(symbol, "15m", 120)

        if not candles or len(candles) < 80:
            return None

        closes = [float(x[4]) for x in candles]
        highs = [float(x[2]) for x in candles]
        lows = [float(x[3]) for x in candles]
        volumes = [float(x[7]) for x in candles]

        rsi_val = rsi(closes, 14)
        bb_now = bollinger_width(closes, 20)

        bb_values = []
        for i in range(20, len(closes) + 1):
            bw = bollinger_width(closes[:i], 20)
            if bw is not None:
                bb_values.append(bw)

        bb_avg = sma(bb_values, 50) if len(bb_values) >= 50 else None

        macd_line, macd_signal, macd_hist = macd(closes)
        obv_now, obv_avg = obv(closes, volumes)
        fib = fib_targets(highs, lows, 60)

        return {
            "rsi": rsi_val,
            "bb_width": bb_now,
            "bb_avg": bb_avg,
            "bb_tight": bb_now is not None and bb_avg is not None and bb_now < bb_avg,
            "macd_bull": macd_line is not None and macd_signal is not None and macd_line > macd_signal,
            "obv_bull": obv_now is not None and obv_avg is not None and obv_now > obv_avg,
            "fib": fib
        }

    except Exception as e:
        print("15M indikatör hata:", symbol, e, flush=True)
        return None


def make_trade_plan(result, mode):
    fib = result.get("fib")
    price = result.get("price")

    if not fib or not price:
        return None

    resistance = fib["high"]
    support = fib["low"]

    if mode == "RETEST_LONG":
        entry_low = resistance * 0.997
        entry_high = resistance * 1.003
        stop = resistance * 0.985

    elif mode == "MOMENTUM_LONG":
        entry_low = price * 0.998
        entry_high = price * 1.002
        stop = resistance * 0.990

    else:
        entry_low = resistance * 0.997
        entry_high = resistance * 1.003
        stop = max(support * 0.995, price * 0.975)

    tp1 = fib["tp2"]
    tp2 = fib["tp3"]
    tp3 = fib["tp4"]

    risk = entry_high - stop
    reward = tp2 - entry_high

    rr = reward / risk if risk > 0 else 0

    if rr < 1:
        status = "ZAYIF"
    elif rr < 2:
        status = "ORTA"
    else:
        status = "GÜÇLÜ"

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "status": status,
        "resistance": resistance,
        "support": support
    }


def classify_signal(price, resistance, volume_ratio, oi_ratio, upper_wick, body_ratio, five):
    distance = (price - resistance) / resistance

    if distance > FOMO_DISTANCE:
        return "FOMO"

    if abs(distance) <= RETEST_ZONE_PCT and five and five["strong"]:
        return "RETEST_LONG"

    if 0.003 < distance <= MOMENTUM_MAX_DISTANCE:
        if (
            five and five["breakout_close"]
            and volume_ratio >= TRADE_MIN_VOLUME_RATIO
            and oi_ratio >= TRADE_MIN_OI_RATIO
            and upper_wick <= 0.25
            and body_ratio >= 0.55
        ):
            return "MOMENTUM_LONG"

    if price > resistance and five and five["breakout_close"]:
        return "BREAKOUT_WAIT_RETEST"

    return "PREP"


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

        price_change_1m = ((c - prev_close) / prev_close) * 100
        price_change_3m = ((c - prev3_close) / prev3_close) * 100

        old_volumes = [float(x[7]) for x in candles[-22:-2]]
        avg_volume = sum(old_volumes) / len(old_volumes)

        if avg_volume <= 0:
            return None

        volume_ratio = quote_volume / avg_volume
        body_ratio = stats["body_ratio"]
        upper_wick = stats["upper_wick"]

        oi_now = get_open_interest(symbol)
        prev_oi = oi_cache.get(symbol)
        oi_cache[symbol] = oi_now

        if prev_oi is None or prev_oi <= 0:
            print(symbol, "OI ilk ölçüm, sonraki turda değerlenecek", flush=True)
            return None

        oi_ratio = oi_now / prev_oi

        trend = get_1h_trend(symbol)
        ind15 = get_15m_indicators(symbol)

        if not trend or not ind15 or not ind15["fib"]:
            return None

        fib = ind15["fib"]
        resistance = fib["high"]
        five = get_5m_confirm(symbol, resistance)

        score = 0
        reasons = []

        if quote_volume >= PREP_MIN_VOLUME_USDT:
            score += 1
            reasons.append("1dk futures hacim yeterli")

        if volume_ratio >= PREP_MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim hazırlık seviyesinde")

        if volume_ratio >= TRADE_MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim patlaması var")

        if oi_ratio >= PREP_MIN_OI_RATIO:
            score += 1
            reasons.append("OI hafif artıyor")

        if oi_ratio >= TRADE_MIN_OI_RATIO:
            score += 2
            reasons.append("OI güçlü artıyor")

        if price_change_1m >= 0:
            score += 1
            reasons.append("1dk zayıf değil")

        if PREP_MIN_3M_CHANGE <= price_change_3m <= PREP_MAX_3M_CHANGE:
            score += 1
            reasons.append("3dk erken momentum")

        if body_ratio >= PREP_MIN_BODY_RATIO:
            score += 1
            reasons.append("mum gövdesi yeterli")

        if upper_wick <= PREP_MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil kabul edilebilir")

        if trend["trend_up"]:
            score += 1
            reasons.append("1H EMA trend yukarı")

        if trend["ma200_above"]:
            score += 1
            reasons.append("1H MA200 üstü")

        if ind15["rsi"] is not None and 48 <= ind15["rsi"] <= 72:
            score += 1
            reasons.append("15m RSI uygun")

        if ind15["bb_tight"]:
            score += 1
            reasons.append("15m BB sıkışma")

        if ind15["obv_bull"]:
            score += 2
            reasons.append("15m OBV toplama")

        if ind15["macd_bull"]:
            score += 1
            reasons.append("15m MACD yukarı")

        prep_quality_ok = ind15["obv_bull"] or ind15["macd_bull"]
        trade_quality_ok = ind15["obv_bull"] and ind15["macd_bull"]

        prep_valid = (
            score >= PREP_MIN_SCORE
            and quote_volume >= PREP_MIN_VOLUME_USDT
            and volume_ratio >= PREP_MIN_VOLUME_RATIO
            and oi_ratio >= PREP_MIN_OI_RATIO
            and PREP_MIN_3M_CHANGE <= price_change_3m <= PREP_MAX_3M_CHANGE
            and body_ratio >= PREP_MIN_BODY_RATIO
            and upper_wick <= PREP_MAX_UPPER_WICK
            and prep_quality_ok
        )

        trade_valid = (
            score >= TRADE_MIN_SCORE
            and quote_volume >= TRADE_MIN_VOLUME_USDT
            and volume_ratio >= TRADE_MIN_VOLUME_RATIO
            and oi_ratio >= TRADE_MIN_OI_RATIO
            and price_change_1m >= TRADE_MIN_1M_CHANGE
            and TRADE_MIN_3M_CHANGE <= price_change_3m <= TRADE_MAX_3M_CHANGE
            and body_ratio >= TRADE_MIN_BODY_RATIO
            and upper_wick <= TRADE_MAX_UPPER_WICK
            and trend["trend_up"]
            and trend["ma200_above"]
            and trade_quality_ok
        )

        if not prep_valid and not trade_valid:
            print(
                symbol,
                "SKOR:", score,
                "VOL:", round(volume_ratio, 2),
                "OI:", round(oi_ratio, 4),
                "OBV:", ind15["obv_bull"],
                "MACD:", ind15["macd_bull"],
                flush=True
            )
            return None

        mode = "PREP"

        if trade_valid:
            mode = classify_signal(
                c,
                resistance,
                volume_ratio,
                oi_ratio,
                upper_wick,
                body_ratio,
                five
            )

        now = time.time()

        if mode == "PREP":
            cache = sent_prep
            cooldown = COOLDOWN_PREP
        else:
            cache = sent_trade
            cooldown = COOLDOWN_TRADE

        key = symbol + "_" + mode

        if key in cache and now - cache[key] < cooldown:
            return None

        cache[key] = now

        return {
            "symbol": symbol,
            "price": c,
            "score": score,
            "mode": mode,
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
            "rsi": ind15["rsi"],
            "bb_width": ind15["bb_width"],
            "obv_bull": ind15["obv_bull"],
            "macd_bull": ind15["macd_bull"],
            "fib": fib,
            "five": five,
            "reasons": reasons
        }

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)
        return None


def format_signal(result):
    mode = result["mode"]
    fib = result["fib"]
    plan = make_trade_plan(result, mode)

    titles = {
        "PREP": "🟡 BINANCE FUTURES HAZIRLIK",
        "BREAKOUT_WAIT_RETEST": "🟠 BINANCE FUTURES BREAKOUT — RETEST BEKLE",
        "RETEST_LONG": "🟢 BINANCE FUTURES RETEST LONG",
        "MOMENTUM_LONG": "🚀 BINANCE FUTURES MOMENTUM LONG",
        "FOMO": "🔴 BINANCE FUTURES FOMO — GEÇ GİRİŞ"
    }

    title = titles.get(mode, "BINANCE FUTURES SETUP")

    if fib:
        fib_text = f"""
Swing Dip: {fib['low']:.6f}
Swing Tepe: {fib['high']:.6f}

TP1: {fib['tp1']:.6f}
TP2 / 1.272: {fib['tp2']:.6f}
TP3 / 1.618: {fib['tp3']:.6f}
TP4 / 2.000: {fib['tp4']:.6f}

Geçersiz Bölge: {fib['invalid']:.6f}
""".strip()
    else:
        fib_text = "Fib hesaplanamadı."

    if plan:
        if mode == "RETEST_LONG":
            trade_text = f"""
✅ RETEST LONG AKTİF

📍 Giriş:
{plan['entry_low']:.6f} - {plan['entry_high']:.6f}

🛑 Stop:
{plan['stop']:.6f}

🎯 TP1:
{plan['tp1']:.6f}

🎯 TP2:
{plan['tp2']:.6f}

🎯 TP3:
{plan['tp3']:.6f}

📊 Risk/Ödül:
1:{plan['rr']:.2f}

Setup:
{plan['status']}
""".strip()

        elif mode == "MOMENTUM_LONG":
            trade_text = f"""
🚀 MOMENTUM LONG

📍 Giriş:
{plan['entry_low']:.6f} - {plan['entry_high']:.6f}

🛑 Stop:
{plan['stop']:.6f}

🎯 TP1:
{plan['tp1']:.6f}

🎯 TP2:
{plan['tp2']:.6f}

🎯 TP3:
{plan['tp3']:.6f}

📊 Risk/Ödül:
1:{plan['rr']:.2f}

⚠️ Not:
Retest vermeden gidiyor.
Küçük pozisyon daha mantıklı.
""".strip()

        elif mode == "BREAKOUT_WAIT_RETEST":
            trade_text = f"""
🟠 Kırılım var ama giriş aktif değil.

Retest Bölgesi:
{plan['entry_low']:.6f} - {plan['entry_high']:.6f}

Şart:
Bu bölgeye geri gelip yeşil tepki vermeli.

Muhtemel Stop:
{plan['stop']:.6f}

Muhtemel TP:
{plan['tp1']:.6f} / {plan['tp2']:.6f} / {plan['tp3']:.6f}
""".strip()

        elif mode == "FOMO":
            trade_text = f"""
🔴 FOMO RİSKİ

Fiyat dirençten fazla uzaklaşmış.

Direnç:
{plan['resistance']:.6f}

Şu an:
{result['price']:.6f}

Karar:
Buradan market giriş riskli.
Retest veya yeni setup bekle.
""".strip()

        else:
            trade_text = f"""
⚠️ Hazırlık var, işlem aktif değil.

Takip Bölgesi:
{plan['entry_low']:.6f} - {plan['entry_high']:.6f}

Onay Şartı:
{plan['resistance']:.6f} üstü 5m kapanış + retest veya momentum devamı

Muhtemel TP:
{plan['tp1']:.6f} / {plan['tp2']:.6f} / {plan['tp3']:.6f}
""".strip()
    else:
        trade_text = "Trade plan hesaplanamadı."

    decision_map = {
        "PREP": "Hazırlık geldi. İşlem yok, takip.",
        "BREAKOUT_WAIT_RETEST": "Kırılım var. Retest bekle.",
        "RETEST_LONG": "Retest tuttu. Long plan aktif.",
        "MOMENTUM_LONG": "Retest vermeden gidiyor. Küçük pozisyon mantığı.",
        "FOMO": "Geç giriş. İşlem kovalanmaz."
    }

    five = result.get("five")
    if five:
        five_text = f"""
5m Kapanış: {five['close']:.6f}
5m Breakout: {'EVET ✅' if five['breakout_close'] else 'HAYIR ❌'}
5m Mum Gücü: {five['body_ratio']:.2f}
5m Üst Fitil: {five['upper_wick']:.2f}
""".strip()
    else:
        five_text = "5m veri yok."

    msg = f"""
{title}

Coin: {result['symbol'].replace('USDT', '/USDT')}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/18

1dk Değişim: %{result['price_change_1m']:.2f}
3dk Değişim: %{result['price_change_3m']:.2f}

1dk Futures Hacim: {int(result['quote_volume'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x
OI Artışı: {result['oi_ratio']:.4f}x

1H EMA Trend: {'YUKARI ✅' if result['trend_up'] else 'ZAYIF ❌'}
1H MA200 Üstü: {'EVET ✅' if result['ma200_above'] else 'HAYIR ❌'}

15m RSI: {result['rsi']:.2f}
15m BB Width: {result['bb_width']:.4f}
15m OBV: {'TOPLAMA ✅' if result['obv_bull'] else 'ZAYIF ❌'}
15m MACD: {'YUKARI ✅' if result['macd_bull'] else 'ZAYIF ❌'}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

1H EMA9: {result['ema9']:.6f}
1H EMA21: {result['ema21']:.6f}
1H MA200: {result['ma200']:.6f}

📌 5M ONAY:
{five_text}

📌 TRADE PLANI:
{trade_text}

🎯 Fib Hedefleri:
{fib_text}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
{decision_map.get(mode, 'Takip et.')}
""".strip()

    return msg


def run_bot():
    send_telegram("🚀 BINANCE FUTURES RETEST + MOMENTUM BOT başladı hocam")
    print("BINANCE FUTURES RETEST + MOMENTUM BOT ÇALIŞTI", flush=True)

    while True:
        try:
            symbols = get_symbols()
            print("Taranan futures coin:", len(symbols), flush=True)

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
                    "PUAN:",
                    result["score"],
                    flush=True
                )

                time.sleep(0.25)

            print("Futures tarama bitti", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(10)


@app.route("/")
def home():
    return "Binance Futures Retest + Momentum Scanner Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
