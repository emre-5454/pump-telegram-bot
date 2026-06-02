from flask import Flask
import threading, time, os, requests, ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "🚀 BINANCE FUTURES PRO BOT | LONG + SWEEP + MSB + SHORT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 30

COOLDOWN_GOLD = 45 * 60
COOLDOWN_SAFE = 60 * 60
COOLDOWN_SWEEP = 60 * 60
COOLDOWN_SHORT = 60 * 60

sent_gold = {}
sent_safe = {}
sent_sweep = {}
sent_short = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "future"}
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
    df["bb_upper"] = basis + dev * 2
    df["bb_lower"] = basis - dev * 2
    df["bb_mid"] = basis
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

            if qv < 1_500_000:
                continue

            if volatility < 1.2:
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


def gold_long(symbol, rs, btc_ok, funding):
    df1m = fetch_df(symbol, "1m", 90)
    df5 = fetch_df(symbol, "5m", 120)
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
        reasons.append("BB üst bant yakın/kırılım")
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
        score >= 12
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
    df5 = fetch_df(symbol, "5m", 120)
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
        confidence >= 68
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
    if risk_pct > 4.5:
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


def sweep_msb_long(symbol, rs, btc_ok, funding):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 120)
    df4h = fetch_df(symbol, "4h", 120)

    if df5 is None or df15 is None or df1h is None or df4h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    h4 = df4h.iloc[-1]

    prev_support = df15["low"].iloc[-25:-1].min()
    prev_swing_high = df5["high"].iloc[-20:-1].max()

    swept_low = m15.low < prev_support
    reclaimed_support = m15.close > prev_support
    msb = m5.close > prev_swing_high

    bb_touch = h4.low <= h4.bb_lower * 1.03 or h1.low <= h1.bb_lower * 1.03

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close

    strong_wick = m15.lower_wick >= 0.40
    recovered = m15.recovery_ratio >= 0.55

    rsi_dip_turn = h1_prev.rsi <= 45 and h1.rsi > h1_prev.rsi and h1.rsi <= 58
    macd_turn = h1.macd > h1_prev.macd
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    not_late = m15.close <= m15.ema21 * 1.06

    score = 0
    reasons = []

    if swept_low:
        score += 3
        reasons.append("Likidite altı süpürüldü")
    if reclaimed_support:
        score += 3
        reasons.append("Destek geri alındı")
    if msb:
        score += 4
        reasons.append("MSB yukarı kırılım")
    if bb_touch:
        score += 2
        reasons.append("Alt Bollinger yakın/temas")
    if vol_ratio >= 2.0:
        score += 2
        reasons.append("15m hacim patlaması")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if strong_wick:
        score += 3
        reasons.append("Güçlü alt fitil")
    if recovered:
        score += 2
        reasons.append("İğneden toparladı")
    if rsi_dip_turn:
        score += 2
        reasons.append("RSI dipten dönüyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlanıyor")
    if obv_turn:
        score += 2
        reasons.append("OBV para girişi")
    if btc_ok:
        score += 1
        reasons.append("BTC destekli")
    if funding["ok"]:
        score += 1
        reasons.append("Funding uygun")

    valid = (
        score >= 16
        and swept_low
        and reclaimed_support
        and msb
        and vol_ratio >= 2.0
        and strong_wick
        and recovered
        and obv_turn
        and not_late
    )

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "lower_wick": m15.lower_wick,
        "recovery": m15.recovery_ratio,
        "swept_low": swept_low,
        "reclaimed_support": reclaimed_support,
        "msb": msb,
        "reasons": reasons
    }


def dump_short(symbol, rs, btc_ok, funding):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 120)

    if df5 is None or df15 is None or df1h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    support = df15["low"].iloc[-30:-1].min()
    breakdown = m15.close < support

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close

    trend_down = m15.close < m15.ema21 and m15.ema9 < m15.ema21
    ma200_below = m15.close < m15.ema200
    macd_down = m15.macd < m15.macd_signal and m15.macd < m15_prev.macd
    obv_down = df15["obv"].iloc[-1] < df15["obv"].iloc[-6]

    red_body = m15.close < m15.open and m15.body_ratio >= 0.45
    weak_retest = m5.close < m5.ema21

    rsi_ok = 20 <= h1.rsi <= 58
    btc_short_support = not btc_ok

    score = 0
    reasons = []

    if breakdown:
        score += 4
        reasons.append("Destek kırılımı")
    if vol_ratio >= 2.0:
        score += 2
        reasons.append("Satış hacmi güçlü")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if trend_down:
        score += 2
        reasons.append("Trend aşağı")
    if ma200_below:
        score += 1
        reasons.append("EMA200 altı")
    if macd_down:
        score += 2
        reasons.append("MACD aşağı")
    if obv_down:
        score += 2
        reasons.append("OBV para çıkışı")
    if red_body:
        score += 2
        reasons.append("Güçlü kırmızı mum")
    if weak_retest:
        score += 1
        reasons.append("Tepki zayıf")
    if rsi_ok:
        score += 1
        reasons.append("RSI short için uygun")
    if btc_short_support:
        score += 1
        reasons.append("BTC zayıf")
    if funding["rate"] > -0.002:
        score += 1
        reasons.append("Funding short için aşırı kalabalık değil")

    valid = (
        score >= 13
        and breakdown
        and vol_ratio >= 2.0
        and trend_down
        and macd_down
        and obv_down
        and red_body
    )

    return valid, {
        "score": score,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "rsi": h1.rsi,
        "breakdown": breakdown,
        "trend_down": trend_down,
        "macd_down": macd_down,
        "obv_down": obv_down,
        "body": m15.body_ratio,
        "reasons": reasons
    }


