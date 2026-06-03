import os, time, threading, requests, ccxt
import pandas as pd
import numpy as np
from flask import Flask
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "ğŸš„ MEXC PRO BOT | EARLY + GOLD + FLASH + SWEEP + SQUEEZE + SHORT"

MAX_SYMBOLS = 180
SLEEP_SECONDS = 45

EARLY_MAX_DISTANCE_FROM_24H_LOW = 12
GOLD_MAX_DISTANCE_FROM_24H_LOW = 8
SWEEP_MAX_DISTANCE_FROM_24H_LOW = 8
SQUEEZE_MAX_DISTANCE_FROM_24H_LOW = 18

COOLDOWN_EARLY = 45 * 60
COOLDOWN_GOLD = 45 * 60
COOLDOWN_FLASH = 120 * 60
COOLDOWN_SWEEP = 60 * 60
COOLDOWN_SQUEEZE = 45 * 60
COOLDOWN_SHORT = 60 * 60

sent = {}

exchange = ccxt.mexc({"enableRateLimit": True, "timeout": 30000, "options": {"defaultType": "swap"}})


def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text, flush=True)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text}, timeout=20)
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

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std()
    df["bb_mid"] = basis
    df["bb_upper"] = basis + dev * 2
    df["bb_lower"] = basis - dev * 2
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / basis.replace(0, np.nan)

    candle_range = high - low
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (high - pd.concat([df["open"], close], axis=1).max(axis=1)) / candle_range.replace(0, np.nan)
    df["lower_wick"] = (pd.concat([df["open"], close], axis=1).min(axis=1) - low) / candle_range.replace(0, np.nan)
    df["recovery_ratio"] = (close - low) / candle_range.replace(0, np.nan)
    df["obv"] = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0)).cumsum()
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
            return rate, "NORMAL âœ…", True
        if rate > 0.0015:
            return rate, "LONG KALABALIK âš ï¸", False
        return rate, "SHORT BASKI âš ï¸", True
    except Exception:
        return 0, "VERÄ° YOK", True


