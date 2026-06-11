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
 

MEXC_ELITE_CHAT_ID = os.getenv("MEXC_ELITE_CHAT_ID") or "-1003758052977"



BOT_NAME = "MEXC RADAR MANAGER + MONEY CONTINUE BOT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 120

COOLDOWN_EARLY = 3 * 60 * 60
EARLY_MAX_PER_SYMBOL_PER_DAY = 3
COOLDOWN_SAFE = 4 * 60 * 60
COOLDOWN_DIP = 4 * 60 * 60
COOLDOWN_DIP_REACTION = 3 * 60 * 60
COOLDOWN_REVERSAL_WATCH = 120 * 60
COOLDOWN_SQUEEZE_BREAKOUT = 120 * 60
COOLDOWN_WATCH_CONFIRM = 90 * 60
COOLDOWN_MONEY_CONTINUE = 120 * 60
COOLDOWN_MOMENTUM_CONTINUE = 120 * 60

WATCH_EXPIRE_SECONDS = 45 * 60
MONEY_STATE_EXPIRE_SECONDS = 120 * 60

MIN_EARLY_RS = 65
MIN_SAFE_CONFIDENCE = 62
MAX_RISK_PCT = 4.5

MEXC_ELITE_MIN_SCORE = 88
MEXC_ELITE_COOLDOWN = 180 * 60

sent_early = {}
early_daily_counter = {}
sent_safe = {}
sent_dip = {}
sent_dip_reaction = {}
sent_reversal_watch = {}
sent_squeeze_breakout = {}
sent_watch_confirm = {}
sent_money_continue = {}
sent_momentum_continue = {}
watchlist = {}
money_state = {}
sent_mexc_elite = {}

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {"defaultType": "swap", "adjustForTimeDifference": True}
})


def send_telegram(msg, chat_id=None):
    target_chat_id = chat_id or CHAT_ID
    if not TELEGRAM_TOKEN or not target_chat_id:
        print(msg, flush=True)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": target_chat_id, "text": msg},
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
    df["bb_middle"] = basis
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
    valid = score >= 10 and rs >= 50 and vol_ratio >= 1.5 and usdt_vol >= 5000 and money_impact >= 1.2 and dist_from_low <= 22 and 38 <= h1.rsi <= 78 and (volume_power >= 2.3 or bb_expanding or bb_squeeze or obv_up)
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
    if usdt_vol >= 5000: score += 10
    if money_impact >= 1.2: score += 8
    if volume_power >= 1.60: score += 8
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



