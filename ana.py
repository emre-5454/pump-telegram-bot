from flask import Flask
import threading, time, os, requests, ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "🚄 MEXC EARLY + GOLD + SAFE + DIP + BREAKOUT BOT"

MAX_SYMBOLS = 200
SLEEP_SECONDS = 30

COOLDOWN_EARLY = 30 * 60
COOLDOWN_SAFE = 45 * 60
COOLDOWN_GOLD = 30 * 60
COOLDOWN_DIP = 60 * 60
COOLDOWN_BREAKOUT = 30 * 60

MIN_EARLY_RS = 70
MIN_SAFE_CONFIDENCE = 68
MIN_GOLD_SCORE = 12
MIN_BREAKOUT_SCORE = 10
MAX_RISK_PCT = 4.5

sent_early = {}
sent_safe = {}
sent_gold = {}
sent_dip = {}
sent_breakout = {}

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
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

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

    df["recovery_ratio"] = (close - low) / candle_range.replace(0, np.nan)

    df["obv"] = np.where(
        close > close.shift(1),
        volume,
        np.where(close < close.shift(1), -volume, 0)
    ).cumsum()

    return df


def fetch_df(symbol, timeframe, limit=150):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not data or len(data) < 60:
            return None

        df = pd.DataFrame(
            data,
            columns=["time", "open", "high", "low", "close", "volume"]
        )
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

    except Exception:
        return {"ok": True, "rate": 0, "status": "VERİ YOK"}


def btc_filter():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERİ YOK"

    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.macd > last.macd_signal and last.rsi >= 42

    return ok, "BTC DESTEKLİ ✅" if ok else "BTC ZAYIF ❌"


def build_universe():
    try:
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

            if qv < 1_000_000:
                continue

            if volatility < 1.0:
                continue

            rows.append({
                "symbol": s,
                "qv": qv,
                "pct": pct,
                "last": last,
                "high": high,
                "low": low,
                "volatility": volatility
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

    except Exception as e:
        print("Universe hata:", e, flush=True)
        return []


def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    low = recent["low"].min()
    high = recent["high"].max()
    impulse = high - low

    if impulse <= 0:
        return None

    return {"low": low, "high": high}


def late_risk_filter(df15):
    last = df15.iloc[-1]
    recent_low = df15["low"].tail(96).min()
    dist_from_low = ((last.close - recent_low) / recent_low) * 100 if recent_low > 0 else 999
    ema21_distance = ((last.close - last.ema21) / last.ema21) * 100 if last.ema21 > 0 else 999

    too_late = dist_from_low > 45 or ema21_distance > 18 or last.rsi > 88
    return not too_late, dist_from_low, ema21_distance


def early_radar(symbol, rs):
    df1h = fetch_df(symbol, "1h", 120)
    df15 = fetch_df(symbol, "15m", 120)

    if df1h is None or df15 is None:
        return False, None

    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]

    vol_ratio_1h = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    vol_ratio_15m = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0

    usdt_vol_1h = h1.volume * h1.close
    usdt_vol_15m = m15.volume * m15.close

    obv_up_1h = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-6]
    obv_up_15m = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    macd_turn_1h = h1.macd > h1_prev.macd
    macd_turn_15m = m15.macd > m15_prev.macd

    macd_cross_near = (
        h1.macd > h1.macd_signal or
        abs(h1.macd - h1.macd_signal) < abs(h1.macd) * 0.45
    )

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

    if vol_ratio_1h >= 1.4:
        score += 2
        reasons.append("1H hacim uyanıyor")

    if vol_ratio_15m >= 1.5:
        score += 2
        reasons.append("15m hacim erken artıyor")

    if usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if 42 <= h1.rsi <= 85:
        score += 2
        reasons.append("RSI erken/aktif bölge")

    if obv_up_1h or obv_up_15m:
        score += 2
        reasons.append("OBV para girişi")

    if macd_turn_1h or macd_turn_15m:
        score += 1
        reasons.append("MACD toparlanıyor")

    if macd_cross_near:
        score += 1
        reasons.append("MACD kesişime yakın")

    if dist_from_low <= 35:
        score += 2
        reasons.append("24s dibinden çok uzak değil")

    if bb_expanding:
        score += 1
        reasons.append("Bollinger açılmaya başlıyor")

    if m15.close > m15.ema21:
        score += 1
        reasons.append("15m EMA21 üstü")

    valid = (
        score >= 8
        and rs >= MIN_EARLY_RS
        and (vol_ratio_1h >= 1.4 or vol_ratio_15m >= 1.5)
        and (obv_up_1h or obv_up_15m)
        and (macd_turn_1h or macd_turn_15m)
        and 42 <= h1.rsi <= 85
        and dist_from_low <= 35
    )

    return valid, {
        "score": score,
        "price": h1.close,
        "rs": rs,
        "vol_ratio_1h": vol_ratio_1h,
        "vol_ratio_15m": vol_ratio_15m,
        "usdt_vol_1h": usdt_vol_1h,
        "usdt_vol_15m": usdt_vol_15m,
        "rsi": h1.rsi,
        "dist_from_low": dist_from_low,
        "bb_expanding": bb_expanding,
        "reasons": reasons
    }


