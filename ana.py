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

BOT_SOURCE = "🚄 Railway"
BOT_NAME = "MEXC HYBRID AI SIGNAL ENGINE"

MAX_SYMBOLS = 200
SLEEP_SECONDS = 180

LIMIT_1M = 80
LIMIT_5M = 80
LIMIT_15M = 220
LIMIT_1H = 220

WATCHLIST_EXPIRE = 60 * 60

COOLDOWN_PREP = 12 * 60 * 60
COOLDOWN_SIGNAL = 4 * 60 * 60
COOLDOWN_SWEEP = 4 * 60 * 60

WATCHLIST_MIN_SCORE = 9
PREP_NOTIFY_MIN_SCORE = 10

MIN_SPOT_15M_VOLUME_USDT = 25000
MIN_FUTURES_1M_VOLUME_USDT = 6000

MIN_CONFIDENCE_SIGNAL = 70
MAX_RISK_PCT = 4.0

sent_prep = {}
sent_signal = {}
sent_sweep = {}
watchlist = {}

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token/chat id eksik", flush=True)
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
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range.replace(0, np.nan)
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range.replace(0, np.nan)

    return df

def fetch_df(exchange, symbol, timeframe, limit):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        if not ohlcv or len(ohlcv) < 30:
            return None

        df = pd.DataFrame(
            ohlcv,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        return df

    except Exception as e:
        print(f"Fetch hata {symbol} {timeframe}: {e}", flush=True)
        return None

def build_symbols():
    try:
        markets = spot_exchange.load_markets()
        symbols = [
            s for s in markets
            if s.endswith("/USDT")
            and markets[s].get("active", True)
            and not any(x in s for x in ["UP/", "DOWN/", "3L/", "3S/", "5L/", "5S/"])
        ]

        tickers = spot_exchange.fetch_tickers(symbols)
        ranked = []

        for s in symbols:
            qv = tickers.get(s, {}).get("quoteVolume") or 0
            ranked.append((s, qv))

        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)
        return [x[0] for x in ranked[:MAX_SYMBOLS]]

    except Exception as e:
        print("Sembol listeleme hata:", e, flush=True)
        return []

def futures_symbol_exists(symbol):
    try:
        markets = future_exchange.load_markets()
        return symbol in markets
    except:
        return False

def fib_targets(df, lookback=60):
    if len(df) < lookback:
        return None

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
        "tp4": swing_low + impulse * 2.0,
        "invalid": swing_low
    }

