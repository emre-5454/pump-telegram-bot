import os, time, threading, requests, ccxt
import pandas as pd
import numpy as np
from flask import Flask
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "🚀 BINANCE FUTURES PRO BOT | LONG + SWEEP + MSB + SHORT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 45

EARLY_MAX_DISTANCE_FROM_24H_LOW = 8
TRADE_MAX_DISTANCE_FROM_24H_LOW = 5
SWEEP_MAX_DISTANCE_FROM_24H_LOW = 6
SQUEEZE_MAX_DISTANCE_FROM_24H_LOW = 18

COOLDOWN_EARLY = 60 * 60
COOLDOWN_GOLD = 45 * 60
COOLDOWN_SWEEP = 60 * 60
COOLDOWN_SHORT = 60 * 60
COOLDOWN_SQUEEZE = 45 * 60

sent = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {
        "defaultType": "future",
        "adjustForTimeDifference": True
    }
})


def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text, flush=True)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)


def can_send(key, cooldown):
    now = time.time()
    if key in sent and now - sent[key] < cooldown:
        return False
    sent[key] = now
    return True


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema100"] = close.ewm(span=100, adjust=False).mean()
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
    df["bb_mid"] = basis
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

    return df.dropna().copy()


def fetch_df(symbol, timeframe, limit=200):
    for _ in range(3):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data or len(data) < 80:
                return None
            df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
            return add_indicators(df)
        except Exception as e:
            print("Veri hata:", symbol, timeframe, e, flush=True)
            time.sleep(2)
    return None


def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0
        if -0.001 <= rate <= 0.0015:
            return rate, "NORMAL ✅", True
        if rate > 0.0015:
            return rate, "LONG KALABALIK ⚠️", False
        return rate, "SHORT BASKI ⚠️", True
    except Exception:
        return 0, "VERİ YOK", True


def btc_status():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERİ YOK"

    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.rsi >= 42 and last.macd >= last.macd_signal
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

            if qv < 1_000_000 or last <= 0 or high <= 0 or low <= 0:
                continue

            volatility = ((high - low) / last) * 100
            dist_low = ((last - low) / low) * 100

            if volatility < 1.0:
                continue

            rows.append({
                "symbol": s,
                "qv": qv,
                "pct": pct,
                "last": last,
                "high": high,
                "low": low,
                "volatility": volatility,
                "dist_low": dist_low
            })

        if not rows:
            return []

        df = pd.DataFrame(rows)
        df["pct_rank"] = df["pct"].rank(pct=True) * 100
        df["vol_rank"] = df["qv"].rank(pct=True) * 100
        df["volatility_rank"] = df["volatility"].rank(pct=True) * 100

        df["rs_score"] = (
            df["pct_rank"] * 0.40 +
            df["vol_rank"] * 0.35 +
            df["volatility_rank"] * 0.25
        )

        df = df.sort_values(["rs_score", "qv"], ascending=False).head(MAX_SYMBOLS)
        return df.to_dict("records")

    except Exception as e:
        print("Universe hata:", e, flush=True)
        return []


def early_radar(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    if dist_low > EARLY_MAX_DISTANCE_FROM_24H_LOW:
        return False, None

    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]

    vol_ratio_15 = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_15 = m15.volume * m15.close

    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    macd_turn = h1.macd > h1_prev.macd
    ema_ok = m15.close > m15.ema21
    rsi_ok = 42 <= h1.rsi <= 70

    score = 0
    reasons = []

    if rs >= 62:
        score += 2; reasons.append("RS güçlü")
    if vol_ratio_15 >= 1.5:
        score += 2; reasons.append("15m hacim erken artıyor")
    if usdt_15 >= 25000:
        score += 1; reasons.append("USDT hacim yeterli")
    if rsi_ok:
        score += 2; reasons.append("RSI erken/aktif bölge")
    if obv_up:
        score += 2; reasons.append("OBV para girişi")
    if macd_turn:
        score += 2; reasons.append("MACD toparlanıyor")
    if ema_ok:
        score += 2; reasons.append("15m EMA21 üstü")
    if btc_ok:
        score += 1; reasons.append("BTC destekli")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = score >= 11 and rs >= 62 and vol_ratio_15 >= 1.5 and usdt_15 >= 25000 and ema_ok and obv_up

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "vol_ratio_15": vol_ratio_15,
        "usdt_15": usdt_15,
        "rsi": h1.rsi,
        "dist_low": dist_low,
        "reasons": reasons,
        "btc": btc_text,
        "funding_rate": funding_rate,
        "funding_text": funding_text
    }