def dip_reaction_radar(symbol, rs):
    """
    15m dipten para giriÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸li dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶nÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸ radarÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±.
    BIG DIP gibi 1H/4H ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶kÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸ aramaz.
    PENGU tarzÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± 15m dip reaksiyonlarÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±nÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± erken yakalamak iÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§in eklendi.
    """
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)

    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    m15_prev2 = df15.iloc[-3]
    h1 = df1h.iloc[-1]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    avg_usdt_vol = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    recent_low = df15["low"].tail(16).min()
    dist_from_low = ((m15.close - recent_low) / recent_low) * 100 if recent_low > 0 else 999

    touched_bb = (
        m15.low <= m15.bb_lower * 1.006
        or m15_prev.low <= m15_prev.bb_lower * 1.006
        or m15_prev2.low <= m15_prev2.bb_lower * 1.006
    )

    green_reaction = m15.close > m15.open and m15.close > m15_prev.close
    reclaim_ma = m15.close > m15.ema9 or m15.close > m15.ema21
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-4]
    rsi_turn = m15.rsi > m15_prev.rsi and 28 <= m15.rsi <= 62
    macd_turn = m15.macd > m15_prev.macd
    recovery = m15.recovery_ratio >= 0.55
    lower_wick_ok = m15.lower_wick >= 0.28 or m15_prev.lower_wick >= 0.35

    # ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¡oktan uÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§muÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸ coinleri DIP REACTION diye alma
    if dist_from_low > 13:
        return False, None

    # RSI ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ok ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸iÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸miÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸se artÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±k dip reaksiyonu deÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸il, geÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ kalmÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¸ momentum olur
    if m15.rsi > 64:
        return False, None

    # 1H tamamen gÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§lÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ trendde ve fiyat yukarÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±da ise dip reaksiyonu sayma
    if h1.close > h1.ema21 and h1.rsi > 58 and not touched_bb:
        return False, None

    score = 0
    reasons = []

    if touched_bb:
        score += 2; reasons.append("15m alt Bollinger tepki")
    if vol_ratio >= 1.35:
        score += 2; reasons.append("15m hacim artisi")
    if usdt_vol >= 5000:
        score += 1; reasons.append("USDT hacim yeterli")
    if money_impact >= 1.12:
        score += 2; reasons.append("Para etkisi basladi")
    if volume_power >= 1.60:
        score += 2; reasons.append("Hacim gucu reaksiyon")
    if obv_turn:
        score += 2; reasons.append("OBV dipten yukari")
    if rsi_turn:
        score += 2; reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1; reasons.append("MACD toparlaniyor")
    if green_reaction:
        score += 2; reasons.append("Yesil donus mumu")
    if recovery:
        score += 1; reasons.append("Mum toparlanma guclu")
    if lower_wick_ok:
        score += 1; reasons.append("Alt fitil tepki")
    if reclaim_ma:
        score += 1; reasons.append("EMA geri alindi")
    if rs >= 55:
        score += 1; reasons.append("RS destekli")

    valid = (
        score >= 10
        and dist_from_low <= 13
        and vol_ratio >= 1.25
        and usdt_vol >= 5000
        and money_impact >= 1.08
        and volume_power >= 1.45
        and 28 <= m15.rsi <= 64
        and (touched_bb or lower_wick_ok or recovery)
        and (obv_turn or macd_turn or green_reaction)
    )

    return valid, {
        "module": "DIP_REACTION",
        "score": score,
        "priority": 28,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "dist_from_low": dist_from_low,
        "lower_wick": m15.lower_wick,
        "recovery_ratio": m15.recovery_ratio,
        "touched_bb": touched_bb,
        "obv_up": obv_turn,
        "macd_turn": macd_turn,
        "green_reaction": green_reaction,
        "reasons": reasons
    }


def reversal_watch(symbol, rs):
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)
    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    p1 = df15.iloc[-2]
    p2 = df15.iloc[-3]
    h1 = df1h.iloc[-1]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    avg_usdt_vol = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    recent_low = df15["low"].tail(20).min()
    dist_from_low = ((m15.close - recent_low) / recent_low) * 100 if recent_low > 0 else 999

    rsi_turn = m15.rsi > p1.rsi and p1.rsi <= p2.rsi and 25 <= m15.rsi <= 58
    macd_turn = m15.macd > p1.macd and p1.macd >= p2.macd
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-4]
    green_reaction = m15.close > m15.open and m15.close >= p1.close
    reclaim_ema = m15.close > m15.ema9 or m15.close > m15.ema21
    near_lower_bb = m15.low <= m15.bb_lower * 1.020 or p1.low <= p1.bb_lower * 1.020
    lower_wick_ok = max(m15.lower_wick, p1.lower_wick) >= 0.25
    recovery_ok = max(m15.recovery_ratio, p1.recovery_ratio) >= 0.50

    if dist_from_low > 10:
        return False, None
    if m15.rsi > 60:
        return False, None
    if h1.close > h1.ema21 and h1.rsi > 62 and not near_lower_bb:
        return False, None

    score = 0
    reasons = []
    if dist_from_low <= 6: score += 2; reasons.append("15m dip bolgesine yakin")
    if rsi_turn: score += 3; reasons.append("RSI dipten donuyor")
    if macd_turn: score += 2; reasons.append("MACD dipten toparlaniyor")
    if obv_turn: score += 2; reasons.append("OBV yukari donuyor")
    if green_reaction: score += 2; reasons.append("Yesil donus mumu")
    if reclaim_ema: score += 1; reasons.append("EMA geri alma")
    if near_lower_bb: score += 2; reasons.append("15m alt Bollinger bolgesi")
    if lower_wick_ok: score += 1; reasons.append("Alt fitil tepki")
    if recovery_ok: score += 1; reasons.append("Mum toparlanma var")
    if vol_ratio >= 1.25: score += 2; reasons.append("15m hacim uyanisi")
    if money_impact >= 1.10: score += 2; reasons.append("Para etkisi basliyor")
    if volume_power >= 1.7: score += 1; reasons.append("Hacim gucu erken")
    if rs >= 45: score += 1; reasons.append("RS fena degil")

    valid = (
        score >= 9
        and dist_from_low <= 10
        and usdt_vol >= 1000
        and vol_ratio >= 1.05
        and money_impact >= 1.00
        and 25 <= m15.rsi <= 60
        and (rsi_turn or macd_turn or obv_turn)
        and (green_reaction or reclaim_ema or near_lower_bb or lower_wick_ok)
    )

    return valid, {
        "module":"REVERSAL", "score":score, "priority":24, "price":m15.close,
        "rs":rs, "vol_ratio":vol_ratio, "usdt_vol":usdt_vol,
        "money_impact":money_impact, "volume_power":volume_power,
        "rsi":m15.rsi, "dist_from_low":dist_from_low,
        "lower_wick":max(m15.lower_wick, p1.lower_wick),
        "recovery_ratio":max(m15.recovery_ratio, p1.recovery_ratio),
        "rsi_turn":rsi_turn, "macd_turn":macd_turn, "obv_up":obv_turn,
        "green_reaction":green_reaction, "near_lower_bb":near_lower_bb,
        "reasons":reasons
    }