def breakout_radar(symbol, rs, btc_ok, funding):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)

    if df5 is None or df15 is None:
        return False, None

    m5 = df5.iloc[-1]
    m5_prev = df5.iloc[-2]
    t15 = df15.iloc[-1]
    t15_prev = df15.iloc[-2]

    ok_late, dist_from_low, ema21_distance = late_risk_filter(df15)
    if not ok_late:
        return False, None

    resistance_15 = df15["high"].tail(24).iloc[:-1].max()
    breakout = t15.close > resistance_15

    vol_ratio_15m = t15.volume / t15.vol_avg if t15.vol_avg > 0 else 0
    usdt_vol_15m = t15.volume * t15.close

    bb_squeeze = df15["bb_width"].iloc[-6:].mean() < df15["bb_width"].iloc[-30:-6].mean()
    bb_expanding_now = t15.bb_width > df15["bb_width"].iloc[-3]

    macd_up = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    trend_up = t15.close > t15.ema21 and t15.ema9 > t15.ema21
    body_ok = t15.body_ratio >= 0.45
    wick_ok = t15.upper_wick <= 0.40

    score = 0
    reasons = []

    if rs >= 72:
        score += 2
        reasons.append("RS güçlü")

    if breakout:
        score += 3
        reasons.append("15m direnç kırılımı")

    if vol_ratio_15m >= 2.0:
        score += 2
        reasons.append("15m hacim patlaması")

    if usdt_vol_15m >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if bb_squeeze or bb_expanding_now:
        score += 2
        reasons.append("Bollinger sıkışma/açılma")

    if macd_up:
        score += 2
        reasons.append("MACD pozitif")

    if obv_up:
        score += 2
        reasons.append("OBV para girişi")

    if trend_up:
        score += 1
        reasons.append("15m trend yukarı")

    if body_ok:
        score += 1
        reasons.append("Güçlü gövde")

    if wick_ok:
        score += 1
        reasons.append("Üst fitil sağlıklı")

    if btc_ok:
        score += 1
        reasons.append("BTC destekli")
    else:
        score -= 1

    if funding["ok"]:
        score += 1
        reasons.append("Funding uygun")
    else:
        score -= 1

    valid = (
        score >= MIN_BREAKOUT_SCORE
        and breakout
        and vol_ratio_15m >= 2.0
        and usdt_vol_15m >= 25000
        and macd_up
        and obv_up
        and trend_up
        and body_ok
        and wick_ok
    )

    return valid, {
        "score": score,
        "price": t15.close,
        "rs": rs,
        "vol_ratio_15m": vol_ratio_15m,
        "usdt_vol_15m": usdt_vol_15m,
        "rsi15": t15.rsi,
        "dist_from_low": dist_from_low,
        "ema21_distance": ema21_distance,
        "breakout": breakout,
        "bb_squeeze": bb_squeeze,
        "bb_expanding_now": bb_expanding_now,
        "macd_up": macd_up,
        "obv_up": obv_up,
        "body": t15.body_ratio,
        "upper_wick": t15.upper_wick,
        "reasons": reasons
    }


