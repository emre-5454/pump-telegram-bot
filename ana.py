import time
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
TELEGRAM_CHAT_ID = "6977265844"

BOT_SOURCE = "🚄 Railway"
BOT_NAME = "PRO AI SIGNAL ENGINE"

EXCHANGE_NAME = "mexc"

MAX_SYMBOLS = 800
SLEEP_SECONDS = 90

LIMIT_15M = 300
LIMIT_1M = 80

WATCHLIST_EXPIRE = 60 * 60

COOLDOWN_PREP = 8 * 60 * 60
COOLDOWN_CONFIRM = 3 * 60 * 60

PREP_MIN_SCORE = 9
PREP_MIN_VOLUME_RATIO = 1.8
PREP_MIN_15M_VOLUME_USDT = 25000

CONFIRM_MIN_SCORE = 6
CONFIRM_MIN_VOLUME_RATIO = 2.5
CONFIRM_MIN_1M_VOLUME_USDT = 6000
CONFIRM_MIN_1M_CHANGE = 0.20
CONFIRM_MIN_3M_CHANGE = 0.40

MAX_RISK_PCT = 4.0

sent_prep = {}
sent_confirm = {}
watchlist = {}

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def get_exchange():
    ex_class = getattr(ccxt, EXCHANGE_NAME)
    return ex_class({
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": "spot"}
    })

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

    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()
    df["ma200"] = close.rolling(200).mean()

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std() * 2
    df["bb_width"] = ((basis + dev) - (basis - dev)) / basis

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

    return df

def score_15m(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close

    if last.close > last.ema200 and last.ema20 > last.ema50:
        score += 2
        reasons.append("EMA trend yukarı")

    if last.close > last.ma200:
        score += 1
        reasons.append("MA200 üstü")

    bb_avg = df["bb_width"].rolling(50).mean().iloc[-1]
    if pd.notna(bb_avg) and last.bb_width < bb_avg:
        score += 1
        reasons.append("BB squeeze")

    if volume_ratio >= PREP_MIN_VOLUME_RATIO:
        score += 2
        reasons.append("hacim hazırlık seviyesinde")

    if 52 <= last.rsi <= 68:
        score += 2
        reasons.append("RSI sağlıklı hazırlık")

    if last.roc > 0.8:
        score += 1
        reasons.append("ROC pozitif")

    if last.roc > 1.8:
        score += 1
        reasons.append("ROC güçlü")

    if last.obv > last.obv_ma:
        score += 2
        reasons.append("OBV toplama")

    if last.macd > last.macd_signal and last.macd > prev.macd:
        score += 1
        reasons.append("MACD güçleniyor")

    if last.body_ratio >= 0.35:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if last.upper_wick <= 0.40:
        score += 1
        reasons.append("üst fitil düşük")

    return score, reasons, volume_ratio, usdt_volume

def confirm_1m(df):
    if len(df) < 25:
        return None

    last = df.iloc[-1]
    prev3 = df.iloc[-4]

    vol_avg = df["volume"].rolling(20).mean().iloc[-1]
    volume_ratio = last.volume / vol_avg if vol_avg > 0 else 0

    change_1m = ((last.close - last.open) / last.open) * 100
    change_3m = ((last.close - prev3.open) / prev3.open) * 100
    usdt_volume = last.volume * last.close

    candle_range = last.high - last.low
    body_ratio = abs(last.close - last.open) / candle_range if candle_range > 0 else 0
    upper_wick = (last.high - max(last.open, last.close)) / candle_range if candle_range > 0 else 0

    score = 0
    reasons = []

    if volume_ratio >= CONFIRM_MIN_VOLUME_RATIO:
        score += 2
        reasons.append("1m hacim artışı")

    if usdt_volume >= CONFIRM_MIN_1M_VOLUME_USDT:
        score += 1
        reasons.append("1m USDT hacim yeterli")

    if change_1m >= CONFIRM_MIN_1M_CHANGE:
        score += 1
        reasons.append("1m hareket başladı")

    if change_3m >= CONFIRM_MIN_3M_CHANGE:
        score += 1
        reasons.append("3m momentum")

    if body_ratio >= 0.35:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if upper_wick <= 0.50:
        score += 1
        reasons.append("üst fitil sağlıklı")

    if last.close > last.open:
        score += 1
        reasons.append("yeşil mum")

    valid = (
        score >= CONFIRM_MIN_SCORE
        and volume_ratio >= CONFIRM_MIN_VOLUME_RATIO
        and usdt_volume >= CONFIRM_MIN_1M_VOLUME_USDT
        and change_1m >= CONFIRM_MIN_1M_CHANGE
        and change_3m >= CONFIRM_MIN_3M_CHANGE
        and body_ratio >= 0.35
        and upper_wick <= 0.50
    )

    return {
        "valid": valid,
        "score": score,
        "reasons": reasons,
        "volume_ratio": volume_ratio,
        "usdt_volume": usdt_volume,
        "change_1m": change_1m,
        "change_3m": change_3m,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick,
        "price": last.close
    }

def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    swing_low = recent["low"].min()
    swing_high = recent["high"].max()
    impulse = swing_high - swing_low

    if impulse <= 0:
        return None

    return {
        "swing_low": swing_low,
        "swing_high": swing_high
    }

def fake_breakout_risk(confirm):
    risk = 0

    if confirm["upper_wick"] > 0.45:
        risk += 35

    if confirm["body_ratio"] < 0.35:
        risk += 25

    if confirm["change_3m"] < 0.40:
        risk += 20

    if confirm["volume_ratio"] < 2.5:
        risk += 20

    risk = min(risk, 100)

    if risk <= 30:
        label = "DÜŞÜK 🟢"
    elif risk <= 60:
        label = "ORTA 🟡"
    else:
        label = "YÜKSEK 🔴"

    return risk, label

def whale_score(confirm, prep_data):
    score = 0

    if confirm["volume_ratio"] >= 2.5:
        score += 25

    if confirm["volume_ratio"] >= 4:
        score += 15

    if confirm["usdt_volume"] >= 10000:
        score += 20

    if confirm["body_ratio"] >= 0.45:
        score += 15

    if confirm["upper_wick"] <= 0.35:
        score += 10

    if prep_data.get("obv_ok", False):
        score += 15

    return min(score, 100)

def confidence_score(prep_score, confirm, fake_risk, whale):
    score = 0

    score += min(prep_score * 4, 40)
    score += min(confirm["score"] * 5, 30)
    score += min(whale * 0.2, 20)

    if fake_risk <= 30:
        score += 10
    elif fake_risk <= 60:
        score += 5

    return int(min(score, 100))

def trade_plan(entry, fib):
    if not fib:
        return None

    swing_low = fib["swing_low"]

    sl = swing_low
    risk = entry - sl

    if risk <= 0:
        return None

    risk_pct = (risk / entry) * 100

    if risk_pct > MAX_RISK_PCT:
        return {
            "valid": False,
            "reason": f"Risk çok yüksek: %{risk_pct:.2f}",
            "entry": entry,
            "sl": sl,
            "risk_pct": risk_pct
        }

    tp1 = entry + risk * 1.5
    tp2 = entry + risk * 2.0
    tp3 = entry + risk * 3.0

    rr = (tp3 - entry) / risk

    return {
        "valid": True,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pct": risk_pct,
        "rr": rr
    }

def build_symbols(exchange):
    markets = exchange.load_markets()

    symbols = [
        s for s in markets
        if s.endswith("/USDT")
        and markets[s].get("active", True)
        and not any(x in s for x in ["UP/", "DOWN/", "3L/", "3S/", "5L/", "5S/"])
    ]

    try:
        tickers = exchange.fetch_tickers(symbols)
        ranked = []

        for s in symbols:
            t = tickers.get(s, {})
            qv = t.get("quoteVolume") or 0
            ranked.append((s, qv))

        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)
        symbols = [x[0] for x in ranked]

    except Exception as e:
        print("Ticker sıralama yapılamadı:", e, flush=True)

    return symbols[:MAX_SYMBOLS]