def squeeze_breakout(symbol, rs):
    df15 = fetch_df(symbol, "15m", 160)
    df1h = fetch_df(symbol, "1h", 120)
    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    p1 = df15.iloc[-2]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    avg_usdt_vol = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    bb_now = m15.bb_width
    bb_prev = df15["bb_width"].iloc[-8]
    squeeze = bb_prev <= 0.085 or df15["bb_width"].tail(12).mean() <= 0.095
    bb_expanding = bb_now > bb_prev * 1.08

    high_range = df15["high"].tail(18).max()
    range_break = m15.close >= high_range * 0.995
    upper_break = m15.close > m15.bb_upper or p1.close > p1.bb_upper
    reclaim_ma = m15.close > m15.ema21 and m15.close > m15.bb_middle

    recent_low = df15["low"].tail(24).min()
    dist_from_low = ((m15.close - recent_low) / recent_low) * 100 if recent_low > 0 else 999

    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    macd_bull = m15.macd > m15.macd_signal and m15.macd > p1.macd
    green_body = m15.close > m15.open and m15.body_ratio >= 0.35

    if m15.rsi > 82:
        return False, None
    if dist_from_low > 18:
        return False, None

    score = 0
    reasons = []
    if squeeze: score += 3; reasons.append("15m BB sikisma")
    if bb_expanding: score += 2; reasons.append("Bollinger aciliyor")
    if range_break: score += 3; reasons.append("Yatay direnc kirilimi")
    if upper_break: score += 2; reasons.append("Ust Bollinger kirilimi")
    if reclaim_ma: score += 1; reasons.append("MA20 ustu kapanis")
    if vol_ratio >= 1.6: score += 2; reasons.append("Hacim kirilim destekli")
    if money_impact >= 1.25: score += 2; reasons.append("Para etkisi var")
    if volume_power >= 2.4: score += 2; reasons.append("Hacim gucu var")
    if obv_up: score += 2; reasons.append("OBV para girisi")
    if macd_bull: score += 2; reasons.append("MACD yukari")
    if green_body: score += 1; reasons.append("Kirilim mumu")
    if rs >= 55: score += 1; reasons.append("RS destekli")

    valid = (
        score >= 10 and squeeze and (range_break or upper_break)
        and vol_ratio >= 1.45 and money_impact >= 1.15
        and usdt_vol >= 2500 and 45 <= m15.rsi <= 82
        and (obv_up or macd_bull or green_body)
    )

    return valid, {
        "module":"SQUEEZE", "score":score, "priority":26, "price":m15.close,
        "rs":rs, "vol_ratio":vol_ratio, "usdt_vol":usdt_vol,
        "money_impact":money_impact, "volume_power":volume_power,
        "rsi":m15.rsi, "bb_width":bb_now, "bb_expanding":bb_expanding,
        "dist_from_low":dist_from_low, "range_break":range_break,
        "upper_break":upper_break, "obv_up":obv_up, "macd_turn":macd_bull,
        "reasons":reasons
    }


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
    if d.get("rsi", 0) > 82:
        return False, None

    valid = (
        cont_score >= 8
        and price_gain >= 1.2
        and money_now >= 1.65
        and power_now >= 3.0
        and d.get("usdt_vol", 0) >= 5000
        and (money_growth >= 1.20 or power_growth >= 1.25 or score_growth >= 2)
    )
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
    if d.get("rsi", 0) > 84:
        return False, None

    valid = (
        mom_score >= 8
        and price_gain >= 1.7
        and money_now >= 1.55
        and power_now >= 3.2
        and d.get("usdt_vol", 0) >= 7000
        and (money_growth >= 1.18 or power_growth >= 1.25)
    )
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
    title_map = {"SAFE":"SAFE LONG", "MOMENTUM":"MOMENTUM CONTINUE", "MONEY":"MONEY CONTINUE", "WATCH":"WATCH CONFIRM", "DIP":"BIG DIP RADAR", "DIP_REACTION":"15M DIP REACTION", "REVERSAL":"REVERSAL WATCH", "SQUEEZE":"SQUEEZE BREAKOUT", "EARLY":"EARLY RADAR"}
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
    elif module == "DIP_REACTION":
        extra = f"""
15m Dip Mesafesi: %{d.get('dist_from_low',0):.2f}
Alt Fitil: %{d.get('lower_wick',0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio',0) * 100:.1f}
15m BB Tepki: {'VAR' if d.get('touched_bb') else 'YOK'}
OBV Donus: {'VAR' if d.get('obv_up') else 'YOK'}
"""
    elif module == "REVERSAL":
        extra = f"""
15m Dip Mesafesi: %{d.get('dist_from_low',0):.2f}
Alt Fitil: %{d.get('lower_wick',0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio',0) * 100:.1f}
RSI Donus: {'VAR' if d.get('rsi_turn') else 'YOK'}
MACD Donus: {'VAR' if d.get('macd_turn') else 'YOK'}
OBV Donus: {'VAR' if d.get('obv_up') else 'YOK'}
"""
    elif module == "SQUEEZE":
        extra = f"""
BB Width: {d.get('bb_width',0):.4f}
15m Dip Mesafesi: %{d.get('dist_from_low',0):.2f}
Yatay Kirilim: {'VAR' if d.get('range_break') else 'YOK'}
Ust Bant Kirilim: {'VAR' if d.get('upper_break') else 'YOK'}
OBV Giris: {'VAR' if d.get('obv_up') else 'YOK'}
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


def early_counter_key(symbol):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{symbol}_{today}"

def can_send_early_today(symbol):
    return early_daily_counter.get(early_counter_key(symbol), 0) < EARLY_MAX_PER_SYMBOL_PER_DAY

def mark_early_sent_today(symbol):
    key = early_counter_key(symbol)
    early_daily_counter[key] = early_daily_counter.get(key, 0) + 1

def cleanup_early_daily_counter():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for k in [x for x in early_daily_counter if not x.endswith("_" + today)]:
        early_daily_counter.pop(k, None)


def mexc_elite_score_signal(d, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    score = 0

    rs = d.get("rs", 0)
    money_impact = d.get("money_impact", 0)
    volume_power = d.get("volume_power", 0)
    price_gain = d.get("price_gain_from_first", 0)
    money_growth = d.get("money_growth", 1)
    power_growth = d.get("power_growth", 1)
    rsi_value = d.get("rsi", d.get("rsi15", 0))
    usdt_vol = d.get("usdt_vol", 0)

    if rs >= 90:
        score += 18
    elif rs >= 80:
        score += 14
    elif rs >= 70:
        score += 10
    elif rs >= 60:
        score += 6

    if money_impact >= 2.8:
        score += 18
    elif money_impact >= 2.2:
        score += 14
    elif money_impact >= 1.7:
        score += 9
    elif money_impact >= 1.3:
        score += 5

    if volume_power >= 7:
        score += 18
    elif volume_power >= 5:
        score += 14
    elif volume_power >= 3.5:
        score += 9
    elif volume_power >= 2.5:
        score += 5

    if usdt_vol >= 100000:
        score += 10
    elif usdt_vol >= 50000:
        score += 7
    elif usdt_vol >= 15000:
        score += 4

    if module == "SAFE":
        score += 30
    elif module == "MOMENTUM":
        score += 24
    elif module == "SQUEEZE":
        score += 20
    elif module == "REVERSAL":
        score += 18
    elif module == "MONEY":
        score += 16
    elif module == "DIP_REACTION":
        score += 16
    elif module == "WATCH":
        score += 10
    elif module == "DIP":
        score += 8
    elif module == "EARLY":
        score += 4

    if "SAFE" in support_modules:
        score += 18
    if "MOMENTUM" in support_modules:
        score += 12
    if "SQUEEZE" in support_modules:
        score += 10
    if "MONEY" in support_modules:
        score += 8
    if "REVERSAL" in support_modules:
        score += 8
    if "DIP_REACTION" in support_modules:
        score += 7
    if "WATCH" in support_modules:
        score += 5

    if price_gain >= 3.0:
        score += 14
    elif price_gain >= 2.0:
        score += 10
    elif price_gain >= 1.2:
        score += 7
    elif price_gain >= 0.8:
        score += 4

    if money_growth >= 1.8:
        score += 10
    elif money_growth >= 1.35:
        score += 7
    elif money_growth >= 1.15:
        score += 4

    if power_growth >= 2.0:
        score += 10
    elif power_growth >= 1.5:
        score += 7
    elif power_growth >= 1.25:
        score += 4

    if rsi_value >= 86:
        score -= 18
    elif rsi_value >= 82:
        score -= 10

    if module == "EARLY" and not support_modules:
        score -= 20

    return max(0, min(100, score))


def format_mexc_elite_signal(symbol, d, elite_score, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    support_text = ", ".join(support_modules) if support_modules else "YOK"

    extra = ""
    if module in ("MONEY", "MOMENTUM"):
        extra = f"""
