from flask import Flask
import threading, time, os, requests, ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

BOT_NAME = "🚄 MEXC FUTURES 3 KADEME AI BOT + TV RADAR"

MAX_SYMBOLS = 120
SLEEP_SECONDS = 240

SEND_EARLY_RADAR = False

LIMIT_1M = 80
LIMIT_5M = 80
LIMIT_15M = 180

MIN_RADAR_SCORE = 7
MIN_WHALE_SCORE = 7
MIN_SAFE_CONFIDENCE = 58

COOLDOWN_RADAR = 6 * 60 * 60
COOLDOWN_WHALE = 4 * 60 * 60
COOLDOWN_SAFE = 4 * 60 * 60
COOLDOWN_SWEEP = 4 * 60 * 60

MAX_RISK_PCT = 4.0

sent_radar = {}
sent_whale = {}
sent_safe = {}
sent_sweep = {}

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token/chat id eksik", flush=True)
        print(msg, flush=True)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def get_exchange():
    return ccxt.mexc({
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": "swap"}
    })

exchange = get_exchange()

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
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close, 14)
    df["roc"] = close.pct_change(9) * 100

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    candle_range = high - low
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range.replace(0, np.nan)
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range.replace(0, np.nan)

    return df

def fetch_df(symbol, timeframe, limit):
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
        markets = exchange.load_markets()
        symbols = [
            s for s in markets
            if s.endswith("/USDT:USDT") and markets[s].get("active", True)
        ]

        tickers = exchange.fetch_tickers(symbols)
        ranked = []

        for s in symbols:
            t = tickers.get(s, {})

            qv = t.get("quoteVolume") or 0
            pct = t.get("percentage") or 0
            last = t.get("last") or 0
            high = t.get("high") or 0
            low = t.get("low") or 0

            if last <= 0 or high <= 0 or low <= 0:
                continue

            volatility = ((high - low) / last) * 100

            score = 0

            if qv >= 10_000_000:
                score += 3
            elif qv >= 5_000_000:
                score += 2
            elif qv >= 2_000_000:
                score += 1

            if 1 <= pct <= 12:
                score += 3
            elif 0 <= pct <= 18:
                score += 1

            if 3 <= volatility <= 18:
                score += 3
            elif 2 <= volatility <= 25:
                score += 1

            if score >= 5:
                ranked.append((s, score, qv, pct, volatility))

        ranked = sorted(ranked, key=lambda x: (x[1], x[2]), reverse=True)
        selected = [x[0] for x in ranked[:MAX_SYMBOLS]]

        print("TradingView Radar seçilen coin:", len(selected), flush=True)
        for x in ranked[:20]:
            print(
                x[0],
                "Score:", x[1],
                "Vol:", int(x[2]),
                "24h%:", round(x[3], 2),
                "Volatility:", round(x[4], 2),
                flush=True
            )

        return selected

    except Exception as e:
        print("Sembol hata:", e, flush=True)
        return []

def fib_targets(df, lookback=60):
    if len(df) < lookback:
        return None

    recent = df.tail(lookback)
    low = recent["low"].min()
    high = recent["high"].max()
    impulse = high - low

    if impulse <= 0:
        return None

    return {
        "low": low,
        "high": high,
        "tp1": high,
        "tp2": low + impulse * 1.272,
        "tp3": low + impulse * 1.618,
        "tp4": low + impulse * 2.0
    }

def one_min_engine(symbol):
    df = fetch_df(symbol, "1m", LIMIT_1M)
    if df is None or len(df) < 30:
        return None

    df = indicators(df).dropna().copy()
    if len(df) < 25:
        return None

    last = df.iloc[-1]
    prev3 = df.iloc[-4]

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close

    change_1m = ((last.close - last.open) / last.open) * 100
    change_3m = ((last.close - prev3.open) / prev3.open) * 100

    score = 0
    reasons = []

    if volume_ratio >= 1.3:
        score += 1
        reasons.append("hacim uyanıyor")

    if volume_ratio >= 1.8:
        score += 2
        reasons.append("hacim artışı var")

    if volume_ratio >= 3.0:
        score += 2
        reasons.append("hacim patlaması var")

    if usdt_volume >= 3000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if change_1m >= 0.05:
        score += 1
        reasons.append("1m fiyat tepki verdi")

    if change_3m >= 0.12:
        score += 1
        reasons.append("3m momentum başladı")

    if last.body_ratio >= 0.25:
        score += 1
        reasons.append("mum gövdesi yeterli")

    if last.upper_wick <= 0.65:
        score += 1
        reasons.append("üst fitil makul")

    if last.close > last.open:
        score += 1
        reasons.append("yeşil mum")

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
        "reasons": reasons,
        "df": df
    }