def clean_watchlist():
    now = time.time()
    expired = []

    for symbol, data in watchlist.items():
        if now - data["time"] > WATCHLIST_EXPIRE:
            expired.append(symbol)

    for symbol in expired:
        del watchlist[symbol]

def check_confirm(exchange, symbol):
    now = time.time()

    try:
        ohlcv_1m = exchange.fetch_ohlcv(symbol, "1m", limit=LIMIT_1M)

        if not ohlcv_1m or len(ohlcv_1m) < 25:
            return

        df1 = pd.DataFrame(
            ohlcv_1m,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        confirm = confirm_1m(df1)

        if not confirm or not confirm["valid"]:
            return

        if symbol in sent_confirm and now - sent_confirm[symbol] < COOLDOWN_CONFIRM:
            return

        data = watchlist.get(symbol, {})

        plan = trade_plan(confirm["price"], data.get("fib"))

        if not plan or not plan.get("valid"):
            reason = plan.get("reason", "Plan hesaplanamadı") if plan else "Plan hesaplanamadı"

            msg = f"""
⚠️ {BOT_SOURCE} | AI SIGNAL İPTAL

Coin: {symbol}
Fiyat: {confirm['price']:.8f}

Sebep:
{reason}

📍 Karar:
Onay geldi ama risk uygun değil.
İşlem planı verilmedi.
""".strip()

            send_telegram(msg)

            if symbol in watchlist:
                del watchlist[symbol]

            return

        fake_risk, fake_label = fake_breakout_risk(confirm)
        whale = whale_score(confirm, data)
        confidence = confidence_score(data.get("score", 0), confirm, fake_risk, whale)

        if confidence < 65:
            return

        sent_confirm[symbol] = now

        msg = f"""
🧠 {BOT_SOURCE} | AI LONG SIGNAL

Coin: {symbol}
Yön: LONG ✅

Hazırlık: ✅
Onay: ✅

📍 NET GİRİŞ:
{plan['entry']:.8f}

🛑 STOP:
{plan['sl']:.8f}

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

📈 Trend:
YUKARI ✅

EMA:
{data.get('ema_status', 'Pozitif')}

MA200:
{data.get('ma200_status', 'Üstünde')}

BB Squeeze:
{data.get('bb_status', 'Var/Yakın')}

15m RSI:
{data.get('rsi', 0):.2f}

15m ROC:
{data.get('roc', 0):.2f}

1m Hacim:
{confirm['volume_ratio']:.2f}x

1m Değişim:
%{confirm['change_1m']:.2f}

3m Değişim:
%{confirm['change_3m']:.2f}

📌 Onay Sebebi:
{", ".join(confirm['reasons'])}

📍 Karar:
Net giriş seviyesi verildi.
SL üstünde kaldıkça plan geçerli.
Retest gelirse daha sağlıklı olur.
FOMO yapma, riskini sabit tut.
""".strip()

        send_telegram(msg)

        if symbol in watchlist:
            del watchlist[symbol]

    except Exception as e:
        print(f"ONAY HATA {symbol}: {e}", flush=True)

def scan_watchlist(exchange):
    clean_watchlist()

    if len(watchlist) == 0:
        return

    print(f"{BOT_SOURCE} Watchlist kontrol: {len(watchlist)}", flush=True)

    for symbol in list(watchlist.keys()):
        check_confirm(exchange, symbol)
        time.sleep(0.15)

def scan_symbol(exchange, symbol):
    now = time.time()

    try:
        ohlcv_15m = exchange.fetch_ohlcv(symbol, "15m", limit=LIMIT_15M)

        if not ohlcv_15m or len(ohlcv_15m) < 220:
            return

        df15 = pd.DataFrame(
            ohlcv_15m,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        df15 = indicators(df15)

        needed_cols = [
            "ema20", "ema50", "ema200", "ma200", "bb_width",
            "vol_avg", "rsi", "roc", "macd", "macd_signal",
            "obv", "obv_ma", "body_ratio", "upper_wick"
        ]

        df15 = df15.dropna(subset=needed_cols).copy()

        if len(df15) < 20:
            return

        score, reasons, volume_ratio, usdt_volume = score_15m(df15)
        last = df15.iloc[-1]

        change_15m = ((last.close - last.open) / last.open) * 100

        print(
            symbol,
            "SKOR:", score,
            "VOL:", round(volume_ratio, 2),
            "USDT:", int(usdt_volume),
            flush=True
        )

        prep_valid = (
            score >= PREP_MIN_SCORE
            and volume_ratio >= PREP_MIN_VOLUME_RATIO
            and usdt_volume >= PREP_MIN_15M_VOLUME_USDT
            and 52 <= last.rsi <= 68
            and last.roc > 0.8
            and last.obv > last.obv_ma
            and last.close > last.ema200
            and last.body_ratio >= 0.35
            and last.upper_wick <= 0.40
        )

        if not prep_valid:
            return

        fib = fib_targets(df15)

        watchlist[symbol] = {
            "time": now,
            "score": score,
            "rsi": last.rsi,
            "roc": last.roc,
            "fib": fib,
            "obv_ok": bool(last.obv > last.obv_ma),
            "ema_status": "EMA20 > EMA50 ve fiyat EMA200 üstü ✅",
            "ma200_status": "MA200 üstü ✅",
            "bb_status": "Sıkışma/Yakın ✅"
        }

        if symbol not in sent_prep or now - sent_prep[symbol] >= COOLDOWN_PREP:
            sent_prep[symbol] = now

            msg = f"""
🟡 {BOT_SOURCE} | AI HAZIRLIK

Coin: {symbol}
Fiyat: {last.close:.8f}

Skor: {score}/15

15dk Değişim:
%{change_15m:.2f}

15dk USDT Hacim:
{int(usdt_volume)}

Hacim Artışı:
{volume_ratio:.2f}x

RSI:
{last.rsi:.2f}

ROC:
{last.roc:.2f}

Mum Gücü:
{last.body_ratio:.2f}

Üst Fitil:
{last.upper_wick:.2f}

📌 Sebep:
{", ".join(reasons)}

📍 Karar:
Coin watchlist'e alındı.
60 dakika boyunca AI onay aranacak.
Net giriş sadece onay gelirse verilecek.
""".strip()

            send_telegram(msg)

    except Exception as e:
        print(f"HATA {symbol}: {e}", flush=True)

def main():
    send_telegram(f"✅ {BOT_SOURCE} | {BOT_NAME} botu başladı.")
    print(f"{BOT_SOURCE} BOT BASLADI", flush=True)

    exchange = get_exchange()

    while True:
        try:
            print(f"{BOT_SOURCE} Tarama başladı: {datetime.now()}", flush=True)

            scan_watchlist(exchange)

            symbols = build_symbols(exchange)

            print(f"{BOT_SOURCE} Coin sayısı: {len(symbols)}", flush=True)

            for symbol in symbols:
                scan_symbol(exchange, symbol)
                time.sleep(0.15)

            scan_watchlist(exchange)

            print(f"{BOT_SOURCE} Tur bitti. {SLEEP_SECONDS}s bekleniyor.", flush=True)

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print(f"{BOT_SOURCE} GENEL HATA:", e, flush=True)
            time.sleep(30)

if __name__ == "__main__":
    main()
