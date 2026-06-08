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

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "MEXC RADAR MANAGER + MONEY CONTINUE BOT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 120

COOLDOWN_EARLY = 3 * 60 * 60
COOLDOWN_SAFE = 4 * 60 * 60
COOLDOWN_DIP = 4 * 60 * 60
COOLDOWN_WATCH_CONFIRM = 90 * 60
COOLDOWN_MONEY_CONTINUE = 45 * 60
COOLDOWN_MOMENTUM_CONTINUE = 60 * 60

WATCH_EXPIRE_SECONDS = 45 * 60
MONEY_STATE_EXPIRE_SECONDS = 120 * 60

MIN_EARLY_RS = 60
MIN_SAFE_CONFIDENCE = 62
MAX_RISK_PCT = 4.5

sent_early = {}
sent_safe = {}
sent_dip = {}
sent_watch_confirm = {}
sent_money_continue = {}
sent_momentum_continue = {}
watchlist = {}
money_state = {}

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {"defaultType": "swap", "adjustForTimeDifference": True}
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
    df["upper_wick"] = (high - pd.concat([df["open"], close], axis=1).max(axis=1)) / candle_range
    df["lower_wick"] = (pd.concat([df["open"], close], axis=1).min(axis=1) - low) / candle_range
    df["recovery_ratio"] = (close - low) / candle_range
    df["obv"] = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0)).cumsum()
    return df.dropna().copy()


def fetch_df(symbol, timeframe, limit=120):
    for _ in range(3):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data or len(data) < 40:
                return None
            df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
            return indicators(df)
        except Exception as e:
            print("Fetch hata:", symbol, timeframe, e, flush=True)
            time.sleep(1.5)
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
    ok = last.close > last.ema21 and last.macd > last.macd_signal and last.rsi >= 43
    return ok, "BTC DESTEKLI" if ok else "BTC ZAYIF"


def build_universe():
    try:
        markets = exchange.load_markets()
        symbols = [s for s in markets if s.endswith("/USDT:USDT") and markets[s].get("active", True)]
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
            if qv < 1_000_000 or volatility < 1.5:
                continue
            rows.append({"symbol": s, "qv": qv, "pct": pct, "last": last, "high": high, "low": low, "volatility": volatility})
        if not rows:
            return []
        df = pd.DataFrame(rows)
        df["pct_rank"] = df["pct"].rank(pct=True) * 100
        df["vol_rank"] = df["qv"].rank(pct=True) * 100
        df["volatility_rank"] = df["volatility"].rank(pct=True) * 100
        df["rs_score"] = df["pct_rank"] * 0.45 + df["vol_rank"] * 0.30 + df["volatility_rank"] * 0.25
        df = df.sort_values(["rs_score", "qv"], ascending=False).head(MAX_SYMBOLS)
        result = df.to_dict("records")
        print("RS evren secildi:", len(result), flush=True)
        return result
    except Exception as e:
        print("Universe hata:", e, flush=True)
        return []