def trend_15m(symbol):
    df = fetch_df(symbol, "15m", LIMIT_15M)
    if df is None or len(df) < 120:
        return None

    df = indicators(df).dropna().copy()
    if len(df) < 50:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "trend_up": last.ema9 > last.ema21,
        "ema200_above": last.close > last.ema200,
        "macd_bull": last.macd > last.macd_signal and last.macd > prev.macd,
        "rsi": last.rsi,
        "roc": last.roc,
        "fib": fib_targets(df),
        "df": df
    }

def five_confirm(symbol, resistance):
    df = fetch_df(symbol, "5m", LIMIT_5M)
    if df is None or len(df) < 30:
        return None

    df = indicators(df).dropna().copy()
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

def early_radar_mode(one, trend):
    score = 0
    reasons = []

    if one["volume_ratio"] >= 2.2:
        score += 2
        reasons.append("hacim güçlü uyanıyor")

    if one["usdt_volume"] >= 10000:
        score += 1
        reasons.append("USDT hacim güçlü")

    if one["change_3m"] >= 0.12:
        score += 1
        reasons.append("3m momentum başladı")

    if one["lower_wick"] >= 0.20:
        score += 1
        reasons.append("alt fitil/dip tepkisi var")

    if one["upper_wick"] <= 0.60:
        score += 1
        reasons.append("üst fitil sağlıklı")

    if trend and 38 <= trend["rsi"] <= 72:
        score += 1
        reasons.append("15m RSI uygun")

    if trend and trend["macd_bull"]:
        score += 2
        reasons.append("15m MACD yukarı")

    valid = (
        score >= MIN_RADAR_SCORE
        and one["volume_ratio"] >= 2.2
        and one["usdt_volume"] >= 10000
        and one["change_3m"] >= 0.12
        and trend
        and trend["macd_bull"]
    )

    return valid, score, reasons

def whale_entry_mode(one, trend):
    score = 0
    reasons = []

    if one["volume_ratio"] >= 2.0:
        score += 2
        reasons.append("futures hacim artışı")

    if one["usdt_volume"] >= 8000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if one["change_3m"] >= 0.15:
        score += 1
        reasons.append("3m momentum başladı")

    if one["body_ratio"] >= 0.30:
        score += 1
        reasons.append("mum gövdesi yeterli")

    if one["upper_wick"] <= 0.55:
        score += 1
        reasons.append("üst fitil sağlıklı")

    if one["lower_wick"] >= 0.15:
        score += 1
        reasons.append("alt fitil desteği var")

    if trend and trend["macd_bull"]:
        score += 2
        reasons.append("15m MACD yukarı")

    if trend and 40 <= trend["rsi"] <= 72:
        score += 1
        reasons.append("15m RSI uygun")

    valid = (
        score >= MIN_WHALE_SCORE
        and one["volume_ratio"] >= 2.0
        and one["usdt_volume"] >= 8000
        and trend
        and trend["macd_bull"]
    )

    return valid, score, reasons

def sweep_mode(one):
    df = one["df"]
    old_lows = df["low"].iloc[-25:-2]
    local_support = old_lows.min()
    last = df.iloc[-1]

    candle_range = last.high - last.low
    if candle_range <= 0:
        return False, 0, None

    swept = last.low < local_support
    reclaimed = last.close > local_support
    recovery = (last.close - last.low) / candle_range

    score = 0
    reasons = []

    if one["volume_ratio"] >= 3.5:
        score += 2
        reasons.append("hacim patlaması")

    if one["lower_wick"] >= 0.45:
        score += 2
        reasons.append("alt fitil güçlü")

    if swept:
        score += 2
        reasons.append("lokal destek süpürüldü")

    if reclaimed:
        score += 2
        reasons.append("destek geri alındı")

    if recovery >= 0.40:
        score += 2
        reasons.append("recovery güçlü")

    valid = (
        score >= 8
        and swept
        and reclaimed
        and one["volume_ratio"] >= 3.5
        and one["lower_wick"] >= 0.45
    )

    data = {
        "score": score,
        "support": local_support,
        "sweep_low": last.low,
        "recovery": recovery,
        "reasons": reasons
    }

    return valid, score, data