def gold_long(symbol, rs, btc_ok, funding):
    df1m = fetch_df(symbol, "1m", 90)
    df5 = fetch_df(symbol, "5m", 100)
    df15 = fetch_df(symbol, "15m", 150)

    if df1m is None or df5 is None or df15 is None:
        return False, None

    ok_late, dist_from_low, ema21_distance = late_risk_filter(df15)
    if not ok_late:
        return False, None

    m1 = df1m.iloc[-1]
    prev3 = df1m.iloc[-4]
    m5 = df5.iloc[-1]
    t15 = df15.iloc[-1]
    t15_prev = df15.iloc[-2]

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100

    trend_up = t15.ema9 > t15.ema21
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]
    ma200_up = t15.close > t15.ema200
    bb_break = t15.close >= t15.bb_upper * 0.995
    body_ok = m5.body_ratio >= 0.38
    wick_ok = m5.upper_wick <= 0.45

    score = 0
    reasons = []

    if rs >= 75:
        score += 2
        reasons.append("RS güçlü")

    if vol_ratio >= 2.2:
        score += 2
        reasons.append("1m hacim güçlü")

    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if change_3m >= 0.25:
        score += 2
        reasons.append("3m momentum var")

    if trend_up:
        score += 1
        reasons.append("15m trend yukarı")

    if macd_bull:
        score += 2
        reasons.append("15m MACD pozitif")

    if obv_up:
        score += 2
        reasons.append("OBV para girişi")

    if ma200_up:
        score += 1
        reasons.append("EMA200 üstü")

    if bb_break:
        score += 1
        reasons.append("BB üst banda yakın/kırılım")

    if body_ok:
        score += 1
        reasons.append("5m gövde güçlü")

    if wick_ok:
        score += 1
        reasons.append("Üst fitil sağlıklı")

    if btc_ok:
        score += 1
        reasons.append("BTC destekli")
    else:
        score -= 1

    if funding["ok"]:
        score += 1
        reasons.append("Funding uygun")
    else:
        score -= 1

    valid = (
        score >= MIN_GOLD_SCORE
        and rs >= 75
        and vol_ratio >= 2.2
        and usdt_vol >= 25000
        and change_3m >= 0.20
        and trend_up
        and macd_bull
        and obv_up
        and body_ok
        and wick_ok
    )

    return valid, {
        "score": score,
        "price": m1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "change_3m": change_3m,
        "rsi15": t15.rsi,
        "trend_up": trend_up,
        "macd_bull": macd_bull,
        "obv_up": obv_up,
        "ma200_up": ma200_up,
        "bb_break": bb_break,
        "body": m5.body_ratio,
        "upper_wick": m5.upper_wick,
        "dist_from_low": dist_from_low,
        "ema21_distance": ema21_distance,
        "reasons": reasons
    }


