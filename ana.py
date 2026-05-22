from flask import Flask
import threading
import time
import os
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

BOT_NAME = "🚄 MEXC HYBRID AI ENGINE"

MAX_SYMBOLS = 80
SLEEP_SECONDS = 240

LIMIT_1M = 80
LIMIT_5M = 80
LIMIT_15M = 220
LIMIT_1H = 220

WATCHLIST_EXPIRE = 60 * 60

COOLDOWN_PREP = 12 * 60 * 60
COOLDOWN_SIGNAL = 4 * 60 * 60
COOLDOWN_RECOVERY = 3 * 60 * 60

WATCHLIST_MIN_SCORE = 9
PREP_NOTIFY_MIN_SCORE = 10

MIN_CONFIDENCE = 70

MAX_RISK_PCT = 4.0

sent_prep = {}
sent_signal = {}
sent_recovery = {}

watchlist = {}

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram eksik", flush=True)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def get_exchange(default_type="spot"):
    return ccxt.mexc({
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": default_type
        }
    })

spot_exchange = get_exchange("spot")
future_exchange = get_exchange("swap")

def rsi(series, length=14):
    delta = series.diff()

    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()

    rs = gain / loss.replace(0, np.nan)

    return 100 - (100 / (1 + rs))

def indicators(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["ma200"] = close.rolling(200).mean()

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std() * 2

    df["bb_width"] = ((basis + dev) - (basis - dev)) / basis
    df["bb_avg"] = df["bb_width"].rolling(50).mean()

    df["vol_avg"] = volume.rolling(20).mean()

    df["rsi"] = rsi(close, 14)
    df["roc"] = close.pct_change(9) * 100

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    obv_values = [0]

    for i in range(1, len(df)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv_values.append(obv_values[-1] + volume.iloc[i])

        elif close.iloc[i] < close.iloc[i - 1]:
            obv_values.append(obv_values[-1] - volume.iloc[i])

        else:
            obv_values.append(obv_values[-1])

    df["obv"] = obv_values
    df["obv_ma"] = pd.Series(obv_values).rolling(20).mean().values

    candle_range = high - low

    df["body_ratio"] = (
        (close - df["open"]).abs()
        / candle_range.replace(0, np.nan)
    )

    df["upper_wick"] = (
        high
        - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range.replace(0, np.nan)

    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1)
        - low
    ) / candle_range.replace(0, np.nan)

    return df

def fetch_df(exchange, symbol, timeframe, limit):
    try:
        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit
        )

        if not ohlcv or len(ohlcv) < 30:
            return None

        df = pd.DataFrame(
            ohlcv,
            columns=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        return df

    except Exception as e:
        print("Fetch hata:", symbol, timeframe, e, flush=True)
        return None

def build_symbols():
    try:
        markets = spot_exchange.load_markets()

        symbols = [
            s for s in markets
            if s.endswith("/USDT")
            and markets[s].get("active", True)
            and not any(
                x in s for x in [
                    "UP/",
                    "DOWN/",
                    "3L/",
                    "3S/",
                    "5L/",
                    "5S/"
                ]
            )
        ]

        tickers = spot_exchange.fetch_tickers(symbols)

        ranked = []

        for s in symbols:
            qv = tickers.get(s, {}).get("quoteVolume") or 0
            ranked.append((s, qv))

        ranked = sorted(
            ranked,
            key=lambda x: x[1],
            reverse=True
        )

        return [x[0] for x in ranked[:MAX_SYMBOLS]]

    except Exception as e:
        print("Symbol hata:", e, flush=True)
        return []

def futures_exists(symbol):
    try:
        markets = future_exchange.load_markets()
        return symbol in markets
    except:
        return False

def fib_targets(df, lookback=60):
    recent = df.tail(lookback)

    swing_low = recent["low"].min()
    swing_high = recent["high"].max()

    impulse = swing_high - swing_low

    if impulse <= 0:
        return None

    return {
        "low": swing_low,
        "high": swing_high,
        "tp1": swing_high,
        "tp2": swing_low + impulse * 1.272,
        "tp3": swing_low + impulse * 1.618,
        "tp4": swing_low + impulse * 2.0
    }

def spot_engine(symbol):
    df15 = fetch_df(
        spot_exchange,
        symbol,
        "15m",
        LIMIT_15M
    )

    if df15 is None or len(df15) < 210:
        return None

    df15 = indicators(df15)

    df15 = df15.dropna().copy()

    if len(df15) < 30:
        return None

    last = df15.iloc[-1]
    prev = df15.iloc[-2]

    volume_ratio = (
        last.volume / last.vol_avg
        if last.vol_avg > 0 else 0
    )

    usdt_volume = last.volume * last.close

    score = 0
    reasons = []

    ema_trend = (
        last.ema20 > last.ema50
        and last.close > last.ema200
    )

    ma200_above = last.close > last.ma200

    bb_squeeze = last.bb_width < last.bb_avg

    obv_bull = last.obv > last.obv_ma

    macd_bull = (
        last.macd > last.macd_signal
        and last.macd > prev.macd
    )

    if ema_trend:
        score += 2
        reasons.append("EMA trend yukarı")

    if ma200_above:
        score += 1
        reasons.append("MA200 üstü")

    if bb_squeeze:
        score += 1
        reasons.append("BB squeeze")

    if volume_ratio >= 1.8:
        score += 2
        reasons.append("hacim hazırlık")

    if volume_ratio >= 2.5:
        score += 1
        reasons.append("hacim güçlü")

    if usdt_volume >= 25000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if 52 <= last.rsi <= 68:
        score += 2
        reasons.append("RSI sağlıklı")

    if last.roc > 0.8:
        score += 1
        reasons.append("ROC pozitif")

    if obv_bull:
        score += 2
        reasons.append("OBV toplama")

    if macd_bull:
        score += 1
        reasons.append("MACD yukarı")

    if last.body_ratio >= 0.35:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if last.upper_wick <= 0.40:
        score += 1
        reasons.append("üst fitil düşük")

    fib = fib_targets(df15)

    return {
        "score": score,
        "price": last.close,
        "volume_ratio": volume_ratio,
        "usdt_volume": usdt_volume,
        "rsi": last.rsi,
        "roc": last.roc,
        "bb_width": last.bb_width,
        "ema_trend": ema_trend,
        "ma200_above": ma200_above,
        "bb_squeeze": bb_squeeze,
        "obv_bull": obv_bull,
        "macd_bull": macd_bull,
        "body_ratio": last.body_ratio,
        "upper_wick": last.upper_wick,
        "lower_wick": last.lower_wick,
        "fib": fib,
        "reasons": reasons
    }

def futures_engine(symbol):
    if not futures_exists(symbol):
        return None

    df1 = fetch_df(
        future_exchange,
        symbol,
        "1m",
        LIMIT_1M
    )

    if df1 is None or len(df1) < 30:
        return None

    df1 = indicators(df1)

    df1 = df1.dropna().copy()

    if len(df1) < 25:
        return None

    last = df1.iloc[-1]
    prev3 = df1.iloc[-4]

    volume_ratio = (
        last.volume / last.vol_avg
        if last.vol_avg > 0 else 0
    )

    usdt_volume = last.volume * last.close

    change_1m = (
        (last.close - last.open)
        / last.open
    ) * 100

    change_3m = (
        (last.close - prev3.open)
        / prev3.open
    ) * 100

    score = 0
    reasons = []

    if volume_ratio >= 2.5:
        score += 2
        reasons.append("futures hacim artışı")

    if volume_ratio >= 4:
        score += 2
        reasons.append("futures hacim patlaması")

    if usdt_volume >= 6000:
        score += 1
        reasons.append("futures hacim yeterli")

    if change_1m >= 0.20:
        score += 1
        reasons.append("1m momentum")

    if change_3m >= 0.40:
        score += 1
        reasons.append("3m momentum")

    if last.body_ratio >= 0.35:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if last.upper_wick <= 0.50:
        score += 1
        reasons.append("üst fitil sağlıklı")

    if last.close > last.open:
        score += 1
        reasons.append("yeşil futures mum")

    return {
        "score": score,
        "price": last.close,
        "volume_ratio": volume_ratio,
        "usdt_volume": usdt_volume,
        "change_1m": change_1m,
        "change_3m": change_3m,
        "body_ratio": last.body_ratio,
        "upper_wick": last.upper_wick,
        "lower_wick": last.lower_wick,
        "reasons": reasons
    }

def trend_1h(symbol):
    df = fetch_df(
        spot_exchange,
        symbol,
        "1h",
        LIMIT_1H
    )

    if df is None or len(df) < 210:
        return None

    df = indicators(df)

    df = df.dropna().copy()

    if len(df) < 10:
        return None

    last = df.iloc[-1]

    return {
        "trend_up": last.ema9 > last.ema21,
        "ma200_above": last.close > last.ma200
    }

def five_confirm(symbol, resistance):
    df = fetch_df(
        spot_exchange,
        symbol,
        "5m",
        LIMIT_5M
    )

    if df is None or len(df) < 30:
        return None

    df = indicators(df)

    df = df.dropna().copy()

    if len(df) < 10:
        return None

    last = df.iloc[-1]

    breakout = last.close > resistance

    strong = (
        breakout
        and last.body_ratio >= 0.45
        and last.upper_wick <= 0.35
    )

    return {
        "close": last.close,
        "breakout": breakout,
        "strong": strong,
        "body_ratio": last.body_ratio,
        "upper_wick": last.upper_wick
    }

def recovery_mode(spot, futures):
    if not spot:
        return False

    recovery_score = 0

    if spot["lower_wick"] >= 0.45:
        recovery_score += 2

    if spot["volume_ratio"] >= 2:
        recovery_score += 2

    if spot["obv_bull"]:
        recovery_score += 2

    if spot["macd_bull"]:
        recovery_score += 1

    if 45 <= spot["rsi"] <= 70:
        recovery_score += 1

    if futures:
        if futures["volume_ratio"] >= 3:
            recovery_score += 2

        if futures["change_3m"] >= 0.50:
            recovery_score += 1

    return recovery_score >= 7

def confidence_score(
    spot,
    futures,
    trend,
    five,
    recovery=False
):
    score = 0

    if spot:
        score += min(spot["score"] * 3, 40)

    if futures:
        score += min(futures["score"] * 2, 20)

    if trend and trend["trend_up"]:
        score += 10

    if trend and trend["ma200_above"]:
        score += 10

    if five and five["strong"]:
        score += 10

    if recovery:
        score += 10

    return int(min(score, 100))

def trade_plan(price, fib, recovery=False):
    if not fib:
        return None

    resistance = fib["high"]
    support = fib["low"]

    if recovery:
        entry = price
        stop = support * 0.995

    else:
        entry = resistance
        stop = resistance * 0.985

    risk = entry - stop

    if risk <= 0:
        return None

    risk_pct = (risk / entry) * 100

    if risk_pct > MAX_RISK_PCT:
        return None

    tp1 = entry + risk * 1.5
    tp2 = entry + risk * 2.0
    tp3 = entry + risk * 3.0

    rr = (tp3 - entry) / risk

    return {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "risk_pct": risk_pct
    }

def clean_watchlist():
    now = time.time()

    expired = []

    for symbol, data in watchlist.items():
        if now - data["time"] > WATCHLIST_EXPIRE:
            expired.append(symbol)

    for symbol in expired:
        del watchlist[symbol]

def analyze_symbol(symbol):
    try:
        spot = spot_engine(symbol)

        if not spot:
            return

        trend = trend_1h(symbol)

        if not trend:
            return

        if spot["score"] < WATCHLIST_MIN_SCORE:
            return

        if not spot["obv_bull"]:
            return

        if not spot["macd_bull"]:
            return

        watchlist[symbol] = {
            "time": time.time(),
            "spot": spot,
            "trend": trend,
            "fib": spot["fib"]
        }

        now = time.time()

        if (
            spot["score"] >= PREP_NOTIFY_MIN_SCORE
            and (
                symbol not in sent_prep
                or now - sent_prep[symbol] > COOLDOWN_PREP
            )
        ):
            sent_prep[symbol] = now

            msg = f"""
🟡 🚄 MEXC HAZIRLIK

Coin: {symbol}
Fiyat: {spot['price']:.8f}

Skor: {spot['score']}/16

Spot Hacim:
{spot['volume_ratio']:.2f}x

USDT Hacim:
{int(spot['usdt_volume'])}

RSI:
{spot['rsi']:.2f}

ROC:
{spot['roc']:.2f}

OBV:
{'TOPLAMA ✅' if spot['obv_bull'] else 'ZAYIF ❌'}

MACD:
{'YUKARI ✅' if spot['macd_bull'] else 'ZAYIF ❌'}

📌 Sebep:
{", ".join(spot['reasons'])}

📍 Karar:
Coin watchlist'e alındı.
Hybrid onay bekleniyor.
""".strip()

            send_telegram(msg)

    except Exception as e:
        print("Analyze hata:", symbol, e, flush=True)

def check_signal(symbol, data):
    try:
        spot = data["spot"]
        trend = data["trend"]
        fib = data["fib"]

        futures = None

        if spot["score"] >= 10:
            futures = futures_engine(symbol)

        five = five_confirm(
            symbol,
            fib["high"]
        )

        recovery = recovery_mode(
            spot,
            futures
        )

        confidence = confidence_score(
            spot,
            futures,
            trend,
            five,
            recovery
        )

        if confidence < MIN_CONFIDENCE:
            return

        mode = "SAFE LONG"

        if recovery:
            mode = "🚀 RECOVERY LONG"

        plan = trade_plan(
            spot["price"],
            fib,
            recovery
        )

        if not plan:
            return

        key = symbol + "_" + mode

        now = time.time()

        if recovery:
            cache = sent_recovery
            cooldown = COOLDOWN_RECOVERY

        else:
            cache = sent_signal
            cooldown = COOLDOWN_SIGNAL

        if (
            key in cache
            and now - cache[key] < cooldown
        ):
            return

        cache[key] = now

        msg = f"""
🧠 🚄 MEXC HYBRID AI SIGNAL

Coin: {symbol}

Mod:
{mode}

📍 NET GİRİŞ:
{plan['entry']:.8f}

🛑 STOP:
{plan['stop']:.8f}

🎯 TP1:
{plan['tp1']:.8f}

🎯 TP2:
{plan['tp2']:.8f}

🎯 TP3:
{plan['tp3']:.8f}

📊 Risk:
%{plan['risk_pct']:.2f}

⚖️ RR:
1 : {plan['rr']:.2f}

🧠 Güven:
{confidence}/100

📈 Trend:
{'YUKARI ✅' if trend['trend_up'] else 'ZAYIF ❌'}

MA200:
{'ÜSTÜ ✅' if trend['ma200_above'] else 'ALTI ❌'}

🐋 Spot Hacim:
{spot['volume_ratio']:.2f}x

📊 RSI:
{spot['rsi']:.2f}

📈 ROC:
{spot['roc']:.2f}

📌 Karar:
{'Recovery trade dikkatli yönetilmeli.' if recovery else 'Safe continuation setup.'}
""".strip()

        send_telegram(msg)

        if symbol in watchlist:
            del watchlist[symbol]

    except Exception as e:
        print("Signal hata:", symbol, e, flush=True)

def scan_watchlist():
    clean_watchlist()

    if len(watchlist) == 0:
        return

    print(
        "Watchlist:",
        len(watchlist),
        flush=True
    )

    for symbol in list(watchlist.keys()):
        check_signal(
            symbol,
            watchlist[symbol]
        )

        time.sleep(0.40)

def run_bot():
    send_telegram(
        f"✅ {BOT_NAME} başladı."
    )

    print(
        BOT_NAME,
        "BAŞLADI",
        flush=True
    )

    while True:
        try:
            print(
                "Tarama başladı:",
                datetime.now(),
                flush=True
            )

            scan_watchlist()

            symbols = build_symbols()

            print(
                "Coin sayısı:",
                len(symbols),
                flush=True
            )

            for symbol in symbols:
                analyze_symbol(symbol)

                time.sleep(0.40)

            scan_watchlist()

            print(
                "Tur bitti",
                flush=True
            )

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print(
                "Genel hata:",
                e,
                flush=True
            )

            time.sleep(30)

@app.route("/")
def home():
    return "MEXC HYBRID AI ENGINE AKTIF", 200

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