def safe_long_mode(one, trend, five):
    if not trend or not five:
        return False

    return (
        one["score"] >= 7
        and one["volume_ratio"] >= 2.0
        and one["change_3m"] >= 0.20
        and one["upper_wick"] <= 0.55
        and trend["macd_bull"]
        and five["breakout"]
    )

def fake_breakout_risk(one, five):
    risk = 0

    if one["upper_wick"] > 0.65:
        risk += 35

    if one["body_ratio"] < 0.25:
        risk += 25

    if one["change_3m"] < 0.12:
        risk += 20

    if five and not five["strong"]:
        risk += 20

    risk = min(risk, 100)

    if risk <= 30:
        label = "DÜŞÜK 🟢"
    elif risk <= 60:
        label = "ORTA 🟡"
    else:
        label = "YÜKSEK 🔴"

    return risk, label

def confidence_score(one, trend, five, mode, fake_risk):
    score = 0

    score += min(one["score"] * 5, 40)

    if trend and trend["trend_up"]:
        score += 10

    if trend and trend["ema200_above"]:
        score += 10

    if trend and trend["macd_bull"]:
        score += 10

    if five and five["breakout"]:
        score += 8

    if five and five["strong"]:
        score += 8

    if mode == "SAFE_LONG":
        score += 10

    if mode == "WHALE_ENTRY":
        score += 6

    if mode == "SWEEP_LONG":
        score += 12

    if fake_risk <= 30:
        score += 10
    elif fake_risk <= 60:
        score += 5

    return int(min(score, 100))

def trade_plan(price, fib, mode):
    if not fib or not price:
        return None

    support = fib["low"]
    resistance = fib["high"]

    if mode == "SAFE_LONG":
        entry = price
        stop = max(resistance * 0.990, price * 0.970)
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
        "risk_pct": risk_pct,
        "rr": rr
    }

def can_send(cache, key, cooldown):
    now = time.time()

    if key in cache and now - cache[key] < cooldown:
        return False

    cache[key] = now
    return True

def send_early_radar(symbol, one, trend, radar_score, radar_reasons):
    key = symbol + "_RADAR"

    if not can_send(sent_radar, key, COOLDOWN_RADAR):
        return

    msg = f"""
👀 {BOT_NAME} | EARLY RADAR

Coin: {symbol}

Bu işlem sinyali değildir.
Coin uyanıyor olabilir.

Radar Skoru: {radar_score}/9

Fiyat:
{one['price']:.8f}

1m Hacim:
{int(one['usdt_volume'])} USDT

Hacim Artışı:
{one['volume_ratio']:.2f}x

1m Değişim:
%{one['change_1m']:.2f}

3m Değişim:
%{one['change_3m']:.2f}

15m RSI:
{trend['rsi']:.2f}

15m MACD:
{'YUKARI ✅' if trend['macd_bull'] else 'ZAYIF ❌'}

📌 Sebep:
{", ".join(radar_reasons)}

📍 Karar:
Sadece radar.
Giriş için WHALE ENTRY veya SAFE LONG bekle.
""".strip()

    send_telegram(msg)

def format_trade_signal(symbol, one, trend, five, mode, confidence, fake_label, plan, title, extra_text=""):
    five_text = "5m veri yok"
    if five:
        five_text = f"""
5m Kapanış: {five['close']:.8f}
Breakout: {'EVET ✅' if five['breakout'] else 'HAYIR ❌'}
Güçlü: {'EVET ✅' if five['strong'] else 'HAYIR ❌'}
Mum Gücü: {five['body_ratio']:.2f}
Üst Fitil: {five['upper_wick']:.2f}
""".strip()

    return f"""
🧠 {BOT_NAME}

Mod: {title}
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

⚠️ Fake Breakout:
{fake_label}

1m Futures Hacim:
{int(one['usdt_volume'])} USDT

Hacim Artışı:
{one['volume_ratio']:.2f}x

1m Değişim:
%{one['change_1m']:.2f}

3m Değişim:
%{one['change_3m']:.2f}

Mum Gücü:
{one['body_ratio']:.2f}

Üst Fitil:
{one['upper_wick']:.2f}

Alt Fitil:
{one['lower_wick']:.2f}

15m Trend:
{'YUKARI ✅' if trend['trend_up'] else 'ZAYIF ❌'}

15m EMA200:
{'ÜSTÜ ✅' if trend['ema200_above'] else 'ALTI ❌'}

15m MACD:
{'YUKARI ✅' if trend['macd_bull'] else 'ZAYIF ❌'}

15m RSI:
{trend['rsi']:.2f}

📌 5M:
{five_text}

{extra_text}

📍 Karar:
Bu otomatik işlem değildir.
Radar → Whale → Safe Long kademeli sistemde bu seviye oluştu.
Riskini sabit tut, FOMO yapma.
""".strip()