def gold_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    if dist_low > TRADE_MAX_DISTANCE_FROM_24H_LOW:
        return False, None

    df1m = fetch_df(symbol, "1m", 100)
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    if df1m is None or df5 is None or df15 is None:
        return False, None

    m1 = df1m.iloc[-1]
    prev3 = df1m.iloc[-4]
    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]

    vol_ratio_1m = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_1m = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100

    trend_up = m15.ema9 > m15.ema21
    macd_up = m15.macd > m15.macd_signal and m15.macd > m15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    ema200_up = m15.close > m15.ema200
    bb_ok = m15.close >= m15.bb_upper * 0.985
    body_ok = m5.body_ratio >= 0.40
    wick_ok = m5.upper_wick <= 0.45

    score = 0
    reasons = []

    if rs >= 70:
        score += 2; reasons.append("RS güçlü")
    if vol_ratio_1m >= 2.2:
        score += 2; reasons.append("1m hacim güçlü")
    if usdt_1m >= 30000:
        score += 1; reasons.append("USDT hacim yeterli")
    if change_3m >= 0.25:
        score += 2; reasons.append("3m momentum var")
    if trend_up:
        score += 2; reasons.append("15m trend yukarı")
    if macd_up:
        score += 2; reasons.append("MACD yukarı")
    if obv_up:
        score += 2; reasons.append("OBV para girişi")
    if ema200_up:
        score += 1; reasons.append("EMA200 üstü")
    if bb_ok:
        score += 1; reasons.append("BB üst bant yakın/kırılım")
    if body_ok:
        score += 1; reasons.append("5m gövde güçlü")
    if wick_ok:
        score += 1; reasons.append("Üst fitil sağlıklı")
    if btc_ok:
        score += 1; reasons.append("BTC destekli")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = (
        score >= 14
        and rs >= 70
        and vol_ratio_1m >= 2.2
        and usdt_1m >= 30000
        and change_3m >= 0.25
        and trend_up
        and macd_up
        and obv_up
        and body_ok
        and wick_ok
    )

    return valid, {
        "score": score,
        "price": m1.close,
        "rs": rs,
        "vol_ratio_1m": vol_ratio_1m,
        "usdt_1m": usdt_1m,
        "change_3m": change_3m,
        "rsi15": m15.rsi,
        "dist_low": dist_low,
        "body": m5.body_ratio,
        "upper_wick": m5.upper_wick,
        "reasons": reasons,
        "btc": btc_text,
        "funding_rate": funding_rate,
        "funding_text": funding_text
    }