def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    low = recent["low"].min()
    high = recent["high"].max()
    if high - low <= 0:
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
    avg_usdt_vol = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio
    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-6]
    macd_turn = h1.macd > h1_prev.macd
    macd_cross_near = h1.macd > h1.macd_signal or abs(h1.macd - h1.macd_signal) < abs(h1.macd) * 0.35
    low_24h = df1h["low"].tail(24).min()
    dist_from_low = ((h1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999
    bb_now = h1.bb_width
    bb_prev = df1h["bb_width"].iloc[-6]
    bb_expanding = bb_now > bb_prev
    bb_squeeze = bb_now <= 0.10
    bb_strong_squeeze = bb_now <= 0.06
    score = 0
    reasons = []
    if rs >= MIN_EARLY_RS:
        score += 3; reasons.append("RS guclu")
    if vol_ratio >= 1.6:
        score += 2; reasons.append("1H hacim uyaniyor")
    if usdt_vol >= 25000:
        score += 1; reasons.append("USDT hacim yeterli")
    if money_impact >= 1.2:
        score += 2; reasons.append("Para etkisi guclu")
    if volume_power >= 2.3:
        score += 2; reasons.append("Hacim gucu guclu")
    if 42 <= h1.rsi <= 74:
        score += 2; reasons.append("RSI erken bolge")
    if obv_up:
        score += 2; reasons.append("OBV para girisi")
    if macd_turn:
        score += 1; reasons.append("MACD toparlaniyor")
    if macd_cross_near:
        score += 1; reasons.append("MACD kesime yakin")
    if dist_from_low <= 22:
        score += 2; reasons.append("24s dibinden cok uzak degil")
    if bb_expanding:
        score += 1; reasons.append("Bollinger aciliyor")
    if bb_squeeze:
        score += 2; reasons.append("BB sikisma")
    if bb_strong_squeeze:
        score += 1; reasons.append("Guclu BB sikisma")
    valid = score >= 8 and rs >= 50 and vol_ratio >= 1.5 and usdt_vol >= 25000 and money_impact >= 1.2 and dist_from_low <= 28 and 38 <= h1.rsi <= 78 and (volume_power >= 2.3 or bb_expanding or bb_squeeze or obv_up)
    return valid, {"module":"EARLY","score":score,"priority":10,"price":h1.close,"rs":rs,"vol_ratio":vol_ratio,"usdt_vol":usdt_vol,"money_impact":money_impact,"volume_power":volume_power,"rsi":h1.rsi,"dist_from_low":dist_from_low,"bb_width":bb_now,"bb_expanding":bb_expanding,"obv_up":obv_up,"macd_turn":macd_turn,"macd_cross_near":macd_cross_near,"bb_squeeze":bb_squeeze,"bb_strong_squeeze":bb_strong_squeeze,"reasons":reasons}


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
    avg_usdt_vol = m1.vol_avg * m1.close if m1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100 if prev3.open > 0 else 0
    trend_up = t15.ema9 > t15.ema21
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd
    score = 0
    if rs >= 65: score += 12
    if vol_ratio >= 2.0: score += 15
    if usdt_vol >= 30000: score += 10
    if money_impact >= 1.2: score += 8
    if volume_power >= 2.8: score += 8
    if change_3m >= 0.20: score += 10
    if trend_up: score += 10
    if macd_bull: score += 10
    if 46 <= t15.rsi <= 80: score += 8
    if strong_breakout: score += 15
    if btc_ok: score += 5
    else: score -= 3
    if funding["ok"]: score += 5
    else: score -= 5
    confidence = max(0, min(100, score))
    valid = confidence >= MIN_SAFE_CONFIDENCE and vol_ratio >= 2.0 and usdt_vol >= 30000 and money_impact >= 1.2 and volume_power >= 2.8 and change_3m >= 0.20 and trend_up and macd_bull and (strong_breakout or volume_power >= 3.5 or change_3m >= 0.45)
    price = m1.close
    stop = max(resistance * 0.990, price * 0.970)
    risk = price - stop
    if risk <= 0:
        return False, None
    risk_pct = (risk / price) * 100
    if risk_pct > MAX_RISK_PCT:
        return False, None
    return valid, {"module":"SAFE","score":confidence,"priority":40,"price":price,"confidence":confidence,"rs":rs,"vol_ratio":vol_ratio,"usdt_vol":usdt_vol,"money_impact":money_impact,"volume_power":volume_power,"change_3m":change_3m,"rsi":t15.rsi,"rsi15":t15.rsi,"trend_up":trend_up,"macd_bull":macd_bull,"breakout":breakout,"strong_breakout":strong_breakout,"entry":price,"stop":stop,"tp1":price+risk*1.5,"tp2":price+risk*2.0,"tp3":price+risk*3.0,"risk_pct":risk_pct,"reasons":["Trend yukari","MACD yukari","Momentum onayi"]}


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
    avg_usdt_vol = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio
    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-5]

    if h1.rsi > 45:
    return False, None

    if h1.close > h1.bb_middle and h1.rsi > 50:
    return False, None

    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 70
    macd_turn = h1.macd > h1_prev.macd
    score = 0
    reasons = []
    if bb_touch: score += 3; reasons.append("4H alt Bollinger tepki")
    if vol_ratio >= 1.5: score += 2; reasons.append("1H hacim patlamasi")
    if usdt_vol >= 100000: score += 2; reasons.append("USDT hacim guclu")
    if money_impact >= 1.2: score += 2; reasons.append("Para etkisi guclu")
    if volume_power >= 2.2: score += 2; reasons.append("Hacim gucu guclu")
    if h1.lower_wick >= 0.60: score += 2; reasons.append("Alt fitil")
    if obv_up: score += 1; reasons.append("OBV yukari")
    if rsi_turn: score += 2; reasons.append("RSI dipten donuyor")
    if macd_turn: score += 1; reasons.append("MACD toparlaniyor")
    if rs >= 50: score += 1; reasons.append("RS fena degil")
    valid = score >= 10 and (bb_touch or h1.lower_wick >= 0.30) and vol_ratio >= 1.3 and usdt_vol >= 20000 and rsi_turn and (obv_up or macd_turn or money_impact >= 1.2)
    return valid, {"module":"DIP","score":score,"priority":20,"price":h1.close,"rs":rs,"vol_ratio":vol_ratio,"usdt_vol":usdt_vol,"money_impact":money_impact,"volume_power":volume_power,"rsi":h1.rsi,"lower_wick":h1.lower_wick,"reasons":reasons}


def update_money_state(symbol, d, stage):
    if not d:
        return
    now = time.time()
    old = money_state.get(symbol)
    if not old:
        money_state[symbol] = {"time":now,"last_time":now,"first_stage":stage,"last_stage":stage,"first_price":d["price"],"last_price":d["price"],"max_price":d["price"],"first_money_impact":d.get("money_impact",0),"last_money_impact":d.get("money_impact",0),"max_money_impact":d.get("money_impact",0),"first_volume_power":d.get("volume_power",0),"last_volume_power":d.get("volume_power",0),"max_volume_power":d.get("volume_power",0),"first_score":d.get("score",0),"last_score":d.get("score",0),"max_score":d.get("score",0),"count":1}
        return
    old["last_time"] = now
    old["last_stage"] = stage
    old["last_price"] = d["price"]
    old["max_price"] = max(old["max_price"], d["price"])
    old["last_money_impact"] = d.get("money_impact",0)
    old["max_money_impact"] = max(old["max_money_impact"], d.get("money_impact",0))
    old["last_volume_power"] = d.get("volume_power",0)
    old["max_volume_power"] = max(old["max_volume_power"], d.get("volume_power",0))
    old["last_score"] = d.get("score",0)
    old["max_score"] = max(old["max_score"], d.get("score",0))
    old["count"] += 1


def cleanup_money_state():
    now = time.time()
    for symbol in [s for s,v in money_state.items() if now - v["time"] > MONEY_STATE_EXPIRE_SECONDS]:
        money_state.pop(symbol, None)
        print("MONEY STATE SILINDI:", symbol, flush=True)


def money_continue_signal(symbol, d):
    if symbol not in money_state or not d:
        return False, None
    s = money_state[symbol]
    age = time.time() - s["time"]
    if age < 5*60:
        return False, None
    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0
    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01
    money_now = d.get("money_impact",0)
    power_now = d.get("volume_power",0)
    money_growth = money_now / first_money
    power_growth = power_now / first_power
    score_growth = d.get("score",0) - s.get("first_score",0)
    cont_score = 0
    reasons = []
    if price_gain >= 0.8: cont_score += 2; reasons.append("Ilk sinyalden sonra fiyat yukari")
    if money_now >= 1.4: cont_score += 2; reasons.append("Para etkisi guclu devam")
    if power_now >= 2.8: cont_score += 2; reasons.append("Hacim gucu devam")
    if money_growth >= 1.15: cont_score += 2; reasons.append("Para etkisi ilk sinyale gore artti")
    if power_growth >= 1.15: cont_score += 2; reasons.append("Hacim gucu ilk sinyale gore artti")
    if score_growth >= 1: cont_score += 1; reasons.append("Radar skoru iyilesti")
    if d.get("obv_up", False): cont_score += 1; reasons.append("OBV para girisi destekliyor")
    if d.get("macd_turn", False) or d.get("macd_cross_near", False): cont_score += 1; reasons.append("MACD toparlaniyor")
    valid = cont_score >= 7 and price_gain >= 0.5 and money_now >= 1.2 and power_now >= 2.0 and (money_growth >= 1.10 or power_growth >= 1.10 or score_growth >= 2)
    if not valid:
        return False, None
    out = dict(d)
    out.update({"module":"MONEY","score":cont_score,"priority":30,"continue_score":cont_score,"continue_reasons":reasons,"first_price":first_price,"price_gain_from_first":price_gain,"first_money_impact":s["first_money_impact"],"money_growth":money_growth,"first_volume_power":s["first_volume_power"],"power_growth":power_growth,"age_min":age/60})
    return True, out


def momentum_continue_signal(symbol, d):
    if symbol not in money_state or not d:
        return False, None
    s = money_state[symbol]
    age = time.time() - s["time"]
    if age < 8*60:
        return False, None
    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0
    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01
    money_now = d.get("money_impact",0)
    power_now = d.get("volume_power",0)
    money_growth = money_now / first_money
    power_growth = power_now / first_power
    mom_score = 0
    reasons = []
    if price_gain >= 1.8: mom_score += 3; reasons.append("Ilk sinyalden sonra guclu fiyat hareketi")
    if money_now >= 1.6: mom_score += 2; reasons.append("Para etkisi yuksek")
    if power_now >= 3.2: mom_score += 2; reasons.append("Hacim gucu yuksek")
    if money_growth >= 1.20: mom_score += 2; reasons.append("Para etkisi buyuyor")
    if power_growth >= 1.25: mom_score += 2; reasons.append("Hacim gucu buyuyor")
    if 55 <= d.get("rsi",0) <= 78: mom_score += 1; reasons.append("RSI momentum bolgesinde")
    if d.get("obv_up",False): mom_score += 1; reasons.append("OBV destekli")
    if d.get("macd_turn",False) or d.get("macd_cross_near",False): mom_score += 1; reasons.append("MACD destekli")
    if d.get("bb_expanding",False): mom_score += 1; reasons.append("Bollinger aciliyor")
    valid = mom_score >= 8 and price_gain >= 1.5 and money_now >= 1.4 and power_now >= 2.8 and (money_growth >= 1.15 or power_growth >= 1.20)
    if not valid:
        return False, None
    out = dict(d)
    out.update({"module":"MOMENTUM","score":mom_score,"priority":35,"momentum_score":mom_score,"momentum_reasons":reasons,"first_price":first_price,"price_gain_from_first":price_gain,"first_money_impact":s["first_money_impact"],"money_growth":money_growth,"first_volume_power":s["first_volume_power"],"power_growth":power_growth,"age_min":age/60})
    return True, out


def add_watch(symbol, d):
    if not d:
        return
    now = time.time()
    old = watchlist.get(symbol)
    if old:
        old["last_seen"] = now
        old["max_score"] = max(old["max_score"], d["score"])
        old["max_price"] = max(old["max_price"], d["price"])
        old["last_price"] = d["price"]
        return
    watchlist[symbol] = {"time":now,"last_seen":now,"start_price":d["price"],"last_price":d["price"],"max_price":d["price"],"start_score":d["score"],"max_score":d["score"]}


def is_watch_candidate(d):
    if not d:
        return False
    return d["score"] >= 6 and d["rs"] >= 40 and d["usdt_vol"] >= 15000 and d["dist_from_low"] <= 32 and (d["vol_ratio"] >= 1.2 or d["money_impact"] >= 1.05 or d["volume_power"] >= 1.5 or d["bb_expanding"])


def cleanup_watchlist():
    now = time.time()
    for symbol in [s for s,v in watchlist.items() if now - v["time"] > WATCH_EXPIRE_SECONDS]:
        watchlist.pop(symbol, None)
        print("WATCH SILINDI:", symbol, "sure doldu", flush=True)


def watch_confirm(symbol, d):
    if symbol not in watchlist or not d:
        return False, None
    w = watchlist[symbol]
    age = time.time() - w["time"]
    if age > WATCH_EXPIRE_SECONDS:
        watchlist.pop(symbol, None)
        return False, None
    price_gain = ((d["price"] - w["start_price"]) / w["start_price"]) * 100 if w["start_price"] > 0 else 0
    score_gain = d["score"] - w["start_score"]
    confirm_score = 0
    reasons = []
    if price_gain >= 0.8: confirm_score += 2; reasons.append("Watch sonrasi fiyat yukari")
    if score_gain >= 2: confirm_score += 2; reasons.append("Radar skoru guclendi")
    if d["vol_ratio"] >= 1.6: confirm_score += 2; reasons.append("Hacim guclendi")
    if d["money_impact"] >= 1.2: confirm_score += 2; reasons.append("Para etkisi guclendi")
    if d["volume_power"] >= 2.3: confirm_score += 2; reasons.append("Hacim gucu guclendi")
    if d["bb_expanding"]: confirm_score += 1; reasons.append("Bollinger aciliyor")
    if 42 <= d["rsi"] <= 78: confirm_score += 1; reasons.append("RSI uygun")
    valid = confirm_score >= 6 and price_gain >= 0.5 and d["vol_ratio"] >= 1.4 and d["money_impact"] >= 1.1 and d["volume_power"] >= 1.8
    if not valid:
        return False, None
    out = dict(d)
    out.update({"module":"WATCH","score":confirm_score,"priority":25,"watch_score":confirm_score,"watch_reasons":reasons,"watch_age_min":age/60,"watch_start_price":w["start_price"],"watch_price_gain":price_gain})
    return True, out


def format_signal(symbol, d, funding, btc_status, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    title_map = {"SAFE":"SAFE LONG", "MOMENTUM":"MOMENTUM CONTINUE", "MONEY":"MONEY CONTINUE", "WATCH":"WATCH CONFIRM", "DIP":"BIG DIP RADAR", "EARLY":"EARLY RADAR"}
    title = title_map.get(module, module)
    reasons = d.get("reasons") or d.get("continue_reasons") or d.get("momentum_reasons") or d.get("watch_reasons") or []
    support_text = ", ".join(support_modules) if support_modules else "YOK"
    extra = ""
    if module == "SAFE":
        extra = f"""
Giris: {d['entry']:.8f}
Stop: {d['stop']:.8f}
TP1: {d['tp1']:.8f}
TP2: {d['tp2']:.8f}
TP3: {d['tp3']:.8f}
Risk: %{d['risk_pct']:.2f}
3m Degisim: %{d['change_3m']:.2f}
15m Trend: {'YUKARI' if d['trend_up'] else 'ZAYIF'}
15m MACD: {'YUKARI' if d['macd_bull'] else 'ZAYIF'}
"""
    elif module in ["MONEY", "MOMENTUM"]:
        extra = f"""
Ilk Fiyat: {d['first_price']:.8f}
Simdiki Fiyat: {d['price']:.8f}
Ilk Sinyalden Sonra: %{d['price_gain_from_first']:.2f}
Sure: {d['age_min']:.1f} dk
Para Buyume: {d['money_growth']:.2f}x
Hacim Gucu Buyume: {d['power_growth']:.2f}x
"""
    elif module == "WATCH":
        extra = f"""
Ilk Watch Fiyati: {d['watch_start_price']:.8f}
Watch Sonrasi: %{d['watch_price_gain']:.2f}
Watch Suresi: {d['watch_age_min']:.1f} dk
"""
    elif module == "DIP":
        extra = f"""
Alt Fitil: %{d.get('lower_wick',0) * 100:.1f}
"""
    else:
        extra = f"""
BB Width: {d.get('bb_width',0):.4f}
Bollinger: {'Aciliyor' if d.get('bb_expanding') else 'Henuz zayif'}
"""
    return f"""
{BOT_NAME}

Mod: {title}
Coin: {symbol}

RS Skoru: {d.get('rs',0):.1f}/100
Skor: {d.get('score',0)}
Fiyat: {d.get('price',0):.8f}

Hacim Artisi: {d.get('vol_ratio',0):.2f}x
USDT Hacim: {int(d.get('usdt_vol',0))} USDT
Para Etkisi: {d.get('money_impact',0):.2f}x
Hacim Gucu: {d.get('volume_power',0):.2f}
RSI: {d.get('rsi',0):.2f}
{extra}
BTC: {btc_status}
Funding: {funding['rate']:.6f}
{funding['status']}

Ek Gecen Radarlar:
{support_text}

Sebep:
{', '.join(reasons)}

Karar:
Radar Manager tum filtreleri taradi. En guclu sonuc bu mesajdir.
""".strip()


def select_best_signal(signals):
    if not signals:
        return None
    return sorted(signals, key=lambda x: (x.get("priority",0), x.get("score",0)), reverse=True)[0]


def send_selected_signal(symbol, signals, funding, btc_status):
    if not signals:
        return False
    best = select_best_signal(signals)
    support = [s["module"] for s in signals if s["module"] != best["module"]]
    cooldown_map = {"SAFE":(sent_safe, COOLDOWN_SAFE), "MOMENTUM":(sent_momentum_continue, COOLDOWN_MOMENTUM_CONTINUE), "MONEY":(sent_money_continue, COOLDOWN_MONEY_CONTINUE), "WATCH":(sent_watch_confirm, COOLDOWN_WATCH_CONFIRM), "DIP":(sent_dip, COOLDOWN_DIP), "EARLY":(sent_early, COOLDOWN_EARLY)}
    cache, cooldown = cooldown_map.get(best["module"], (sent_early, COOLDOWN_EARLY))
    if can_send(cache, symbol + "_" + best["module"], cooldown):
        send_telegram(format_signal(symbol, best, funding, btc_status, support))
        print("SEND:", symbol, best["module"], "Score:", best.get("score"), "Support:", support, flush=True)
        return True
    print("COOLDOWN:", symbol, best["module"], "Support:", support, flush=True)
    return False


def analyze(item, btc_ok, btc_status):
    symbol = item["symbol"]
    rs = item["rs_score"]
    funding = get_funding(symbol)
    try:
        signals = []
        early_ok, early_data = early_radar(symbol, rs)
        money_ok, money_data = money_continue_signal(symbol, early_data)
        momentum_ok, momentum_data = momentum_continue_signal(symbol, early_data)
        watch_ok, watch_data = watch_confirm(symbol, early_data)
        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        dip_ok, dip_data = big_dip_radar(symbol, rs)
        if early_ok: signals.append(early_data)
        if money_ok: signals.append(money_data)
        if momentum_ok: signals.append(momentum_data)
        if watch_ok: signals.append(watch_data)
        if safe_ok: signals.append(safe_data)
        if dip_ok: signals.append(dip_data)
        if early_data:
            update_money_state(symbol, early_data, "RADAR_MANAGER")
            if is_watch_candidate(early_data):
                add_watch(symbol, early_data)
        if signals:
            send_selected_signal(symbol, signals, funding, btc_status)
        else:
            print(symbol, "RS:", round(rs,1), "Funding:", funding["status"], "Early:", early_ok, "Money:", money_ok, "Momentum:", momentum_ok, "Watch:", watch_ok, "Safe:", safe_ok, "Dip:", dip_ok, "IC FILTRE", flush=True)
    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)


def run_bot():
    send_telegram(f"{BOT_NAME} BASLADI. Radar Manager aktif.")
    print(BOT_NAME, "BASLADI", flush=True)
    while True:
        try:
            print("Tarama basladi:", datetime.now(), flush=True)
            btc_ok, btc_status = btc_filter()
            print("BTC:", btc_status, flush=True)
            cleanup_watchlist()
            cleanup_money_state()
            universe = build_universe()
            print("Taranacak coin:", len(universe), "Watchlist:", len(watchlist), "MoneyState:", len(money_state), flush=True)
            for item in universe:
                analyze(item, btc_ok, btc_status)
                time.sleep(0.35)
            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)
        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"MEXC bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "MEXC RADAR MANAGER Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