def analyze(symbol):
    try:
        one = one_min_engine(symbol)

        if not one:
            return

        trend = trend_15m(symbol)

        if not trend or not trend["fib"]:
            return

        five = five_confirm(symbol, trend["fib"]["high"])

        radar_valid, radar_score, radar_reasons = early_radar_mode(one, trend)

        if radar_valid and SEND_EARLY_RADAR:
            send_early_radar(symbol, one, trend, radar_score, radar_reasons)

        sweep_valid, sweep_score, sweep_data = sweep_mode(one)
        whale_valid, whale_score_value, whale_reasons = whale_entry_mode(one, trend)
        safe_valid = safe_long_mode(one, trend, five)

        mode = None
        title = None
        extra_text = ""

        if sweep_valid:
            mode = "SWEEP_LONG"
            title = "🧹 LIQUIDITY SWEEP"
            extra_text = f"""
Sweep Skoru: {sweep_data['score']}/10
Süpürülen Destek: {sweep_data['support']:.8f}
Sweep Dibi: {sweep_data['sweep_low']:.8f}
Recovery: {sweep_data['recovery']:.2f}

Sweep Sebebi:
{", ".join(sweep_data['reasons'])}
""".strip()

        elif safe_valid:
            mode = "SAFE_LONG"
            title = "🟢 SAFE LONG"

        elif whale_valid:
            mode = "WHALE_ENTRY"
            title = "🐋 WHALE ENTRY"
            extra_text = f"""
Whale Entry Skoru: {whale_score_value}/10

Whale Sebebi:
{", ".join(whale_reasons)}
""".strip()

        if not mode:
            print(
                symbol,
                "RADAR:", radar_score,
                "ONE:", one["score"],
                "VOL:", round(one["volume_ratio"], 2),
                "3M:", round(one["change_3m"], 2),
                "RSI15:", round(trend["rsi"], 2),
                flush=True
            )
            return

        fake_risk, fake_label = fake_breakout_risk(one, five)
        confidence = confidence_score(one, trend, five, mode, fake_risk)

        if mode == "SAFE_LONG" and confidence < MIN_SAFE_CONFIDENCE:
            return

        plan = trade_plan(one["price"], trend["fib"], mode)

        if not plan:
            return

        key = symbol + "_" + mode

        if mode == "SAFE_LONG":
            cache = sent_safe
            cooldown = COOLDOWN_SAFE
        elif mode == "SWEEP_LONG":
            cache = sent_sweep
            cooldown = COOLDOWN_SWEEP
        else:
            cache = sent_whale
            cooldown = COOLDOWN_WHALE

        if not can_send(cache, key, cooldown):
            return

        msg = format_trade_signal(
            symbol,
            one,
            trend,
            five,
            mode,
            confidence,
            fake_label,
            plan,
            title,
            extra_text
        )

        send_telegram(msg)
        print("SINYAL:", symbol, mode, confidence, flush=True)

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)

def run_bot():
    send_telegram(f"✅ {BOT_NAME} başladı. TradingView Radar coin eleme aktif.")
    print(BOT_NAME, "BAŞLADI", flush=True)

    while True:
        try:
            print("Tarama başladı:", datetime.now(), flush=True)

            symbols = build_symbols()
            print("Taranacak futures coin:", len(symbols), flush=True)

            for symbol in symbols:
                analyze(symbol)
                time.sleep(0.35)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(30)

@app.route("/")
def home():
    return "MEXC Futures 3 Kademe AI Bot + TV Radar Aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
