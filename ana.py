from flask import Flask
import threading, time, os, requests, ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

BOT_NAME = "🚄 MEXC RS EARLY RADAR + SAFE LONG BOT"

MAX_SYMBOLS = 120
SLEEP_SECONDS = 180

COOLDOWN_EARLY = 4 * 60 * 60
COOLDOWN_SAFE = 6 * 60 * 60
COOLDOWN_DIP = 6 * 60 * 60
COOLDOWN_SWEEP = 6 * 60 * 60

MIN_EARLY_RS = 80
MIN_SAFE_CONFIDENCE = 68
MAX_RISK_PCT = 4.0

sent_early = {}
sent_safe = {}
sent_dip = {}
sent_sweep = {}

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
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

def can_send(cache, key, cooldown):
    now = time.time()
    if key in cache and now - cache[key] < cooldown:
        return False
    cache[key] = now
    return True

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
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std()
    df["bb_upper"] = basis + dev * 2
    df["bb_lower"] = basis - dev * 2
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / basis.replace(0, np.nan)

    candle_range = high - low
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range.replace(0, np.nan)
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range.replace(0, np.nan)

    df["obv"] = np.where(
        close > close.shift(1),
        volume,
        np.where(close < close.shift(1), -volume, 0)
    ).cumsum()

    return df

def fetch_df(symbol, timeframe, limit=120):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not data or len(data) < 40:
            return None
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
        return indicators(df).dropna().copy()
    except Exception as e:
        print("Fetch hata:", symbol, timeframe, e, flush=True)
        return None

def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0
        if -0.001 <= rate <= 0.0015:
            return {"ok": True, "rate": rate, "status": "NORMAL ✅"}
        elif rate > 0.0015:
            return {"ok": False, "rate": rate, "status": "LONG KALABALIK ⚠️"}
        else:
            return {"ok": True, "rate": rate, "status": "SHORT BASKI ⚠️"}
    except:
        return {"ok": True, "rate": 0, "status": "VERİ YOK"}

def btc_filter():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERİ YOK"
    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.macd > last.macd_signal and last.rsi >= 45
    return (ok, "BTC DESTEKLİ ✅" if ok else "BTC ZAYIF ❌")

def build_universe():
    markets = exchange.load_markets()
    symbols = [
        s for s in markets
        if s.endswith("/USDT:USDT") and markets[s].get("active", True)
    ]

    tickers = exchange.fetch_tickers(symbols)
    rows = []

    for s in symbols:
        t = tickers.get(s, {})
        qv = t.get("quoteVolume") or 0
        pct = t.get("percentage") or 0
        last = t.get("last") or 0
        high = t.get("high") or 0
        low = t.get("low") or 0

        if last <= 0 or high <= 0 or low <= 0 or qv <= 0:
            continue

        volatility = ((high - low) / last) * 100

        if qv < 2_000_000:
            continue
        if volatility < 2:
            continue

        base_score = 0
        if qv >= 15_000_000: base_score += 3
        elif qv >= 8_000_000: base_score += 2
        elif qv >= 4_000_000: base_score += 1

        if -8 <= pct <= 18: base_score += 2
        if 3 <= volatility <= 30: base_score += 2

        rows.append({
            "symbol": s,
            "qv": qv,
            "pct": pct,
            "last": last,
            "high": high,
            "low": low,
            "volatility": volatility,
            "base_score": base_score
        })

    if not rows:
        return []

    df = pd.DataFrame(rows)

    df["pct_rank"] = df["pct"].rank(pct=True) * 100
    df["vol_rank"] = df["qv"].rank(pct=True) * 100
    df["volatility_rank"] = df["volatility"].rank(pct=True) * 100

    df["rs_score"] = (
        df["pct_rank"] * 0.45 +
        df["vol_rank"] * 0.30 +
        df["volatility_rank"] * 0.25
    )

    df = df.sort_values(["rs_score", "qv"], ascending=False).head(MAX_SYMBOLS)

    result = df.to_dict("records")

    print("RS evren seçildi:", len(result), flush=True)
    for r in result[:15]:
        print(
            r["symbol"],
            "RS:", round(r["rs_score"], 1),
            "24h%:", round(r["pct"], 2),
            "Vol:", int(r["qv"]),
            flush=True
        )

    return result

def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    low = recent["low"].min()
    high = recent["high"].max()
    impulse = high - low
    if impulse <= 0:
        return None
    return {"low": low, "high": high}