def spot_engine(symbol):
    df15 = fetch_df(spot_exchange, symbol, "15m", LIMIT_15M)

    if df15 is None or len(df15) < 210:
        return None

    df15 = indicators(df15)

    needed = [
        "ema20", "ema50", "ema200", "ma200", "bb_width", "bb_avg",
        "vol_avg", "rsi", "roc", "macd", "macd_signal",
        "obv", "obv_ma", "body_ratio", "upper_wick", "lower_wick"
    ]

    df15 = df15.dropna(subset=needed).copy()

    if len(df15) < 20:
        return None

    last = df15.iloc[-1]
    prev = df15.iloc[-2]

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close
    change_15m = ((last.close - last.open) / last.open) * 100

    score = 0
    reasons = []

    ema_trend = last.ema20 > last.ema50 and last.close > last.ema200
    ma200_above = last.close > last.ma200
    bb_squeeze = last.bb_width < last.bb_avg
    obv_bull = last.obv > last.obv_ma
    macd_bull = last.macd > last.macd_signal and last.macd > prev.macd

    if ema_trend:
        score += 2
        reasons.append("Spot EMA trend yukarı")

    if ma200_above:
        score += 1
        reasons.append("Spot MA200 üstü")

    if bb_squeeze:
        score += 1
        reasons.append("Spot BB squeeze")

    if volume_ratio >= 1.8:
        score += 2
        reasons.append("Spot hacim hazırlık")

    if volume_ratio >= 2.5:
        score += 1
        reasons.append("Spot hacim güçlü")

    if usdt_volume >= MIN_SPOT_15M_VOLUME_USDT:
        score += 1
        reasons.append("Spot USDT hacim yeterli")

    if 52 <= last.rsi <= 68:
        score += 2
        reasons.append("RSI sağlıklı hazırlık")

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
        reasons.append("Mum gövdesi güçlü")

    if last.upper_wick <= 0.40:
        score += 1
        reasons.append("Üst fitil düşük")

    fib = fib_targets(df15)

    return {
        "score": score,
        "price": last.close,
        "volume_ratio": volume_ratio,
        "usdt_volume": usdt_volume,
        "change_15m": change_15m,
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
    if not futures_symbol_exists(symbol):
        return None

    df1 = fetch_df(future_exchange, symbol, "1m", LIMIT_1M)

    if df1 is None or len(df1) < 30:
        return None

    df1 = indicators(df1)
    df1 = df1.dropna().copy()

    if len(df1) < 25:
        return None

    last = df1.iloc[-1]
    prev3 = df1.iloc[-4]

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close

    change_1m = ((last.close - last.open) / last.open) * 100
    change_3m = ((last.close - prev3.open) / prev3.open) * 100

    score = 0
    reasons = []

    if volume_ratio >= 2.5:
        score += 2
        reasons.append("Futures hacim artışı")

    if volume_ratio >= 4.0:
        score += 2
        reasons.append("Futures hacim patlaması")

    if usdt_volume >= MIN_FUTURES_1M_VOLUME_USDT:
        score += 1
        reasons.append("Futures USDT hacim yeterli")

    if change_1m >= 0.20:
        score += 1
        reasons.append("1m momentum başladı")

    if change_3m >= 0.40:
        score += 1
        reasons.append("3m momentum var")

    if last.body_ratio >= 0.35:
        score += 1
        reasons.append("Futures mum gövdesi güçlü")

    if last.upper_wick <= 0.50:
        score += 1
        reasons.append("Üst fitil sağlıklı")

    if last.close > last.open:
        score += 1
        reasons.append("Yeşil futures mum")

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
    df = fetch_df(spot_exchange, symbol, "1h", LIMIT_1H)

    if df is None or len(df) < 210:
        return None

    df = indicators(df)
    df = df.dropna().copy()

    if len(df) < 5:
        return None

    last = df.iloc[-1]

    return {
        "trend_up": last.ema9 > last.ema21,
        "ma200_above": last.close > last.ma200,
        "ema9": last.ema9,
        "ema21": last.ema21,
        "ma200": last.ma200
    }

def five_confirm(symbol, resistance):
    df = fetch_df(spot_exchange, symbol, "5m", LIMIT_5M)

    if df is None or len(df) < 30:
        return None

    df = indicators(df)
    df = df.dropna().copy()

    if len(df) < 5:
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

def detect_sweep(symbol):
    fut = futures_engine(symbol)

    if not fut:
        return None

    df1 = fetch_df(future_exchange, symbol, "1m", LIMIT_1M)

    if df1 is None or len(df1) < 30:
        return None

    lows = df1["low"].iloc[-25:-2]
    local_support = lows.min()

    last = df1.iloc[-1]

    swept = last["low"] < local_support
    reclaimed = last["close"] > local_support

    recovery = (last["close"] - last["low"]) / (last["high"] - last["low"]) if last["high"] > last["low"] else 0

    sweep_score = 0
    reasons = []

    if fut["volume_ratio"] >= 4:
        sweep_score += 2
        reasons.append("Futures hacim patlaması")

    if fut["lower_wick"] >= 0.45:
        sweep_score += 2
        reasons.append("Alt fitil güçlü")

    if swept:
        sweep_score += 2
        reasons.append("Lokal destek altı süpürüldü")

    if reclaimed:
        sweep_score += 2
        reasons.append("Destek geri alındı")

    if recovery >= 0.35:
        sweep_score += 2
        reasons.append("İğne sonrası recovery")

    valid = (
        sweep_score >= 8
        and swept
        and reclaimed
        and fut["volume_ratio"] >= 4
        and fut["lower_wick"] >= 0.45
    )

    if not valid:
        return None

    return {
        "score": sweep_score,
        "price": fut["price"],
        "support": local_support,
        "sweep_low": last["low"],
        "recovery": recovery,
        "futures": fut,
        "reasons": reasons
    }

def classify_signal(price, resistance, five, futures):
    if not resistance:
        return "PREP"

    distance = (price - resistance) / resistance

    if distance > 0.012:
        return "FOMO"

    if abs(distance) <= 0.004 and five and five["strong"]:
        return "RETEST_LONG"

    if 0.003 < distance <= 0.012:
        if (
            five and five["breakout"]
            and futures
            and futures["volume_ratio"] >= 2.5
            and futures["change_3m"] >= 0.40
            and futures["upper_wick"] <= 0.45
        ):
            return "MOMENTUM_LONG"

    if price > resistance and five and five["breakout"]:
        return "BREAKOUT_WAIT_RETEST"

    return "PREP"

def fake_breakout_risk(spot, futures, five):
    risk = 0

    if futures and futures["upper_wick"] > 0.50:
        risk += 30

    if futures and futures["body_ratio"] < 0.35:
        risk += 20

    if futures and futures["change_3m"] < 0.40:
        risk += 20

    if spot and not spot["obv_bull"]:
        risk += 15

    if five and not five["strong"]:
        risk += 15

    risk = min(risk, 100)

    if risk <= 30:
        label = "DÜŞÜK 🟢"
    elif risk <= 60:
        label = "ORTA 🟡"
    else:
        label = "YÜKSEK 🔴"

    return risk, label

def whale_score(spot, futures):
    score = 0

    if spot and spot["volume_ratio"] >= 2:
        score += 20

    if spot and spot["obv_bull"]:
        score += 20

    if spot and spot["body_ratio"] >= 0.40:
        score += 10

    if futures and futures["volume_ratio"] >= 3:
        score += 20

    if futures and futures["usdt_volume"] >= 10000:
        score += 15

    if futures and futures["upper_wick"] <= 0.35:
        score += 15

    return min(score, 100)

def confidence_score(spot, futures, trend, five, fake_risk, whale):
    score = 0

    if spot:
        score += min(spot["score"] * 3, 35)

    if futures:
        score += min(futures["score"] * 3, 25)

    if trend and trend["trend_up"]:
        score += 10

    if trend and trend["ma200_above"]:
        score += 10

    if five and five["strong"]:
        score += 10

    score += min(whale * 0.10, 10)

    if fake_risk <= 30:
        score += 10
    elif fake_risk <= 60:
        score += 5

    return int(min(score, 100))

def make_trade_plan(price, fib, mode):
    if not fib or not price:
        return None

    resistance = fib["high"]
    support = fib["low"]

    if mode == "RETEST_LONG":
        entry = resistance
        stop = resistance * 0.985

    elif mode == "MOMENTUM_LONG":
        entry = price
        stop = resistance * 0.990

    elif mode == "LIQUIDITY_SWEEP":
        entry = price
        stop = support * 0.995

    else:
        entry = price
        stop = max(support * 0.995, price * 0.975)

    risk = entry - stop

    if risk <= 0:
        return None

    risk_pct = (risk / entry) * 100

    if risk_pct > MAX_RISK_PCT:
        return {
            "valid": False,
            "reason": f"Risk yüksek: %{risk_pct:.2f}",
            "entry": entry,
            "stop": stop,
            "risk_pct": risk_pct
        }

    tp1 = entry + risk * 1.5
    tp2 = entry + risk * 2.0
    tp3 = entry + risk * 3.0

    rr = (tp3 - entry) / risk

    return {
        "valid": True,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "risk_pct": risk_pct,
        "resistance": resistance,
        "support": support
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
    spot = spot_engine(symbol)

    if not spot:
        return None

    trend = trend_1h(symbol)

    if not trend:
        return None

    fib = spot.get("fib")

    if not fib:
        return None

    futures = futures_engine(symbol)
    five = five_confirm(symbol, fib["high"])

    base_score = spot["score"]

    prep_valid = (
        base_score >= WATCHLIST_MIN_SCORE
        and spot["usdt_volume"] >= MIN_SPOT_15M_VOLUME_USDT
        and spot["volume_ratio"] >= 1.8
        and spot["obv_bull"]
        and spot["macd_bull"]
        and trend["trend_up"]
    )

    if not prep_valid:
        print(
            symbol,
            "SPOT_SCORE:", spot["score"],
            "VOL:", round(spot["volume_ratio"], 2),
            "OBV:", spot["obv_bull"],
            "MACD:", spot["macd_bull"],
            flush=True
        )
        return None

    now = time.time()

    watchlist[symbol] = {
        "time": now,
        "spot": spot,
        "trend": trend,
        "fib": fib
    }

    if spot["score"] >= PREP_NOTIFY_MIN_SCORE:
        if symbol not in sent_prep or now - sent_prep[symbol] > COOLDOWN_PREP:
            sent_prep[symbol] = now

            msg = f"""
🟡 {BOT_SOURCE} | MEXC HYBRID HAZIRLIK

Coin: {symbol}
Fiyat: {spot['price']:.8f}

Spot Skor: {spot['score']}/16

15m Değişim: %{spot['change_15m']:.2f}
15m Spot Hacim: {int(spot['usdt_volume'])} USDT
Spot Hacim Artışı: {spot['volume_ratio']:.2f}x

RSI: {spot['rsi']:.2f}
ROC: {spot['roc']:.2f}
BB Width: {spot['bb_width']:.4f}

OBV: {'TOPLAMA ✅' if spot['obv_bull'] else 'ZAYIF ❌'}
MACD: {'YUKARI ✅' if spot['macd_bull'] else 'ZAYIF ❌'}

1H Trend: {'YUKARI ✅' if trend['trend_up'] else 'ZAYIF ❌'}
1H MA200: {'ÜSTÜ ✅' if trend['ma200_above'] else 'ALTI ❌'}

📌 Sebep:
{", ".join(spot['reasons'])}

📍 Karar:
Hazırlık güçlü.
Coin watchlist'e alındı.
Net giriş sadece hybrid onay gelirse verilecek.
""".strip()

            send_telegram(msg)

    return {
        "symbol": symbol,
        "spot": spot,
        "futures": futures,
        "trend": trend,
        "five": five,
        "fib": fib
    }

def check_signal(symbol, data):
    now = time.time()

    spot = data["spot"]
    trend = data["trend"]
    fib = data["fib"]

    futures = futures_engine(symbol)
    five = five_confirm(symbol, fib["high"])

    sweep = detect_sweep(symbol)

    mode = "PREP"

    if sweep:
        mode = "LIQUIDITY_SWEEP"
        price = sweep["price"]
    else:
        price = futures["price"] if futures else spot["price"]
        mode = classify_signal(price, fib["high"], five, futures)

    if mode in ["PREP", "BREAKOUT_WAIT_RETEST", "FOMO"]:
        return

    fake_risk, fake_label = fake_breakout_risk(spot, futures, five)
    whale = whale_score(spot, futures)
    confidence = confidence_score(spot, futures, trend, five, fake_risk, whale)

    if confidence < MIN_CONFIDENCE_SIGNAL:
        return

    key = symbol + "_" + mode

    if key in sent_signal and now - sent_signal[key] < COOLDOWN_SIGNAL:
        return

    plan = make_trade_plan(price, fib, mode)

    if not plan or not plan.get("valid"):
        return

    sent_signal[key] = now

    title_map = {
        "RETEST_LONG": "🟢 MEXC HYBRID RETEST LONG",
        "MOMENTUM_LONG": "🚀 MEXC HYBRID MOMENTUM LONG",
        "LIQUIDITY_SWEEP": "🧹 MEXC HYBRID LIQUIDITY SWEEP"
    }

    title = title_map.get(mode, "🧠 MEXC HYBRID AI SIGNAL")

    futures_text = "Futures veri yok"
    if futures:
        futures_text = f"""
Futures Hacim Artışı: {futures['volume_ratio']:.2f}x
1m Futures Hacim: {int(futures['usdt_volume'])} USDT
1m Değişim: %{futures['change_1m']:.2f}
3m Değişim: %{futures['change_3m']:.2f}
Futures Mum Gücü: {futures['body_ratio']:.2f}
Futures Üst Fitil: {futures['upper_wick']:.2f}
""".strip()

    five_text = "5m veri yok"
    if five:
        five_text = f"""
5m Kapanış: {five['close']:.8f}
5m Breakout: {'EVET ✅' if five['breakout'] else 'HAYIR ❌'}
5m Güçlü: {'EVET ✅' if five['strong'] else 'HAYIR ❌'}
5m Mum Gücü: {five['body_ratio']:.2f}
5m Üst Fitil: {five['upper_wick']:.2f}
""".strip()

    msg = f"""
🧠 {BOT_SOURCE} | {title}

Coin: {symbol}
Yön: LONG ✅
Mod: {mode}

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

🧠 Güven Skoru:
{confidence}/100

🐋 Whale Score:
{whale}/100

⚠️ Fake Breakout Riski:
{fake_label}

📈 1H Trend:
{'YUKARI ✅' if trend['trend_up'] else 'ZAYIF ❌'}

MA200:
{'ÜSTÜ ✅' if trend['ma200_above'] else 'ALTI ❌'}

SPOT:
Spot Skor: {spot['score']}/16
Spot Hacim: {int(spot['usdt_volume'])} USDT
Spot Hacim Artışı: {spot['volume_ratio']:.2f}x
RSI: {spot['rsi']:.2f}
ROC: {spot['roc']:.2f}
OBV: {'TOPLAMA ✅' if spot['obv_bull'] else 'ZAYIF ❌'}
MACD: {'YUKARI ✅' if spot['macd_bull'] else 'ZAYIF ❌'}
BB Squeeze: {'VAR ✅' if spot['bb_squeeze'] else 'YOK ❌'}

FUTURES:
{futures_text}

📌 5M ONAY:
{five_text}

📌 Karar:
Hybrid spot + futures onay geldi.
Net giriş verildi.
SL üstünde kaldıkça plan geçerli.
FOMO yapma, pozisyonu küçük ve risk sabit tut.
""".strip()

    send_telegram(msg)

    if symbol in watchlist:
        del watchlist[symbol]

def scan_watchlist():
    clean_watchlist()

    if len(watchlist) == 0:
        return

    print(f"{BOT_SOURCE} Watchlist kontrol: {len(watchlist)}", flush=True)

    for symbol in list(watchlist.keys()):
        try:
            check_signal(symbol, watchlist[symbol])
            time.sleep(0.25)
        except Exception as e:
            print("Watchlist hata:", symbol, e, flush=True)

def run_bot():
    send_telegram(f"✅ {BOT_SOURCE} | {BOT_NAME} başladı.")
    print(f"{BOT_SOURCE} | {BOT_NAME} BAŞLADI", flush=True)

    while True:
        try:
            print(f"Tarama başladı: {datetime.now()}", flush=True)

            scan_watchlist()

            symbols = build_symbols()
            print("Taranacak MEXC coin:", len(symbols), flush=True)

            for symbol in symbols:
                print("Taranıyor:", symbol, flush=True)
                analyze_symbol(symbol)
                time.sleep(0.25)

            scan_watchlist()

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(30)

@app.route("/")
def home():
    return "MEXC Hybrid AI Signal Engine Aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
