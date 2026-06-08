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

TELEGRAM_TOKEN = "8937020446:AAEmdROw4hfDYArdz4eJ47oGHAT_9u4HhIM"
CHAT_ID = "7553607277"

BOT_NAME = "BINANCE FUTURES EARLY + MONEY CONTINUE BOT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 30

COOLDOWN_EARLY = 45 * 60
COOLDOWN_SAFE = 60 * 60
COOLDOWN_DIP = 60 * 60
COOLDOWN_MONEY_CONTINUE = 45 * 60
MONEY_STATE_EXPIRE_SECONDS = 120 * 60

MIN_EARLY_RS = 65
MIN_SAFE_CONFIDENCE = 68
MAX_RISK_PCT = 4.5

sent_early = {}
sent_safe = {}
sent_dip = {}
sent_money_continue = {}
money_state = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {
        "defaultType": "future",
        "adjustForTimeDifference": True
    }
})


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg, flush=True)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=15
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

    candle_range = (high - low).replace(0, np.nan)
    df["body_ratio"] = (close - df["open"]).abs() / candle_range
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range

    df["obv"] = np.where(
        close > close.shift(1),
        volume,
        np.where(close < close.shift(1), -volume, 0)
    ).cumsum()

    return df.dropna().copy()


def fetch_df(symbol, timeframe, limit=120):
    for _ in range(3):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data or len(data) < 40:
                return None

            df = pd.DataFrame(
                data,
                columns=["time", "open", "high", "low", "close", "volume"]
            )
            return indicators(df)

        except Exception as e:
            print("Fetch hata:", symbol, timeframe, e, flush=True)
            time.sleep(1.2)

    return None


def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0

        if -0.001 <= rate <= 0.0015:
            return {"ok": True, "rate": rate, "status": "NORMAL"}

        if rate > 0.0015:
            return {"ok": False, "rate": rate, "status": "LONG KALABALIK"}

        return {"ok": True, "rate": rate, "status": "SHORT BASKI"}

    except Exception:
        return {"ok": True, "rate": 0, "status": "VERI YOK"}