def format_gold(symbol, d, funding, btc_status):
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

Sebep:
{", ".join(d['reasons'])}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Karar:
Güçlü long takip. FOMO değil, retest bekle.
""".strip()


def format_safe(symbol, d, funding, btc_status):
    return f"""
🚀 {BOT_NAME}

Mod: SAFE LONG
Coin: {symbol}
Yön: LONG ✅

Güven:
{d['confidence']}/100

RS Skoru:
{d['rs']:.1f}/100

Giriş:
{d['entry']:.8f}

Stop:
{d['stop']:.8f}

TP1:
{d['tp1']:.8f}

TP2:
{d['tp2']:.8f}

TP3:
{d['tp3']:.8f}

Risk:
%{d['risk_pct']:.2f}

Hacim Artışı:
{d['vol_ratio']:.2f}x

3m Değişim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Karar:
Onaylı long bölgesi. Stop şart.
""".strip()


def format_sweep(symbol, d, funding, btc_status):
    return f"""
🧲 {BOT_NAME}

Mod: SWEEP + MSB LONG
Coin: {symbol}
Yön: DİPTEN DÖNÜŞ ADAYI ✅

Sweep Skoru:
{d['score']}/24

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

Alt Fitil:
%{d['lower_wick'] * 100:.1f}

İğneden Toparlanma:
%{d['recovery'] * 100:.1f}

Likidite Sweep:
{'VAR ✅' if d['swept_low'] else 'YOK ❌'}

Destek Geri Alındı:
{'VAR ✅' if d['reclaimed_support'] else 'YOK ❌'}

MSB:
{'VAR ✅' if d['msb'] else 'YOK ❌'}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dipten dönüş adayı. Direkt FOMO değil; 5m/15m tutunma takip.
""".strip()


def format_short(symbol, d, funding, btc_status):
    return f"""
🔻 {BOT_NAME}

Mod: DUMP / SAFE SHORT
Coin: {symbol}
Yön: SHORT ADAYI ✅

Short Skoru:
{d['score']}/19

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
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dump/short adayı. Tepki shortu değil; kırılım sonrası retest bekle.
""".strip()


def analyze(item, btc_ok, btc_status):
    symbol = item["symbol"]
    rs = item["rs_score"]
    funding = get_funding(symbol)

    try:
        gold_ok, gold_data = gold_long(symbol, rs, btc_ok, funding)
        if gold_ok and can_send(sent_gold, symbol + "_GOLD", COOLDOWN_GOLD):
            send_telegram(format_gold(symbol, gold_data, funding, btc_status))
            print("GOLD:", symbol, gold_data["score"], flush=True)

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        if safe_ok and can_send(sent_safe, symbol + "_SAFE", COOLDOWN_SAFE):
            send_telegram(format_safe(symbol, safe_data, funding, btc_status))
            print("SAFE:", symbol, safe_data["confidence"], flush=True)

        sweep_ok, sweep_data = sweep_msb_long(symbol, rs, btc_ok, funding)
        if sweep_ok and can_send(sent_sweep, symbol + "_SWEEP", COOLDOWN_SWEEP):
            send_telegram(format_sweep(symbol, sweep_data, funding, btc_status))
            print("SWEEP:", symbol, sweep_data["score"], flush=True)

        short_ok, short_data = dump_short(symbol, rs, btc_ok, funding)
        if short_ok and can_send(sent_short, symbol + "_SHORT", COOLDOWN_SHORT):
            send_telegram(format_short(symbol, short_data, funding, btc_status))
            print("SHORT:", symbol, short_data["score"], flush=True)

        if not gold_ok and not safe_ok and not sweep_ok and not short_ok:
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
    send_telegram(f"✅ {BOT_NAME} başladı. GOLD + SAFE + SWEEP/MSB + SHORT aktif.")
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
                time.sleep(0.20)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"⚠️ Binance bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE FUTURES PRO BOT Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