def early_radar(symbol, rs):
    df1h = fetch_df(symbol, "1h", 120)
    df15 = fetch_df(symbol, "15m", 120)

    if df1h is None or df15 is None:
        return False, None

    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]

    vol_ratio = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    usdt_vol = h1.volume * h1.close

    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-6]
    macd_turn = h1.macd > h1_prev.macd
    macd_cross_near = h1.macd > h1.macd_signal or abs(h1.macd - h1.macd_signal) < abs(h1.macd) * 0.35

    low_24h = df1h["low"].tail(24).min()
    dist_from_low = ((h1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    bb_now = df1h["bb_width"].iloc[-1]
    bb_prev = df1h["bb_width"].iloc[-6]
    bb_expanding = bb_now > bb_prev

    score = 0
    reasons = []

    if rs >= MIN_EARLY_RS:
        score += 3
        reasons.append("RS güçlü")
    if vol_ratio >= 1.8:
        score += 2
        reasons.append("1H hacim uyanıyor")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if 45 <= h1.rsi <= 72:
        score += 2
        reasons.append("RSI erken bölge")
    if obv_up:
        score += 2
        reasons.append("OBV para girişi")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlanıyor")
    if macd_cross_near:
        score += 1
        reasons.append("MACD kesişime yakın")
    if dist_from_low <= 18:
        score += 2
        reasons.append("24s dibinden çok uzak değil")
    if bb_expanding:
        score += 1
        reasons.append("Bollinger açılmaya başlıyor")

    valid = (
        score >= 10
        and rs >= MIN_EARLY_RS
        and vol_ratio >= 1.8
        and obv_up
        and macd_turn
        and 45 <= h1.rsi <= 72
        and dist_from_low <= 18
    )

    return valid, {
        "score": score,
        "price": h1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "dist_from_low": dist_from_low,
        "bb_expanding": bb_expanding,
        "reasons": reasons,
        "df15": df15,
        "df1h": df1h
    }

def safe_long(symbol, rs, btc_ok, funding):
    df1m = fetch_df(symbol, "1m", 90)
    df5 = fetch_df(symbol, "5m", 100)
    df15 = fetch_df(symbol, "15m", 150)

    if df1m is None or df5 is None or df15 is None:
        return False, None

    m1 = df1m.iloc[-1]
    prev3 = df1m.iloc[-4]
    m5 = df5.iloc[-1]
    t15 = df15.iloc[-1]
    t15_prev = df15.iloc[-2]

    fib = fib_targets(df15)
    if not fib:
        return False, None

    resistance = fib["high"]
    breakout = m5.close > resistance
    strong_breakout = breakout and m5.body_ratio >= 0.42 and m5.upper_wick <= 0.48

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100

    trend_up = t15.ema9 > t15.ema21
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd

    score = 0
    if rs >= 80: score += 12
    if vol_ratio >= 3.0: score += 15
    if usdt_vol >= 40000: score += 10
    if change_3m >= 0.35: score += 10
    if trend_up: score += 10
    if macd_bull: score += 10
    if 48 <= t15.rsi <= 78: score += 8
    if strong_breakout: score += 15
    if btc_ok: score += 5
    else: score -= 5
    if funding["ok"]: score += 5
    else: score -= 5

    confidence = max(0, min(100, score))

    valid = (
        confidence >= MIN_SAFE_CONFIDENCE
        and vol_ratio >= 3.0
        and usdt_vol >= 35000
        and change_3m >= 0.30
        and trend_up
        and macd_bull
        and strong_breakout
    )

    price = m1.close
    stop = max(resistance * 0.990, price * 0.970)
    risk = price - stop

    if risk <= 0:
        return False, None

    risk_pct = (risk / price) * 100
    if risk_pct > MAX_RISK_PCT:
        return False, None

    return valid, {
        "price": price,
        "confidence": confidence,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "change_3m": change_3m,
        "rsi15": t15.rsi,
        "trend_up": trend_up,
        "macd_bull": macd_bull,
        "breakout": breakout,
        "strong_breakout": strong_breakout,
        "entry": price,
        "stop": stop,
        "tp1": price + risk * 1.5,
        "tp2": price + risk * 2.0,
        "tp3": price + risk * 3.0,
        "risk_pct": risk_pct
    }

def big_dip_radar(symbol, rs):
    df1h = fetch_df(symbol, "1h", 120)
    df4h = fetch_df(symbol, "4h", 120)

    if df1h is None or df4h is None:
        return False, None

    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    h4 = df4h.iloc[-1]
    h4_prev = df4h.iloc[-2]

    bb_touch = h4.low <= h4.bb_lower or h4_prev.low <= h4_prev.bb_lower
    vol_ratio = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    usdt_vol = h1.volume * h1.close
    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-5]
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 68
    macd_turn = h1.macd > h1_prev.macd

    score = 0
    reasons = []

    if bb_touch:
        score += 3; reasons.append("4H alt Bollinger tepki")
    if vol_ratio >= 2.2:
        score += 2; reasons.append("1H hacim patlaması")
    if usdt_vol >= 40000:
        score += 1; reasons.append("USDT hacim güçlü")
    if h1.lower_wick >= 0.35:
        score += 2; reasons.append("alt fitil")
    if obv_up:
        score += 2; reasons.append("OBV yukarı")
    if rsi_turn:
        score += 2; reasons.append("RSI dipten dönüyor")
    if macd_turn:
        score += 1; reasons.append("MACD toparlanıyor")
    if rs >= 70:
        score += 1; reasons.append("RS fena değil")

    valid = score >= 10 and bb_touch and vol_ratio >= 2.2 and obv_up and rsi_turn

    return valid, {
        "score": score,
        "price": h1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "lower_wick": h1.lower_wick,
        "reasons": reasons
    }

def format_early(symbol, d, funding, btc_status):
    return f"""
👀 {BOT_NAME}

Mod: EARLY RADAR
Coin: {symbol}

Bu işlem sinyali değildir.
Coin uyanıyor olabilir.

RS Skoru:
{d['rs']:.1f}/100

Radar Skoru:
{d['score']}/15

Fiyat:
{d['price']:.8f}

1H Hacim Artışı:
{d['vol_ratio']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

24s Dipten Uzaklık:
%{d['dist_from_low']:.2f}

Bollinger:
{'Açılıyor ✅' if d['bb_expanding'] else 'Henüz zayıf'}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Takibe al.
5m/15m kırılım gelmeden direkt long değil.
""".strip()

def format_safe(symbol, d, funding, btc_status):
    return f"""
🚀 {BOT_NAME}

Mod: SAFE LONG
Coin: {symbol}
Yön: LONG ✅

RS Skoru:
{d['rs']:.1f}/100

Güven:
{d['confidence']}/100

📍 Giriş:
{d['entry']:.8f}

🛑 Stop:
{d['stop']:.8f}

🎯 TP1:
{d['tp1']:.8f}

🎯 TP2:
{d['tp2']:.8f}

🎯 TP3:
{d['tp3']:.8f}

Risk:
%{d['risk_pct']:.2f}

1m Hacim:
{int(d['usdt_vol'])} USDT

Hacim Artışı:
{d['vol_ratio']:.2f}x

3m Değişim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

15m Trend:
{'YUKARI ✅' if d['trend_up'] else 'ZAYIF ❌'}

15m MACD:
{'YUKARI ✅' if d['macd_bull'] else 'ZAYIF ❌'}

5m Breakout:
{'GÜÇLÜ ✅' if d['strong_breakout'] else 'ZAYIF ❌'}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Karar:
EARLY RADAR sonrası onaylı giriş bölgesi.
Stop şart, FOMO yok.
""".strip()

def format_dip(symbol, d, funding, btc_status):
    return f"""
🟣 {BOT_NAME}

Mod: BIG DIP RADAR
Coin: {symbol}

Bu direkt long değildir.
Dipten balina tepkisi olabilir.

RS Skoru:
{d['rs']:.1f}/100

Dip Skoru:
{d['score']}/14

Fiyat:
{d['price']:.8f}

1H Hacim Artışı:
{d['vol_ratio']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

Alt Fitil:
%{d['lower_wick'] * 100:.1f}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dip radar.
5m/15m retest ve kırılım bekle.
""".strip()

def analyze(item, btc_ok, btc_status):
    symbol = item["symbol"]
    rs = item["rs_score"]
    funding = get_funding(symbol)

    try:
        early_ok, early_data = early_radar(symbol, rs)
        if early_ok and can_send(sent_early, symbol + "_EARLY", COOLDOWN_EARLY):
            send_telegram(format_early(symbol, early_data, funding, btc_status))
            print("EARLY:", symbol, round(rs, 1), flush=True)

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        if safe_ok and can_send(sent_safe, symbol + "_SAFE", COOLDOWN_SAFE):
            send_telegram(format_safe(symbol, safe_data, funding, btc_status))
            print("SAFE:", symbol, safe_data["confidence"], flush=True)

        dip_ok, dip_data = big_dip_radar(symbol, rs)
        if dip_ok and can_send(sent_dip, symbol + "_DIP", COOLDOWN_DIP):
            send_telegram(format_dip(symbol, dip_data, funding, btc_status))
            print("DIP:", symbol, round(rs, 1), flush=True)

        if not early_ok and not safe_ok and not dip_ok:
            print(
                symbol,
                "RS:", round(rs, 1),
                "Funding:", funding["status"],
                "İÇ FİLTRE",
                flush=True
            )

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)

def run_bot():
    send_telegram(f"✅ {BOT_NAME} başladı. RS Skoru + EARLY RADAR aktif.")
    print(BOT_NAME, "BAŞLADI", flush=True)

    while True:
        try:
            print("Tarama başladı:", datetime.now(), flush=True)

            btc_ok, btc_status = btc_filter()
            print("BTC:", btc_status, flush=True)

            universe = build_universe()
            print("Taranacak coin:", len(universe), flush=True)

            for item in universe:
                analyze(item, btc_ok, btc_status)
                time.sleep(0.35)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            time.sleep(30)

@app.route("/")
def home():
    return "MEXC RS EARLY RADAR + SAFE LONG Bot Aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