def sweep_msb_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    if dist_low > SWEEP_MAX_DISTANCE_FROM_24H_LOW:
        return False, None

    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    df4h = fetch_df(symbol, "4h", 150)
    if df5 is None or df15 is None or df1h is None or df4h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    h4 = df4h.iloc[-1]

    prev_support = df15["low"].iloc[-30:-1].min()
    prev_swing_high = df5["high"].iloc[-24:-1].max()

    swept_low = m15.low < prev_support
    reclaimed = m15.close > prev_support
    msb = m5.close > prev_swing_high

    bb_touch = h4.low <= h4.bb_lower * 1.04 or h1.low <= h1.bb_lower * 1.04
    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close

    strong_wick = m15.lower_wick >= 0.35
    recovered = m15.recovery_ratio >= 0.55
    rsi_turn = h1_prev.rsi <= 48 and h1.rsi > h1_prev.rsi and h1.rsi <= 58
    macd_turn = h1.macd > h1_prev.macd
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]

    score = 0
    reasons = []

    if swept_low:
        score += 3; reasons.append("Likidite altı süpürüldü")
    if reclaimed:
        score += 3; reasons.append("Destek geri alındı")
    if msb:
        score += 4; reasons.append("MSB yukarı kırılım")
    if bb_touch:
        score += 2; reasons.append("Alt Bollinger yakın/temas")
    if vol_ratio >= 2.0:
        score += 2; reasons.append("15m hacim patlaması")
    if usdt_vol >= 30000:
        score += 1; reasons.append("USDT hacim yeterli")
    if strong_wick:
        score += 3; reasons.append("Aşağı iğne / güçlü alt fitil")
    if recovered:
        score += 2; reasons.append("İğneden toparladı")
    if rsi_turn:
        score += 2; reasons.append("RSI dipten dönüyor")
    if macd_turn:
        score += 1; reasons.append("MACD toparlanıyor")
    if obv_turn:
        score += 2; reasons.append("OBV para girişi")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = (
        score >= 15
        and swept_low
        and reclaimed
        and msb
        and vol_ratio >= 2.0
        and strong_wick
        and recovered
        and obv_turn
    )

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "dist_low": dist_low,
        "lower_wick": m15.lower_wick,
        "recovery": m15.recovery_ratio,
        "swept_low": swept_low,
        "reclaimed": reclaimed,
        "msb": msb,
        "reasons": reasons,
        "btc": btc_text,
        "funding_rate": funding_rate,
        "funding_text": funding_text
    }


def short_squeeze_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    if dist_low > SQUEEZE_MAX_DISTANCE_FROM_24H_LOW:
        return False, None

    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)

    if df5 is None or df15 is None or df1h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]

    recent_support = df15["low"].iloc[-35:-5].min()
    recent_breakdown = df15["low"].iloc[-5:].min() < recent_support

    reclaim_ema21 = m15.close > m15.ema21
    strong_green = m15.close > m15.open and m15.body_ratio >= 0.45

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close

    obv_boom = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]
    macd_turn = m15.macd > m15_prev.macd
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi >= 48

    msb = m5.close > df5["high"].iloc[-20:-1].max()

    score = 0
    reasons = []

    if recent_breakdown:
        score += 3; reasons.append("Önce destek altı fake kırılım")
    if reclaim_ema21:
        score += 3; reasons.append("EMA21 geri alındı")
    if strong_green:
        score += 3; reasons.append("Güçlü yeşil dönüş mumu")
    if vol_ratio >= 2.0:
        score += 2; reasons.append("15m hacim patlaması")
    if usdt_vol >= 30000:
        score += 1; reasons.append("USDT hacim yeterli")
    if obv_boom:
        score += 2; reasons.append("OBV yukarı patlama")
    if macd_turn:
        score += 2; reasons.append("MACD yukarı dönüyor")
    if rsi_turn:
        score += 2; reasons.append("RSI toparlanıyor")
    if msb:
        score += 3; reasons.append("5m MSB yukarı kırılım")
    if btc_ok:
        score += 1; reasons.append("BTC destekli")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = (
        score >= 16
        and recent_breakdown
        and reclaim_ema21
        and strong_green
        and vol_ratio >= 2.0
        and obv_boom
        and macd_turn
        and rsi_turn
        and msb
    )

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "dist_low": dist_low,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "body": m15.body_ratio,
        "recent_breakdown": recent_breakdown,
        "reclaim_ema21": reclaim_ema21,
        "msb": msb,
        "reasons": reasons,
        "btc": btc_text,
        "funding_rate": funding_rate,
        "funding_text": funding_text
    }