Ilk Fiyat: {d.get('first_price', 0):.8f}
Simdiki Fiyat: {d.get('price', 0):.8f}
Ilk Sinyalden Sonra: %{d.get('price_gain_from_first', 0):.2f}
Para Buyume: {d.get('money_growth', 1):.2f}x
Hacim Gucu Buyume: {d.get('power_growth', 1):.2f}x
Sure: {d.get('age_min', 0):.1f} dk
"""
    elif module == "SAFE":
        extra = f"""
Giris: {d.get('entry', 0):.8f}
Stop: {d.get('stop', 0):.8f}
TP1: {d.get('tp1', 0):.8f}
TP2: {d.get('tp2', 0):.8f}
TP3: {d.get('tp3', 0):.8f}
Risk: %{d.get('risk_pct', 0):.2f}
"""
    elif module in ("REVERSAL", "DIP_REACTION"):
        extra = f"""
15m Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Alt Fitil: %{d.get('lower_wick', 0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio', 0) * 100:.1f}
"""
    elif module == "SQUEEZE":
        extra = f"""
BB Width: {d.get('bb_width', 0):.4f}
Yatay Kirilim: {'VAR' if d.get('range_break') else 'YOK'}
Ust Bant Kirilim: {'VAR' if d.get('upper_break') else 'YOK'}
"""

    return f"""
MEXC ELITE TOP

Coin: {symbol}
Mod: {module}
Elite Skor: {elite_score}/100

Fiyat: {d.get('price', 0):.8f}
RS Skoru: {d.get('rs', 0):.1f}/100
Radar Skoru: {d.get('score', 0)}

Para Etkisi: {d.get('money_impact', 0):.2f}x
Hacim Gucu: {d.get('volume_power', 0):.2f}
USDT Hacim: {int(d.get('usdt_vol', 0))} USDT
RSI: {d.get('rsi', d.get('rsi15', 0)):.2f}

Ek Gecen Radarlar:
{support_text}

{extra}

Karar:
Bu coin MEXC ana radardaki sinyaller arasindan ELITE listeye ayrildi.
Direkt islem degildir. 5m/15m kapanis, retest ve BTC durumu kontrol edilir.
""".strip()


def send_mexc_elite_signal(symbol, best, support):
    if not MEXC_ELITE_CHAT_ID:
        return False

    elite_score = mexc_elite_score_signal(best, support)
    print("MEXC ELITE CHECK:", symbol, best.get("module"), "EliteScore:", elite_score, "Min:", MEXC_ELITE_MIN_SCORE, "Support:", support, flush=True)

    if elite_score < MEXC_ELITE_MIN_SCORE:
        return False

    if best.get("module") == "EARLY" and not support:
        return False

    key = symbol + "_MEXC_ELITE_" + best.get("module", "UNKNOWN")
    if not can_send(sent_mexc_elite, key, MEXC_ELITE_COOLDOWN):
        return False

    send_telegram(format_mexc_elite_signal(symbol, best, elite_score, support), MEXC_ELITE_CHAT_ID)
    print("MEXC ELITE SEND:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
    return True


def select_best_signal(signals):
    if not signals:
        return None
    return sorted(signals, key=lambda x: (x.get("priority",0), x.get("score",0)), reverse=True)[0]


def send_selected_signal(symbol, signals, funding, btc_status):
    if not signals:
        return False
    best = select_best_signal(signals)
    support = [s["module"] for s in signals if s["module"] != best["module"]]
    cooldown_map = {"SAFE":(sent_safe, COOLDOWN_SAFE), "MOMENTUM":(sent_momentum_continue, COOLDOWN_MOMENTUM_CONTINUE), "MONEY":(sent_money_continue, COOLDOWN_MONEY_CONTINUE), "WATCH":(sent_watch_confirm, COOLDOWN_WATCH_CONFIRM), "DIP":(sent_dip, COOLDOWN_DIP), "DIP_REACTION":(sent_dip_reaction, COOLDOWN_DIP_REACTION), "REVERSAL":(sent_reversal_watch, COOLDOWN_REVERSAL_WATCH), "SQUEEZE":(sent_squeeze_breakout, COOLDOWN_SQUEEZE_BREAKOUT), "EARLY":(sent_early, COOLDOWN_EARLY)}
    cache, cooldown = cooldown_map.get(best["module"], (sent_early, COOLDOWN_EARLY))
    if best["module"] == "EARLY" and not can_send_early_today(symbol):
        print("EARLY DAILY LIMIT:", symbol, "Limit:", EARLY_MAX_PER_SYMBOL_PER_DAY, flush=True)
        return False

    if can_send(cache, symbol + "_" + best["module"], cooldown):
        send_telegram(format_signal(symbol, best, funding, btc_status, support))
        if best["module"] == "EARLY":
            mark_early_sent_today(symbol)
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
        reaction_ok, reaction_data = dip_reaction_radar(symbol, rs)
        reversal_ok, reversal_data = reversal_watch(symbol, rs)
        squeeze_ok, squeeze_data = squeeze_breakout(symbol, rs)
        if early_ok: signals.append(early_data)
        if money_ok: signals.append(money_data)
        if momentum_ok: signals.append(momentum_data)
        if watch_ok: signals.append(watch_data)
        if safe_ok: signals.append(safe_data)
        if dip_ok: signals.append(dip_data)
        if reaction_ok: signals.append(reaction_data)
        if reversal_ok: signals.append(reversal_data)
        if squeeze_ok: signals.append(squeeze_data)
        if early_data:
            update_money_state(symbol, early_data, "RADAR_MANAGER")
            if is_watch_candidate(early_data):
                add_watch(symbol, early_data)
        if signals:
            send_selected_signal(symbol, signals, funding, btc_status)
        else:
            print(symbol, "RS:", round(rs,1), "Funding:", funding["status"], "Early:", early_ok, "Money:", money_ok, "Momentum:", momentum_ok, "Watch:", watch_ok, "Safe:", safe_ok, "Dip:", dip_ok, "Reaction:", reaction_ok, "Reversal:", reversal_ok, "Squeeze:", squeeze_ok, "IC FILTRE", flush=True)
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
    return "MEXC RADAR MANAGER + ELITE + DIP FIX Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