def safe_long(symbol, rs, btc_ok, funding):
    df1m = fetch_df(symbol, "1m", 90)
    df5 = fetch_df(symbol, "5m", 100)
    df15 = fetch_df(symbol, "15m", 150)

    if df1m is None or df5 is None or df15 is None:
        return False, None

    ok_late, dist_from_low, ema21_distance = late_risk_filter(df15)
    if not ok_late:
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
    strong_breakout = breakout and m5.body_ratio >= 0.38 and m5.upper_wick <= 0.55

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100

    trend_up = t15.ema9 > t15.ema21
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd

    score = 0

    if rs >= 70:
        score += 12
    if vol_ratio >= 2.2:
        score += 15
    if usdt_vol >= 25000:
        score += 10
    if change_3m >= 0.20:
        score += 10
    if trend_up:
        score += 10
    if macd_bull:
        score += 10
    if 48 <= t15.rsi <= 88:
        score += 8
    if strong_breakout:
        score += 15
    if btc_ok:
        score += 5
    else:
        score -= 5
    if funding["ok"]:
        score += 5
    else:
        score -= 5

    confidence = max(0, min(100, score))

    valid = (
        confidence >= MIN_SAFE_CONFIDENCE
        and vol_ratio >= 2.2
        and usdt_vol >= 25000
        and change_3m >= 0.20
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
        "risk_pct": risk_pct,
        "dist_from_low": dist_from_low,
        "ema21_distance": ema21_distance
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
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 72
    macd_turn = h1.macd > h1_prev.macd
    trend_not_dead = h1.close > h1.ema50 or h1.close > h1.ema200 * 0.97
    strong_wick = h1.lower_wick >= 0.45
    reclaimed = h1.recovery_ratio >= 0.55

    score = 0
    reasons = []

    if bb_touch:
        score += 3
        reasons.append("4H alt Bollinger tepki")

    if vol_ratio >= 2.0:
        score += 2
        reasons.append("1H hacim güçlü")

    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim güçlü")

    if strong_wick:
        score += 2
        reasons.append("Güçlü alt fitil")

    if reclaimed:
        score += 2
        reasons.append("İğneden toparladı")

    if obv_up:
        score += 2
        reasons.append("OBV yukarı")

    if rsi_turn:
        score += 2
        reasons.append("RSI dipten dönüyor")

    if macd_turn:
        score += 1
        reasons.append("MACD toparlanıyor")

    if trend_not_dead:
        score += 2
        reasons.append("Trend tamamen ölü değil")

    if rs >= 65:
        score += 1
        reasons.append("RS fena değil")

    valid = (
        score >= 12
        and bb_touch
        and vol_ratio >= 2.0
        and strong_wick
        and reclaimed
        and obv_up
        and rsi_turn
        and trend_not_dead
    )

    return valid, {
        "score": score,
        "price": h1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "lower_wick": h1.lower_wick,
        "recovery": h1.recovery_ratio,
        "trend_not_dead": trend_not_dead,
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
{d['score']}/17

Fiyat:
{d['price']:.8f}

1H Hacim Artışı:
{d['vol_ratio_1h']:.2f}x

15m Hacim Artışı:
{d['vol_ratio_15m']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol_1h'])} USDT

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

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


def format_breakout(symbol, d, funding, btc_status):
    return f"""
🔥 {BOT_NAME}

Mod: BREAKOUT RADAR
Coin: {symbol}
Yön: LONG ADAYI ✅

Sıkışma sonrası kırılım adayı.

Breakout Skoru:
{d['score']}/18

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

15m Hacim Artışı:
{d['vol_ratio_15m']:.2f}x

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

15m RSI:
{d['rsi15']:.2f}

24s Dipten Uzaklık:
%{d['dist_from_low']:.2f}

EMA21 Uzaklık:
%{d['ema21_distance']:.2f}

Breakout:
{'VAR ✅' if d['breakout'] else 'YOK ❌'}

Bollinger:
{'Sıkışma/Açılma ✅' if d['bb_squeeze'] or d['bb_expanding_now'] else 'NORMAL'}

MACD:
{'POZİTİF ✅' if d['macd_up'] else 'ZAYIF ❌'}

OBV:
{'PARA GİRİŞİ ✅' if d['obv_up'] else 'ZAYIF ❌'}

Gövde:
%{d['body'] * 100:.1f}

Üst Fitil:
%{d['upper_wick'] * 100:.1f}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Kırılım radarı.
FOMO değil; 5m retest veya mum kapanışı takip.
""".strip()


def format_gold(symbol, d, funding, btc_status):
    return f"""
🏆 {BOT_NAME}

Mod: GOLD LONG
Coin: {symbol}
Yön: LONG ADAYI ✅

Bu en kaliteli takip alarmıdır.

GOLD Skoru:
{d['score']}/18

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

1m Hacim Artışı:
{d['vol_ratio']:.2f}x

1m USDT Hacim:
{int(d['usdt_vol'])} USDT

3m Değişim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

24s Dipten Uzaklık:
%{d['dist_from_low']:.2f}

EMA21 Uzaklık:
%{d['ema21_distance']:.2f}

15m Trend:
{'YUKARI ✅' if d['trend_up'] else 'ZAYIF ❌'}

15m MACD:
{'YUKARI ✅' if d['macd_bull'] else 'ZAYIF ❌'}

OBV:
{'PARA GİRİŞİ ✅' if d['obv_up'] else 'ZAYIF ❌'}

EMA200:
{'ÜSTÜ ✅' if d['ma200_up'] else 'ALTI ❌'}

BB:
{'ÜST BANT YAKIN/KIRILIM ✅' if d['bb_break'] else 'NORMAL'}

5m Gövde:
%{d['body'] * 100:.1f}

5m Üst Fitil:
%{d['upper_wick'] * 100:.1f}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Öncelikli takip.
FOMO değil; mümkünse 5m retest veya küçük geri çekilme bekle.
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

24s Dipten Uzaklık:
%{d['dist_from_low']:.2f}

EMA21 Uzaklık:
%{d['ema21_distance']:.2f}

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
Onaylı giriş bölgesi.
Stop şart, FOMO yok.
""".strip()


def format_dip(symbol, d, funding, btc_status):
    return f"""
🟣 {BOT_NAME}

Mod: STRONG DIP RADAR
Coin: {symbol}

Bu direkt long değildir.
Dipten güçlü balina tepkisi olabilir.

RS Skoru:
{d['rs']:.1f}/100

Dip Skoru:
{d['score']}/17

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

İğneden Toparlanma:
%{d['recovery'] * 100:.1f}

Trend:
{'TAM ÖLÜ DEĞİL ✅' if d['trend_not_dead'] else 'ZAYIF ❌'}

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

        breakout_ok, breakout_data = breakout_radar(symbol, rs, btc_ok, funding)

        if breakout_ok and can_send(sent_breakout, symbol + "_BREAKOUT", COOLDOWN_BREAKOUT):
            send_telegram(format_breakout(symbol, breakout_data, funding, btc_status))
            print("BREAKOUT:", symbol, breakout_data["score"], flush=True)

        gold_ok, gold_data = gold_long(symbol, rs, btc_ok, funding)

        if gold_ok and can_send(sent_gold, symbol + "_GOLD", COOLDOWN_GOLD):
            send_telegram(format_gold(symbol, gold_data, funding, btc_status))
            print("GOLD:", symbol, gold_data["score"], flush=True)

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)

        if safe_ok and can_send(sent_safe, symbol + "_SAFE", COOLDOWN_SAFE):
            send_telegram(format_safe(symbol, safe_data, funding, btc_status))
            print("SAFE:", symbol, safe_data["confidence"], flush=True)

        dip_ok, dip_data = big_dip_radar(symbol, rs)

        if dip_ok and can_send(sent_dip, symbol + "_DIP", COOLDOWN_DIP):
            send_telegram(format_dip(symbol, dip_data, funding, btc_status))
            print("DIP:", symbol, round(rs, 1), flush=True)

        if not early_ok and not breakout_ok and not gold_ok and not safe_ok and not dip_ok:
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
    send_telegram(f"✅ {BOT_NAME} başladı. EARLY + BREAKOUT + GOLD + SAFE + DIP aktif.")
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
                time.sleep(0.25)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"⚠️ Bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "MEXC EARLY + BREAKOUT + GOLD + SAFE + DIP Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