def dump_short(symbol, rs, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df5 is None or df15 is None or df1h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    if m15.close > m15.ema21:
        return False, None
    if m15.close > m15.open:
        return False, None
    if h1.rsi > 60:
        return False, None
    if df15["obv"].iloc[-1] > df15["obv"].iloc[-3]:
        return False, None

    support = df15["low"].iloc[-30:-1].min()
    breakdown = m15.close < support

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close

    trend_down = m15.close < m15.ema21 and m15.ema9 < m15.ema21
    ema200_below = m15.close < m15.ema200
    macd_down = m15.macd < m15.macd_signal and m15.macd < m15_prev.macd
    obv_down = df15["obv"].iloc[-1] < df15["obv"].iloc[-6]

    red_body = m15.close < m15.open and m15.body_ratio >= 0.42
    weak_retest = m5.close < m5.ema21
    rsi_ok = 20 <= h1.rsi <= 58

    score = 0
    reasons = []

    if breakdown:
        score += 4; reasons.append("Destek kırılımı")
    if vol_ratio >= 2.0:
        score += 2; reasons.append("Satış hacmi güçlü")
    if usdt_vol >= 30000:
        score += 1; reasons.append("USDT hacim yeterli")
    if trend_down:
        score += 2; reasons.append("Trend aşağı")
    if ema200_below:
        score += 1; reasons.append("EMA200 altı")
    if macd_down:
        score += 2; reasons.append("MACD aşağı")
    if obv_down:
        score += 2; reasons.append("OBV para çıkışı")
    if red_body:
        score += 2; reasons.append("Güçlü kırmızı mum")
    if weak_retest:
        score += 1; reasons.append("Tepki zayıf")
    if rsi_ok:
        score += 1; reasons.append("RSI short için uygun")
    if not btc_ok:
        score += 1; reasons.append("BTC zayıf")

    valid = score >= 17 and breakdown and vol_ratio >= 4.0 and usdt_vol >= 100000 and trend_down and macd_down and obv_down and red_body

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "body": m15.body_ratio,
        "breakdown": breakdown,
        "trend_down": trend_down,
        "macd_down": macd_down,
        "obv_down": obv_down,
        "reasons": reasons,
        "btc": btc_text,
        "funding_rate": funding_rate,
        "funding_text": funding_text
    }


def msg_early(symbol, d):
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

15m Hacim Artışı:
{d['vol_ratio_15']:.2f}x

15m USDT Hacim:
{int(d['usdt_15'])} USDT

1H RSI:
{d['rsi']:.2f}

24s Dipten Uzaklık:
%{d['dist_low']:.2f}

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Takibe al.
5m/15m kırılım gelmeden direkt long değil.
""".strip()


def msg_gold(symbol, d):
    return f"""
🏆 {BOT_NAME}

Mod: GOLD LONG
Coin: {symbol}
Yön: LONG ADAYI ✅

GOLD Skoru:
{d['score']}/18

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

1m Hacim Artışı:
{d['vol_ratio_1m']:.2f}x

1m USDT Hacim:
{int(d['usdt_1m'])} USDT

3m Değişim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

24s Dipten Uzaklık:
%{d['dist_low']:.2f}

5m Gövde:
%{d['body'] * 100:.1f}

5m Üst Fitil:
%{d['upper_wick'] * 100:.1f}

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
En kaliteli long takip. FOMO değil; 5m retest bekle.
""".strip()


def msg_sweep(symbol, d):
    return f"""
🧲 {BOT_NAME}

Mod: SWEEP + MSB LONG
Coin: {symbol}
Yön: DİPTEN DÖNÜŞ ADAYI ✅

Sweep Skoru:
{d['score']}/25

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

24s Dipten Uzaklık:
%{d['dist_low']:.2f}

15m Hacim Artışı:
{d['vol_ratio']:.2f}x

15m USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

Alt Fitil:
%{d['lower_wick'] * 100:.1f}

İğneden Toparlanma:
%{d['recovery'] * 100:.1f}

Likidite Sweep:
{'VAR ✅' if d['swept_low'] else 'YOK ❌'}

Destek Geri Alındı:
{'VAR ✅' if d['reclaimed'] else 'YOK ❌'}

MSB:
{'VAR ✅' if d['msb'] else 'YOK ❌'}

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dipten dönüş adayı. Direkt long değil; 5m/15m tutunma bekle.
""".strip()


def msg_squeeze(symbol, d):
    return f"""
🟢 {BOT_NAME}

Mod: SHORT SQUEEZE LONG
Coin: {symbol}
Yön: LONG ADAYI ✅

Squeeze Skoru:
{d['score']}/23

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

24s Dipten Uzaklık:
%{d['dist_low']:.2f}

15m Hacim Artışı:
{d['vol_ratio']:.2f}x