def btc_filter():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)

    if df is None:
        return True, "BTC VERI YOK"

    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.macd > last.macd_signal and last.rsi >= 42

    return ok, "BTC DESTEKLI" if ok else "BTC ZAYIF"


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

        print("RS evren secildi:", len(result), flush=True)
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

    avg_usdt_1h = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    avg_usdt_15m = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0

    money_impact_1h = usdt_vol_1h / avg_usdt_1h if avg_usdt_1h > 0 else 0
    money_impact_15m = usdt_vol_15m / avg_usdt_15m if avg_usdt_15m > 0 else 0
    money_impact = max(money_impact_1h, money_impact_15m)

    volume_power = money_impact * max(vol_ratio_1h, vol_ratio_15m)

    obv_up_1h = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-6]
    obv_up_15m = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    macd_turn_1h = h1.macd > h1_prev.macd
    macd_turn_15m = m15.macd > m15_prev.macd

    macd_cross_near = (
        h1.macd > h1.macd_signal
        or abs(h1.macd - h1.macd_signal) < abs(h1.macd) * 0.45
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
        reasons.append("RS guclu")

    if vol_ratio_1h >= 1.5:
        score += 2
        reasons.append("1H hacim uyaniyor")

    if vol_ratio_15m >= 1.4:
        score += 2
        reasons.append("15m hacim erken artiyor")

    if usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if money_impact >= 1.4:
        score += 2
        reasons.append("Para etkisi guclu")

    if volume_power >= 2.8:
        score += 2
        reasons.append("Hacim gucu guclu")

    if 42 <= h1.rsi <= 85:
        score += 2
        reasons.append("RSI erken/aktif bolge")

    if obv_up_1h or obv_up_15m:
        score += 2
        reasons.append("OBV para girisi")

    if macd_turn_1h or macd_turn_15m:
        score += 1
        reasons.append("MACD toparlaniyor")

    if macd_cross_near:
        score += 1
        reasons.append("MACD kesisime yakin")

    if dist_from_low <= 35:
        score += 2
        reasons.append("24s dibinden cok uzak degil")

    if bb_expanding:
        score += 1
        reasons.append("Bollinger acilmaya basliyor")

    if m15.close > m15.ema21:
        score += 1
        reasons.append("15m EMA21 ustu")

    valid = (
        score >= 11
        and rs >= MIN_EARLY_RS
        and (vol_ratio_1h >= 1.3 or vol_ratio_15m >= 1.4)
        and (usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000)
        and money_impact >= 1.4
        and (
            obv_up_1h
            or obv_up_15m
            or macd_turn_1h
            or macd_turn_15m
            or bb_expanding
        )
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
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": h1.rsi,
        "dist_from_low": dist_from_low,
        "bb_expanding": bb_expanding,
        "reasons": reasons
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
    strong_breakout = breakout and m5.body_ratio >= 0.38 and m5.upper_wick <= 0.55

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100 if prev3.open > 0 else 0

    trend_up = t15.ema9 > t15.ema21
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd

    score = 0
    if rs >= 70: score += 12
    if vol_ratio >= 2.2: score += 15
    if usdt_vol >= 30000: score += 10
    if change_3m >= 0.25: score += 10
    if trend_up: score += 10
    if macd_bull: score += 10
    if 48 <= t15.rsi <= 88: score += 8
    if strong_breakout: score += 15
    if btc_ok: score += 5
    else: score -= 5
    if funding["ok"]: score += 5
    else: score -= 5

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
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 72
    macd_turn = h1.macd > h1_prev.macd

    score = 0
    reasons = []

    if bb_touch:
        score += 3
        reasons.append("4H alt Bollinger tepki")
    if vol_ratio >= 1.8:
        score += 2
        reasons.append("1H hacim artisi")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim guclu")
    if h1.lower_wick >= 0.32:
        score += 2
        reasons.append("Alt fitil")
    if obv_up:
        score += 2
        reasons.append("OBV yukari")
    if rsi_turn:
        score += 2
        reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlaniyor")
    if rs >= 65:
        score += 1
        reasons.append("RS fena degil")

    valid = score >= 9 and bb_touch and vol_ratio >= 1.8 and obv_up and rsi_turn

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


def update_money_state(symbol, d, stage):
    if not d:
        return

    now = time.time()
    old = money_state.get(symbol)

    if not old:
        money_state[symbol] = {
            "time": now,
            "last_time": now,
            "first_stage": stage,
            "last_stage": stage,
            "first_price": d["price"],
            "last_price": d["price"],
            "first_money_impact": d.get("money_impact", 0),
            "last_money_impact": d.get("money_impact", 0),
            "first_volume_power": d.get("volume_power", 0),
            "last_volume_power": d.get("volume_power", 0),
            "first_score": d.get("score", 0),
            "last_score": d.get("score", 0)
        }
        return

    old["last_time"] = now
    old["last_stage"] = stage
    old["last_price"] = d["price"]
    old["last_money_impact"] = d.get("money_impact", 0)
    old["last_volume_power"] = d.get("volume_power", 0)
    old["last_score"] = d.get("score", 0)


def cleanup_money_state():
    now = time.time()
    expired = []

    for symbol, s in money_state.items():
        if now - s["time"] > MONEY_STATE_EXPIRE_SECONDS:
            expired.append(symbol)

    for symbol in expired:
        money_state.pop(symbol, None)
        print("MONEY STATE SILINDI:", symbol, flush=True)


def money_continue_signal(symbol, d):
    if symbol not in money_state or not d:
        return False, None

    s = money_state[symbol]
    age = time.time() - s["time"]

    if age < 5 * 60:
        return False, None

    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0

    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01

    money_now = d.get("money_impact", 0)
    power_now = d.get("volume_power", 0)

    money_growth = money_now / first_money
    power_growth = power_now / first_power
    score_growth = d.get("score", 0) - s.get("first_score", 0)

    cont_score = 0
    reasons = []

    if price_gain >= 0.7:
        cont_score += 2
        reasons.append("Ilk sinyalden sonra fiyat yukari")
    if money_now >= 1.3:
        cont_score += 2
        reasons.append("Para etkisi devam ediyor")
    if power_now >= 2.2:
        cont_score += 2
        reasons.append("Hacim gucu devam ediyor")
    if money_growth >= 1.10:
        cont_score += 2
        reasons.append("Para etkisi ilk sinyale gore artti")
    if power_growth >= 1.10:
        cont_score += 2
        reasons.append("Hacim gucu ilk sinyale gore artti")
    if score_growth >= 1:
        cont_score += 1
        reasons.append("Radar skoru iyilesti")

    valid = (
        cont_score >= 7
        and price_gain >= 0.5
        and money_now >= 1.2
        and power_now >= 2.0
        and (
            money_growth >= 1.08
            or power_growth >= 1.08
            or score_growth >= 2
        )
    )

    if not valid:
        return False, None

    out = dict(d)
    out["continue_score"] = cont_score
    out["continue_reasons"] = reasons
    out["first_price"] = first_price
    out["price_gain_from_first"] = price_gain
    out["first_money_impact"] = s["first_money_impact"]
    out["money_growth"] = money_growth
    out["first_volume_power"] = s["first_volume_power"]
    out["power_growth"] = power_growth
    out["age_min"] = age / 60
    return True, out


def format_early(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: EARLY RADAR
Coin: {symbol}

Bu islem sinyali degildir.
Coin uyaniyor olabilir.

RS Skoru:
{d['rs']:.1f}/100

Radar Skoru:
{d['score']}/17

Fiyat:
{d['price']:.8f}

1H Hacim Artisi:
{d['vol_ratio_1h']:.2f}x

15m Hacim Artisi:
{d['vol_ratio_15m']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol_1h'])} USDT

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

Para Etkisi:
{d.get('money_impact', 0):.2f}x

Hacim Gucu:
{d.get('volume_power', 0):.2f}

1H RSI:
{d['rsi']:.2f}

24s Dipten Uzaklik:
%{d['dist_from_low']:.2f}

Bollinger:
{"Aciliyor" if d['bb_expanding'] else "Henuz zayif"}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Takibe al.
5m/15m kirilim gelmeden direkt long degil.
""".strip()


def format_money_continue(symbol, d, funding, btc_status):
    return f"""
BINANCE PARA DEVAM EDIYOR
{BOT_NAME}

Coin: {symbol}

Ilk para girisinden sonra para devam ediyor.

Skor:
{d['continue_score']}/11

Ilk Fiyat:
{d['first_price']:.8f}

Simdiki Fiyat:
{d['price']:.8f}

Ilk Sinyalden Sonra:
%{d['price_gain_from_first']:.2f}

Sure:
{d['age_min']:.1f} dk

RS Skoru:
{d['rs']:.1f}/100

Radar Skoru:
{d['score']}/17

1H Hacim Artisi:
{d['vol_ratio_1h']:.2f}x

15m Hacim Artisi:
{d['vol_ratio_15m']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol_1h'])} USDT

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

Para Etkisi:
{d.get('money_impact', 0):.2f}x

Ilk Para Etkisi:
{d['first_money_impact']:.2f}x

Para Buyume:
{d['money_growth']:.2f}x

Hacim Gucu:
{d.get('volume_power', 0):.2f}

Ilk Hacim Gucu:
{d['first_volume_power']:.2f}

Hacim Gucu Buyume:
{d['power_growth']:.2f}x

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['continue_reasons'])}

Karar:
Ayni coine para girmeye devam ediyor.
Bu ilk EARLY sinyalden daha onemli takip sinyalidir.
Retest ve 5m/15m kapanis bekle.
""".strip()


def format_safe(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: SAFE LONG
Coin: {symbol}
Yon: LONG

RS Skoru:
{d['rs']:.1f}/100

Guven:
{d['confidence']}/100

Giris:
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

1m Hacim:
{int(d['usdt_vol'])} USDT

Hacim Artisi:
{d['vol_ratio']:.2f}x

3m Degisim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

15m Trend:
{"YUKARI" if d['trend_up'] else "ZAYIF"}

15m MACD:
{"YUKARI" if d['macd_bull'] else "ZAYIF"}

5m Breakout:
{"GUCLU" if d['strong_breakout'] else "ZAYIF"}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Karar:
EARLY RADAR sonrasi onayli giris bolgesi.
Stop sart, FOMO yok.
""".strip()


def format_dip(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: BIG DIP RADAR
Coin: {symbol}

Bu direkt long degildir.
Dipten balina tepkisi olabilir.

RS Skoru:
{d['rs']:.1f}/100

Dip Skoru:
{d['score']}/14

Fiyat:
{d['price']:.8f}

1H Hacim Artisi:
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
5m/15m retest ve kirilim bekle.
""".strip()


def analyze(item, btc_ok, btc_status):
    symbol = item["symbol"]
    rs = item["rs_score"]
    funding = get_funding(symbol)

    try:
        early_ok, early_data = early_radar(symbol, rs)

        money_ok, money_data = money_continue_signal(symbol, early_data)
        if money_ok and can_send(sent_money_continue, symbol + "_MONEY_CONTINUE", COOLDOWN_MONEY_CONTINUE):
            send_telegram(format_money_continue(symbol, money_data, funding, btc_status))
            update_money_state(symbol, early_data, "MONEY_CONTINUE")
            print("MONEY_CONTINUE:", symbol, money_data["continue_score"], flush=True)
            return

        if early_ok and can_send(sent_early, symbol + "_EARLY", COOLDOWN_EARLY):
            send_telegram(format_early(symbol, early_data, funding, btc_status))
            update_money_state(symbol, early_data, "EARLY")
            print("EARLY:", symbol, round(rs, 1), flush=True)
            return

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        if safe_ok and can_send(sent_safe, symbol + "_SAFE", COOLDOWN_SAFE):
            send_telegram(format_safe(symbol, safe_data, funding, btc_status))
            print("SAFE:", symbol, safe_data["confidence"], flush=True)
            return

        dip_ok, dip_data = big_dip_radar(symbol, rs)
        if dip_ok and can_send(sent_dip, symbol + "_DIP", COOLDOWN_DIP):
            send_telegram(format_dip(symbol, dip_data, funding, btc_status))
            print("DIP:", symbol, round(rs, 1), flush=True)
            return

        if not early_ok and not safe_ok and not dip_ok:
            print(
                symbol,
                "RS:", round(rs, 1),
                "Funding:", funding["status"],
                "MoneyState:", "VAR" if symbol in money_state else "YOK",
                "IC FILTRE",
                flush=True
            )

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)


def run_bot():
    send_telegram(f"{BOT_NAME} BASLADI. Binance Futures EARLY RADAR aktif.")
    print(BOT_NAME, "BASLADI", flush=True)

    while True:
        try:
            print("Tarama basladi:", datetime.now(), flush=True)

            btc_ok, btc_status = btc_filter()
            print("BTC:", btc_status, flush=True)

            cleanup_money_state()

            universe = build_universe()
            print("Taranacak coin:", len(universe), "MoneyState:", len(money_state), flush=True)

            for item in universe:
                analyze(item, btc_ok, btc_status)
                time.sleep(0.20)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"Binance bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE FUTURES EARLY MONEY CONTINUE Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
