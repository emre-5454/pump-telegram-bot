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

MAX_SYMBOLS = 120
SLEEP_SECONDS = 240

LIMIT_1M = 80
LIMIT_5M = 80
LIMIT_15M = 220
LIMIT_1H = 220

WATCHLIST_EXPIRE = 60 * 60

SEND_PREP_MESSAGES = False

WATCHLIST_MIN_SCORE = 8
MIN_CONFIDENCE = 58
RECOVERY_MIN_CONFIDENCE = 55
SWEEP_MIN_CONFIDENCE = 75
WHALE_MIN_CONFIDENCE = 55

MAX_RISK_PCT = 4.0

COOLDOWN_SIGNAL = 4 * 60 * 60
COOLDOWN_RECOVERY = 3 * 60 * 60
COOLDOWN_SWEEP = 4 * 60 * 60
COOLDOWN_WHALE = 3 * 60 * 60

sent_signal = {}
sent_recovery = {}
sent_sweep = {}
sent_whale = {}
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
        "options": {"defaultType": default_type}
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
        return pd.DataFrame(
            ohlcv,
            columns=["time", "open", "high", "low", "close", "volume"]
        )
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
        print("Sembol hata:", e, flush=True)
        return []

def futures_exists(symbol):
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
        "tp4": swing_low + impulse * 2.0
    }