def btc_status():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERÄ° YOK"
    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.rsi >= 42 and last.macd >= last.macd_signal
    return ok, "BTC DESTEKLÄ° âœ…" if ok else "BTC ZAYIF âŒ"


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
            if qv < 700_000 or last <= 0 or high <= 0 or low <= 0:
                continue
            volatility = ((high - low) / last) * 100
            dist_low = ((last - low) / low) * 100
            if volatility < 1:
                continue
            rows.append({"symbol": s, "qv": qv, "pct": pct, "last": last, "high": high, "low": low, "volatility": volatility, "dist_low": dist_low})
        if not rows:
            return []
        df = pd.DataFrame(rows)
        df["pct_rank"] = df["pct"].rank(pct=True) * 100
        df["vol_rank"] = df["qv"].rank(pct=True) * 100
        df["volatility_rank"] = df["volatility"].rank(pct=True) * 100
        df["rs_score"] = df["pct_rank"] * 0.40 + df["vol_rank"] * 0.35 + df["volatility_rank"] * 0.25
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
    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    macd_turn = h1.macd > h1_prev.macd
    ema_ok = m15.close > m15.ema21
    rsi_ok = 42 <= h1.rsi <= 75
    score, reasons = 0, []
    if rs >= 62: score += 2; reasons.append("RS gÃ¼Ã§lÃ¼")
    if vol_ratio >= 1.5: score += 2; reasons.append("15m hacim erken artÄ±yor")
    if usdt_vol >= 15000: score += 1; reasons.append("USDT hacim yeterli")
    if rsi_ok: score += 2; reasons.append("RSI erken/aktif bÃ¶lge")
    if obv_up: score += 2; reasons.append("OBV para giriÅŸi")
    if macd_turn: score += 2; reasons.append("MACD toparlanÄ±yor")
    if ema_ok: score += 2; reasons.append("EMA21 Ã¼stÃ¼")
    if btc_ok: score += 1; reasons.append("BTC destekli")
    if funding_ok: score += 1; reasons.append("Funding uygun")
    valid = score >= 11 and vol_ratio >= 1.5 and usdt_vol >= 15000 and ema_ok and obv_up
    return valid, {"score": score, "price": m15.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def gold_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    if dist_low > GOLD_MAX_DISTANCE_FROM_24H_LOW:
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
    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100
    trend_up = m15.ema9 > m15.ema21
    macd_up = m15.macd > m15.macd_signal and m15.macd > m15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    body_ok = m5.body_ratio >= 0.40
    wick_ok = m5.upper_wick <= 0.45
    score, reasons = 0, []
    if rs >= 70: score += 2; reasons.append("RS gÃ¼Ã§lÃ¼")
    if vol_ratio >= 2.2: score += 2; reasons.append("1m hacim gÃ¼Ã§lÃ¼")
    if usdt_vol >= 20000: score += 1; reasons.append("USDT hacim yeterli")
    if change_3m >= 0.25: score += 2; reasons.append("3m momentum")
    if trend_up: score += 2; reasons.append("15m trend yukarÄ±")
    if macd_up: score += 2; reasons.append("MACD yukarÄ±")
    if obv_up: score += 2; reasons.append("OBV para giriÅŸi")
    if m15.close > m15.ema200: score += 1; reasons.append("EMA200 Ã¼stÃ¼")
    if body_ok: score += 1; reasons.append("5m gÃ¶vde gÃ¼Ã§lÃ¼")
    if wick_ok: score += 1; reasons.append("Ãœst fitil saÄŸlÄ±klÄ±")
    if btc_ok: score += 1; reasons.append("BTC destekli")
    if funding_ok: score += 1; reasons.append("Funding uygun")
    valid = score >= 13 and rs >= 70 and vol_ratio >= 2.2 and usdt_vol >= 20000 and change_3m >= 0.20 and trend_up and macd_up and obv_up and body_ok and wick_ok
    return valid, {"score": score, "price": m1.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "change_3m": change_3m, "rsi15": m15.rsi, "body": m5.body_ratio, "upper_wick": m5.upper_wick, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def flash_sweep_radar(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    if df5 is None or df15 is None:
        return False, None
    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    vol_ratio_5m = m5.volume / m5.vol_avg if m5.vol_avg > 0 else 0
    vol_ratio_15m = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol_5m = m5.volume * m5.close
    usdt_vol_15m = m15.volume * m15.close
    wick_5m, wick_15m = m5.lower_wick, m15.lower_wick
    recovery_5m, recovery_15m = m5.recovery_ratio, m15.recovery_ratio
    dip_price = min(m5.low, m15.low)
    current_price = m5.close
    bounce_from_dip = ((current_price - dip_price) / dip_price) * 100 if dip_price > 0 else 0
    recent_low_5m = df5["low"].iloc[-40:-1].min()
    recent_low_15m = df15["low"].iloc[-40:-1].min()
    swept_5m = m5.low <= recent_low_5m * 1.003
    swept_15m = m15.low <= recent_low_15m * 1.003
    obv_turn = df5["obv"].iloc[-1] > df5["obv"].iloc[-3]
    macd_turn = df5["macd"].iloc[-1] > df5["macd"].iloc[-2]
    score, reasons = 0, []
    if wick_5m >= 0.55 or wick_15m >= 0.55: score += 4; reasons.append("AÅŸaÄŸÄ± gÃ¼Ã§lÃ¼ iÄŸne")
    if recovery_5m >= 0.45 or recovery_15m >= 0.45: score += 3; reasons.append("Ä°ÄŸneden toparlanma var")
    if vol_ratio_5m >= 2.5 or vol_ratio_15m >= 2.0: score += 3; reasons.append("Hacim patlamasÄ±")
    if usdt_vol_5m >= 10000 or usdt_vol_15m >= 15000: score += 1; reasons.append("USDT hacim yeterli")
    if swept_5m or swept_15m: score += 3; reasons.append("YakÄ±n dip / likidite sÃ¼pÃ¼rmesi")
    if bounce_from_dip >= 2: score += 2; reasons.append("Dipten hÄ±zlÄ± tepki")
    if obv_turn: score += 1; reasons.append("OBV tepki veriyor")
    if macd_turn: score += 1; reasons.append("MACD toparlanÄ±yor")
    if funding_ok: score += 1; reasons.append("Funding uygun")
    valid = score >= 11 and (wick_5m >= 0.35 or wick_15m >= 0.35) and (recovery_5m >= 0.45 or recovery_15m >= 0.45) and (vol_ratio_5m >= 2.5 or vol_ratio_15m >= 2.0) and (usdt_vol_5m >= 10000 or usdt_vol_15m >= 15000) and bounce_from_dip >= 2
    return valid, {"score": score, "price": current_price, "rs": rs, "dist_low": dist_low, "dip_price": dip_price, "bounce_from_dip": bounce_from_dip, "vol_ratio_5m": vol_ratio_5m, "vol_ratio_15m": vol_ratio_15m, "usdt_vol_5m": usdt_vol_5m, "usdt_vol_15m": usdt_vol_15m, "wick_5m": wick_5m, "wick_15m": wick_15m, "recovery_5m": recovery_5m, "recovery_15m": recovery_15m, "swept_5m": swept_5m, "swept_15m": swept_15m, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


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
    score, reasons = 0, []
    if swept_low: score += 3; reasons.append("Likidite altÄ± sÃ¼pÃ¼rÃ¼ldÃ¼")
    if reclaimed: score += 3; reasons.append("Destek geri alÄ±ndÄ±")
    if msb: score += 4; reasons.append("MSB yukarÄ± kÄ±rÄ±lÄ±m")
    if bb_touch: score += 2; reasons.append("Alt Bollinger yakÄ±n")
    if vol_ratio >= 2: score += 2; reasons.append("15m hacim patlamasÄ±")
    if usdt_vol >= 15000: score += 1; reasons.append("USDT hacim yeterli")
    if strong_wick: score += 3; reasons.append("AÅŸaÄŸÄ± iÄŸne")
    if recovered: score += 2; reasons.append("Ä°ÄŸneden toparladÄ±")
    if rsi_turn: score += 2; reasons.append("RSI dipten dÃ¶nÃ¼yor")
    if macd_turn: score += 1; reasons.append("MACD toparlanÄ±yor")
    if obv_turn: score += 2; reasons.append("OBV para giriÅŸi")
    if funding_ok: score += 1; reasons.append("Funding uygun")
    valid = score >= 15 and swept_low and reclaimed and msb and vol_ratio >= 2 and strong_wick and recovered and obv_turn
    return valid, {"score": score, "price": m15.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "lower_wick": m15.lower_wick, "recovery": m15.recovery_ratio, "swept_low": swept_low, "reclaimed": reclaimed, "msb": msb, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


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
    score, reasons = 0, []
    if recent_breakdown: score += 3; reasons.append("Ã–nce destek altÄ± fake kÄ±rÄ±lÄ±m")
    if reclaim_ema21: score += 3; reasons.append("EMA21 geri alÄ±ndÄ±")
    if strong_green: score += 3; reasons.append("GÃ¼Ã§lÃ¼ yeÅŸil dÃ¶nÃ¼ÅŸ")
    if vol_ratio >= 2: score += 2; reasons.append("15m hacim patlamasÄ±")
    if usdt_vol >= 15000: score += 1; reasons.append("USDT hacim yeterli")
    if obv_boom: score += 2; reasons.append("OBV yukarÄ± patlama")
    if macd_turn: score += 2; reasons.append("MACD yukarÄ± dÃ¶nÃ¼yor")
    if rsi_turn: score += 2; reasons.append("RSI toparlanÄ±yor")
    if msb: score += 3; reasons.append("5m MSB yukarÄ± kÄ±rÄ±lÄ±m")
    if btc_ok: score += 1; reasons.append("BTC destekli")
    if funding_ok: score += 1; reasons.append("Funding uygun")
    valid = score >= 16 and recent_breakdown and reclaim_ema21 and strong_green and vol_ratio >= 2 and obv_boom and macd_turn and rsi_turn and msb
    return valid, {"score": score, "price": m15.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "body": m15.body_ratio, "recent_breakdown": recent_breakdown, "reclaim_ema21": reclaim_ema21, "msb": msb, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def dump_short(symbol, rs, *args):
    if len(args) == 5:
        btc_ok, btc_text, funding_rate, funding_text, funding_ok = args
    elif len(args) == 6:
        dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok = args
    else:
        return False, None
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df5 is None or df15 is None or df1h is None:
        return False, None
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]
    if m15.close > m15.ema21 or m15.close > m15.open or h1.rsi > 60 or df15["obv"].iloc[-1] > df15["obv"].iloc[-3]:
        return False, None
    support = df15["low"].iloc[-30:-1].min()
    breakdown = m15.close < support
    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    trend_down = m15.close < m15.ema21 and m15.ema9 < m15.ema21
    macd_down = m15.macd < m15.macd_signal and m15.macd < m15_prev.macd
    obv_down = df15["obv"].iloc[-1] < df15["obv"].iloc[-6]
    red_body = m15.close < m15.open and m15.body_ratio >= 0.42
    rsi_ok = 20 <= h1.rsi <= 58
    score, reasons = 0, []
    if breakdown: score += 4; reasons.append("Destek kÄ±rÄ±lÄ±mÄ±")
    if vol_ratio >= 2: score += 2; reasons.append("SatÄ±ÅŸ hacmi gÃ¼Ã§lÃ¼")
    if usdt_vol >= 15000: score += 1; reasons.append("USDT hacim yeterli")
    if trend_down: score += 2; reasons.append("Trend aÅŸaÄŸÄ±")
    if macd_down: score += 2; reasons.append("MACD aÅŸaÄŸÄ±")
    if obv_down: score += 2; reasons.append("OBV para Ã§Ä±kÄ±ÅŸÄ±")
    if red_body: score += 2; reasons.append("GÃ¼Ã§lÃ¼ kÄ±rmÄ±zÄ± mum")
    if rsi_ok: score += 1; reasons.append("RSI short iÃ§in uygun")
    if not btc_ok: score += 1; reasons.append("BTC zayÄ±f")
    valid = score >= 13 and breakdown and vol_ratio >= 2 and trend_down and macd_down and obv_down and red_body
    return valid, {"score": score, "price": m15.close, "rs": rs, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "body": m15.body_ratio, "breakdown": breakdown, "trend_down": trend_down, "macd_down": macd_down, "obv_down": obv_down, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def base_msg(title, symbol, d, decision):
    flash_extra = ""
    if "dip_price" in d:
        flash_extra = f"""
Ä°ÄŸne Dibi:
{d['dip_price']:.8f}

Dipten Tepki:
%{d['bounce_from_dip']:.2f}

5m Alt Fitil:
%{d['wick_5m'] * 100:.1f}

15m Alt Fitil:
%{d['wick_15m'] * 100:.1f}

5m Toparlanma:
%{d['recovery_5m'] * 100:.1f}

15m Toparlanma:
%{d['recovery_15m'] * 100:.1f}
"""
    return f"""
{title}

Coin: {symbol}

Skor:
{d['score']}

RS:
{d['rs']:.1f}/100

Fiyat:
{d['price']:.8f}

24s Dipten UzaklÄ±k:
%{d.get('dist_low', 0):.2f}
{flash_extra}
Hacim ArtÄ±ÅŸÄ±:
{d.get('vol_ratio', d.get('vol_ratio_5m', 0)):.2f}x

USDT Hacim:
{int(d.get('usdt_vol', d.get('usdt_vol_5m', 0)))} USDT

BTC:
{d['btc']}

Funding:
{d['funding_rate']:.6f}
{d['funding_text']}

Sebep:
{', '.join(d['reasons'])}

Karar:
{decision}
""".strip()


def analyze(item, btc_ok, btc_text):
    symbol = item["symbol"]
    rs = item["rs_score"]
    dist_low = item["dist_low"]
    funding_rate, funding_text, funding_ok = get_funding(symbol)
    try:
        checks = [
            ("FLASH", COOLDOWN_FLASH, flash_sweep_radar, "âš¡ FLASH SWEEP RADAR", "Ä°ÄŸne alarmÄ±. Direkt long deÄŸil; 5m/15m kapanÄ±ÅŸ takip et."),
            ("SQUEEZE", COOLDOWN_SQUEEZE, short_squeeze_long, "ğŸŸ¢ SHORT SQUEEZE LONG", "Short squeeze / fake dump dÃ¶nÃ¼ÅŸ adayÄ±. 5m retest bekle."),
            ("SWEEP", COOLDOWN_SWEEP, sweep_msb_long, "ğŸ§² SWEEP + MSB LONG", "Dipten dÃ¶nÃ¼ÅŸ adayÄ±. Direkt long deÄŸil; tutunma bekle."),
            ("GOLD", COOLDOWN_GOLD, gold_long, "ğŸ† GOLD LONG", "En kaliteli long takip. FOMO deÄŸil; 5m retest bekle."),
            ("EARLY", COOLDOWN_EARLY, early_radar, "ğŸ‘€ EARLY RADAR", "Takibe al. KÄ±rÄ±lÄ±m gelmeden direkt long deÄŸil."),
            ("SHORT", COOLDOWN_SHORT, dump_short, "ğŸ”» DUMP / SAFE SHORT", "Short adayÄ±. Retest bekle.")
        ]
        any_signal = False
        for tag, cooldown, func, title, decision in checks:
            ok, data = func(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
            if ok and can_send(symbol + "_" + tag, cooldown):
                send_telegram(base_msg(f"{title}\n{BOT_NAME}", symbol, data, decision))
                print(tag, symbol, data["score"], flush=True)
                any_signal = True
        if not any_signal:
            print(symbol, "RS:", round(rs, 1), "DistLow:", round(dist_low, 2), "Funding:", funding_text, "Ä°Ã‡ FÄ°LTRE", flush=True)
    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)


def run_bot():
    send_telegram(f"âœ… {BOT_NAME} baÅŸladÄ±. MEXC PRO aktif. FLASH SWEEP dahil.")
    print(BOT_NAME, "baÅŸladÄ±", flush=True)
    while True:
        try:
            print("Tarama baÅŸladÄ±:", datetime.now(), flush=True)
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
            send_telegram(f"âš ï¸ MEXC bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "MEXC PRO BOT AKTIF", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