15m USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

15m Yeşil Mum Gövde:
%{d['body'] * 100:.1f}

Fake Kırılım:
{'VAR ✅' if d['recent_breakdown'] else 'YOK ❌'}

EMA21 Geri Alındı:
{'VAR ✅' if d['reclaim_ema21'] else 'YOK ❌'}

5m MSB:
{'VAR ✅' if d['msb'] else 'YOK ❌'}

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Short squeeze / fake dump dönüş adayı. FOMO değil; 5m retest bekle.
""".strip()


def msg_short(symbol, d):
    return f"""
🔻 {BOT_NAME}

Mod: DUMP / SAFE SHORT
Coin: {symbol}
Yön: SHORT ADAYI ✅

Short Skoru:
{d['score']}/18

RS Skoru:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

15m Hacim Artışı:
{d['vol_ratio']:.2f}x

15m USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

Destek Kırılımı:
{'VAR ✅' if d['breakdown'] else 'YOK ❌'}

Trend:
{'AŞAĞI ✅' if d['trend_down'] else 'ZAYIF ❌'}

MACD:
{'AŞAĞI ✅' if d['macd_down'] else 'ZAYIF ❌'}

OBV:
{'PARA ÇIKIŞI ✅' if d['obv_down'] else 'ZAYIF ❌'}

Kırmızı Mum Gövde:
%{d['body'] * 100:.1f}

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dump/short adayı. Kırılım sonrası retest bekle.
""".strip()


def analyze(item, btc_ok, btc_text):
    symbol = item["symbol"]
    rs = item["rs_score"]
    dist_low = item["dist_low"]

    funding_rate, funding_text, funding_ok = get_funding(symbol)

    try:
        squeeze_ok, squeeze_data = short_squeeze_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
        if squeeze_ok and can_send(symbol + "_SQUEEZE", COOLDOWN_SQUEEZE):
            send_telegram(msg_squeeze(symbol, squeeze_data))
            print("SQUEEZE:", symbol, squeeze_data["score"], flush=True)

        sweep_ok, sweep_data = sweep_msb_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
        if sweep_ok and can_send(symbol + "_SWEEP", COOLDOWN_SWEEP):
            send_telegram(msg_sweep(symbol, sweep_data))
            print("SWEEP:", symbol, sweep_data["score"], flush=True)

        gold_ok, gold_data = gold_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
        if gold_ok and can_send(symbol + "_GOLD", COOLDOWN_GOLD):
            send_telegram(msg_gold(symbol, gold_data))
            print("GOLD:", symbol, gold_data["score"], flush=True)

        early_ok, early_data = early_radar(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
        if early_ok and can_send(symbol + "_EARLY", COOLDOWN_EARLY):
            send_telegram(msg_early(symbol, early_data))
            print("EARLY:", symbol, early_data["score"], flush=True)

        short_ok, short_data = dump_short(symbol, rs, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
        if short_ok and can_send(symbol + "_SHORT", COOLDOWN_SHORT):
            send_telegram(msg_short(symbol, short_data))
            print("SHORT:", symbol, short_data["score"], flush=True)

        if not squeeze_ok and not sweep_ok and not gold_ok and not early_ok and not short_ok:
            print(symbol, "RS:", round(rs, 1), "DistLow:", round(dist_low, 2), "Funding:", funding_text, "İÇ FİLTRE", flush=True)

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)


def run_bot():
    send_telegram(f"✅ {BOT_NAME} başladı. EARLY + GOLD + SWEEP/MSB + SQUEEZE + SHORT aktif.")
    print(BOT_NAME, "başladı", flush=True)

    while True:
        try:
            print("Tarama başladı:", datetime.now(), flush=True)

            btc_ok, btc_text = btc_status()
            print("BTC:", btc_text, flush=True)

            universe = build_universe()
            print("Taranacak coin:", len(universe), flush=True)

            for item in universe:
                analyze(item, btc_ok, btc_text)
                time.sleep(0.25)

            print("Tur bitti. Bekleme:", SLEEP_SECONDS, flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"⚠️ Binance veri hatası hocam:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE FUTURES PRO BOT AKTIF", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