def spot_engine(symbol):
    df15 = fetch_df(spot_exchange, symbol, "15m", LIMIT_15M)
    if df15 is None or len(df15) < 210:
        return None

    df15 = indicators(df15)
    df15 = df15.dropna().copy()

    if len(df15) < 30:
        return None

    last = df15.iloc[-1]
    prev = df15.iloc[-2]

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close
    change_15m = ((last.close - last.open) / last.open) * 100

    ema_trend = last.ema20 > last.ema50 and last.close > last.ema200
    ma200_above = last.close > last.ma200
    bb_squeeze = last.bb_width < last.bb_avg
    obv_bull = last.obv > last.obv_ma
    macd_bull = last.macd > last.macd_signal and last.macd > prev.macd

    score = 0
    reasons = []

    if ema_trend:
        score += 2
        reasons.append("EMA trend yukarı")
    if ma200_above:
        score += 1
        reasons.append("MA200 üstü")
    if bb_squeeze:
        score += 1
        reasons.append("BB squeeze")
    if volume_ratio >= 1.5:
        score += 2
        reasons.append("Spot hacim girişi")
    if volume_ratio >= 2.5:
        score += 1
        reasons.append("Spot hacim güçlü")
    if usdt_volume >= 10000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if 42 <= last.rsi <= 72:
        score += 2
        reasons.append("RSI uygun")
    if last.roc > 0:
        score += 1
        reasons.append("ROC pozitife dönüyor")
    if obv_bull:
        score += 2
        reasons.append("OBV toplama")
    if macd_bull:
        score += 1
        reasons.append("MACD yukarı")
    if last.body_ratio >= 0.30:
        score += 1
        reasons.append("Mum gövdesi yeterli")
    if last.upper_wick <= 0.55:
        score += 1
        reasons.append("Üst fitil kabul edilebilir")

    fib = fib_targets(df15)

    return {
        "score": score,
        "price": last.close,
        "change_15m": change_15m,
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

    if volume_ratio >= 1.8:
        score += 2
        reasons.append("Futures hacim artışı")
    if volume_ratio >= 3.5:
        score += 2
        reasons.append("Futures hacim patlaması")
    if usdt_volume >= 4000:
        score += 1
        reasons.append("Futures USDT hacim yeterli")
    if change_1m >= 0.10:
        score += 1
        reasons.append("1m momentum başladı")
    if change_3m >= 0.12:
        score += 1
        reasons.append("3m momentum var")
    if last.body_ratio >= 0.25:
        score += 1
        reasons.append("Futures mum gövdesi yeterli")
    if last.upper_wick <= 0.60:
        score += 1
        reasons.append("Üst fitil kabul edilebilir")
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

    if len(df) < 10:
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

    if len(df) < 10:
        return None

    last = df.iloc[-1]
    breakout = last.close > resistance
    strong = breakout and last.body_ratio >= 0.35 and last.upper_wick <= 0.55

    return {
        "close": last.close,
        "breakout": breakout,
        "strong": strong,
        "body_ratio": last.body_ratio,
        "upper_wick": last.upper_wick
    }

def whale_entry_mode(spot, futures):
    if not spot:
        return False, 0

    score = 0
    reasons = []

    if spot["volume_ratio"] >= 1.5:
        score += 2
        reasons.append("Spot hacim girişi var")

    if spot["usdt_volume"] >= 10000:
        score += 1
        reasons.append("Spot USDT hacim yeterli")

    if spot["obv_bull"]:
        score += 2
        reasons.append("OBV alttan toparlıyor")

    if spot["macd_bull"]:
        score += 1
        reasons.append("MACD yukarı dönüyor")

    if 38 <= spot["rsi"] <= 68:
        score += 1
        reasons.append("RSI dipten çıkış bölgesi")

    if spot["lower_wick"] >= 0.25:
        score += 1
        reasons.append("Alt fitil / dip tepkisi var")

    if spot["roc"] > -0.5:
        score += 1
        reasons.append("ROC toparlıyor")

    if futures:
        if futures["volume_ratio"] >= 1.8:
            score += 2
            reasons.append("Futures hacim destekliyor")

        if futures["change_3m"] >= 0.12:
            score += 1
            reasons.append("Futures 3m hareket var")

    valid = (
        score >= 7
        and spot["volume_ratio"] >= 1.5
        and spot["usdt_volume"] >= 10000
        and spot["obv_bull"]
    )

    return valid, score, reasons

def recovery_mode(spot, futures):
    if not spot:
        return False, 0

    score = 0

    if spot["lower_wick"] >= 0.30:
        score += 2
    if spot["volume_ratio"] >= 1.8:
        score += 2
    if spot["obv_bull"]:
        score += 2
    if spot["macd_bull"]:
        score += 1
    if 42 <= spot["rsi"] <= 72:
        score += 1
    if spot["roc"] > 0:
        score += 1
    if futures:
        if futures["volume_ratio"] >= 1.8:
            score += 2
        if futures["change_3m"] >= 0.12:
            score += 1
        if futures["upper_wick"] <= 0.60:
            score += 1

    return score >= 7, score

def sweep_mode(symbol, spot):
    futures = futures_engine(symbol)

    if not futures or not spot:
        return False, 0, None

    if not spot["obv_bull"]:
        return False, 0, None

    df1 = fetch_df(future_exchange, symbol, "1m", LIMIT_1M)
    if df1 is None or len(df1) < 30:
        return False, 0, None

    old_lows = df1["low"].iloc[-25:-2]
    local_support = old_lows.min()
    last = df1.iloc[-1]

    candle_range = last["high"] - last["low"]
    if candle_range <= 0:
        return False, 0, None

    swept = last["low"] < local_support
    reclaimed = last["close"] > local_support
    recovery = (last["close"] - last["low"]) / candle_range

    score = 0
    reasons = []

    if futures["volume_ratio"] >= 4:
        score += 2
        reasons.append("Futures hacim patlaması")
    if futures["lower_wick"] >= 0.45:
        score += 2
        reasons.append("Alt fitil güçlü")
    if swept:
        score += 2
        reasons.append("Lokal destek süpürüldü")
    if reclaimed:
        score += 2
        reasons.append("Destek geri alındı")
    if recovery >= 0.40:
        score += 2
        reasons.append("Recovery güçlü")
    if spot["obv_bull"]:
        score += 2
        reasons.append("Spot OBV destekliyor")

    valid = (
        score >= 10
        and swept
        and reclaimed
        and futures["volume_ratio"] >= 4
        and futures["lower_wick"] >= 0.45
    )

    data = {
        "score": score,
        "support": local_support,
        "sweep_low": last["low"],
        "recovery": recovery,
        "futures": futures,
        "reasons": reasons
    }

    return valid, score, data

def fake_breakout_risk(spot, futures, five):
    risk = 0

    if futures and futures["upper_wick"] > 0.60:
        risk += 30
    if futures and futures["body_ratio"] < 0.25:
        risk += 20
    if futures and futures["change_3m"] < 0.12:
        risk += 20
    if spot and not spot["obv_bull"]:
        risk += 20
    if five and not five["strong"]:
        risk += 10

    risk = min(risk, 100)

    if risk <= 30:
        label = "DÜŞÜK 🟢"
    elif risk <= 60:
        label = "ORTA 🟡"
    else:
        label = "YÜKSEK 🔴"

    return risk, label

def whale_score_calc(spot, futures, whale_entry=False):
    score = 0

    if spot and spot["volume_ratio"] >= 1.5:
        score += 20
    if spot and spot["volume_ratio"] >= 2.5:
        score += 10
    if spot and spot["obv_bull"]:
        score += 25
    if spot and spot["body_ratio"] >= 0.30:
        score += 10
    if futures and futures["volume_ratio"] >= 1.8:
        score += 15
    if futures and futures["usdt_volume"] >= 6000:
        score += 10
    if futures and futures["upper_wick"] <= 0.55:
        score += 10
    if whale_entry:
        score += 10

    return min(score, 100)

def confidence_score(spot, futures, trend, five, fake_risk, whale, recovery=False, sweep=False, whale_entry=False):
    score = 0

    if spot:
        score += min(spot["score"] * 3, 40)
    if futures:
        score += min(futures["score"] * 2, 20)
    if trend and trend["trend_up"]:
        score += 6
    if trend and trend["ma200_above"]:
        score += 6
    if five and five["strong"]:
        score += 6
    if recovery:
        score += 8
    if sweep:
        score += 10
    if whale_entry:
        score += 10

    score += min(whale * 0.08, 8)

    if fake_risk <= 30:
        score += 8
    elif fake_risk <= 60:
        score += 4

    return int(min(score, 100))

def trade_plan(price, fib, mode):
    if not fib or not price:
        return None

    resistance = fib["high"]
    support = fib["low"]

    if mode == "SAFE_LONG":
        entry = resistance
        stop = resistance * 0.985
    elif mode == "RECOVERY_LONG":
        entry = price
        stop = max(support * 0.995, price * 0.965)
    elif mode == "SWEEP_LONG":
        entry = price
        stop = max(support * 0.995, price * 0.965)
    elif mode == "WHALE_ENTRY":
        entry = price
        stop = max(support * 0.995, price * 0.970)
    else:
        entry = price
        stop = max(support * 0.995, price * 0.970)

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

        fib = spot.get("fib")
        if not fib:
            return

        prep_valid = (
            spot["score"] >= WATCHLIST_MIN_SCORE
            and spot["usdt_volume"] >= 10000
            and spot["volume_ratio"] >= 1.5
            and spot["obv_bull"]
        )

        if not prep_valid:
            print(
                symbol,
                "SKOR:", spot["score"],
                "VOL:", round(spot["volume_ratio"], 2),
                "OBV:", spot["obv_bull"],
                flush=True
            )
            return

        watchlist[symbol] = {
            "time": time.time(),
            "spot": spot,
            "trend": trend,
            "fib": fib
        }

    except Exception as e:
        print("Analyze hata:", symbol, e, flush=True)

def check_signal(symbol, data):
    try:
        spot = data["spot"]
        trend = data["trend"]
        fib = data["fib"]

        futures = None
        if spot["score"] >= 8:
            futures = futures_engine(symbol)

        five = five_confirm(symbol, fib["high"])

        sweep_valid, sweep_score, sweep_data = sweep_mode(symbol, spot)
        recovery_valid, recovery_score = recovery_mode(spot, futures)
        whale_valid, whale_entry_score, whale_reasons = whale_entry_mode(spot, futures)

        mode = None

        if sweep_valid:
            mode = "SWEEP_LONG"
        elif recovery_valid:
            mode = "RECOVERY_LONG"
        elif whale_valid:
            mode = "WHALE_ENTRY"
        else:
            if (
                futures
                and five
                and five["breakout"]
                and futures["volume_ratio"] >= 1.8
                and futures["change_3m"] >= 0.12
                and futures["upper_wick"] <= 0.60
            ):
                mode = "SAFE_LONG"

        if not mode:
            return

        fake_risk, fake_label = fake_breakout_risk(spot, futures, five)
        whale = whale_score_calc(spot, futures, whale_entry=(mode == "WHALE_ENTRY"))

        confidence = confidence_score(
            spot,
            futures,
            trend,
            five,
            fake_risk,
            whale,
            recovery=(mode == "RECOVERY_LONG"),
            sweep=(mode == "SWEEP_LONG"),
            whale_entry=(mode == "WHALE_ENTRY")
        )

        required = MIN_CONFIDENCE
        cache = sent_signal
        cooldown = COOLDOWN_SIGNAL

        if mode == "RECOVERY_LONG":
            required = RECOVERY_MIN_CONFIDENCE
            cache = sent_recovery
            cooldown = COOLDOWN_RECOVERY
        elif mode == "SWEEP_LONG":
            required = SWEEP_MIN_CONFIDENCE
            cache = sent_sweep
            cooldown = COOLDOWN_SWEEP
        elif mode == "WHALE_ENTRY":
            required = WHALE_MIN_CONFIDENCE
            cache = sent_whale
            cooldown = COOLDOWN_WHALE

        if confidence < required:
            return

        price = futures["price"] if futures else spot["price"]
        plan = trade_plan(price, fib, mode)

        if not plan:
            return

        key = symbol + "_" + mode
        now = time.time()

        if key in cache and now - cache[key] < cooldown:
            return

        cache[key] = now

        title_map = {
            "SAFE_LONG": "🟢 SAFE LONG",
            "RECOVERY_LONG": "🚀 RECOVERY LONG",
            "SWEEP_LONG": "🧹 STRONG LIQUIDITY SWEEP",
            "WHALE_ENTRY": "🐋 WHALE ENTRY"
        }

        futures_text = "Futures veri yok"
        if futures:
            futures_text = f"""
Futures Hacim: {futures['volume_ratio']:.2f}x
1m Değişim: %{futures['change_1m']:.2f}
3m Değişim: %{futures['change_3m']:.2f}
Mum Gücü: {futures['body_ratio']:.2f}
Üst Fitil: {futures['upper_wick']:.2f}
Alt Fitil: {futures['lower_wick']:.2f}
""".strip()

        five_text = "5m veri yok"
        if five:
            five_text = f"""
5m Kapanış: {five['close']:.8f}
Breakout: {'EVET ✅' if five['breakout'] else 'HAYIR ❌'}
Güçlü: {'EVET ✅' if five['strong'] else 'HAYIR ❌'}
""".strip()

        whale_text = ""
        if mode == "WHALE_ENTRY":
            whale_text = f"""
🐋 Whale Entry Sebebi:
{", ".join(whale_reasons)}
""".strip()

        msg = f"""
🧠 🚄 MEXC HYBRID AI SIGNAL

Mod: {title_map.get(mode, mode)}
Coin: {symbol}
Yön: LONG ✅

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

🐋 Whale Score:
{whale}/100

⚠️ Fake Breakout:
{fake_label}

SPOT:
Spot Skor: {spot['score']}/16
Spot Hacim: {spot['volume_ratio']:.2f}x
USDT Hacim: {int(spot['usdt_volume'])}
RSI: {spot['rsi']:.2f}
ROC: {spot['roc']:.2f}
OBV: {'TOPLAMA ✅' if spot['obv_bull'] else 'ZAYIF ❌'}
MACD: {'YUKARI ✅' if spot['macd_bull'] else 'ZAYIF ❌'}

FUTURES:
{futures_text}

5M:
{five_text}

{whale_text}

Trend:
{'YUKARI ✅' if trend['trend_up'] else 'ZAYIF ❌'}

MA200:
{'ÜSTÜ ✅' if trend['ma200_above'] else 'ALTI ❌'}

📍 Karar:
Bu otomatik işlem değildir.
Balina/Recovery/Onay yapısı oluştuğu için plan verildi.
Riskini sabit tut, FOMO yapma.
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

    print("Watchlist:", len(watchlist), flush=True)

    for symbol in list(watchlist.keys()):
        check_signal(symbol, watchlist[symbol])
        time.sleep(0.40)

def run_bot():
    send_telegram(f"✅ {BOT_NAME} başladı. Hazırlık kapalı, Whale Entry aktif.")
    print(BOT_NAME, "BAŞLADI", flush=True)

    while True:
        try:
            print("Tarama başladı:", datetime.now(), flush=True)

            scan_watchlist()

            symbols = build_symbols()
            print("Coin sayısı:", len(symbols), flush=True)

            for symbol in symbols:
                analyze_symbol(symbol)
                time.sleep(0.40)

            scan_watchlist()

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(30)

@app.route("/")
def home():
    return "MEXC HYBRID AI ENGINE AKTIF", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
