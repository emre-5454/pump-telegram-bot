# Binance Futures SAFE ENTRY DECISION BOT V4
# Binance MEXC kopyasi degil: Money Acceleration + Safe Entry + Elite AL + FOMO Block mantigi.
# Ortam degiskenleri: TELEGRAM_TOKEN, CHAT_ID, ELITE_CHAT_ID

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

ELITE_CHAT_ID = os.getenv("ELITE_CHAT_ID") or "-1003961962823"

BOT_NAME = "BINANCE SAFE ENTRY DECISION BOT V4"

MAX_SYMBOLS = 120
SLEEP_SECONDS = 120

COOLDOWN_EARLY = 180 * 60
EARLY_MAX_PER_SYMBOL_PER_DAY = 1
COOLDOWN_SAFE = 90 * 60
COOLDOWN_DIP = 120 * 60
COOLDOWN_SWEEP_WATCH = 120 * 60
COOLDOWN_MONEY_CONTINUE = 120 * 60
COOLDOWN_MOMENTUM_CONTINUE = 150 * 60
MONEY_STATE_EXPIRE_SECONDS = 120 * 60

MIN_EARLY_RS = 74
MIN_SAFE_CONFIDENCE = 72
MAX_RISK_PCT = 4.5

sent_early = {}
early_daily_counter = {}
sent_safe = {}
sent_dip = {}
sent_sweep_watch = {}
sent_money_continue = {}
sent_momentum_continue = {}
money_state = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {
        "defaultType": "future",
        "adjustForTimeDifference": True
    }
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
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range

    df["recovery_ratio"] = (close - low) / candle_range

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

            if qv < 3_000_000:
                continue

            if volatility < 1.5:
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


def recent_price_gains(df, price=None):
    """FOMO filtresi: son 15m / 30m hareketini olcer."""
    if df is None or len(df) < 3:
        return {"price_gain_15m": 0, "price_gain_30m": 0}
    now_price = price if price is not None else df["close"].iloc[-1]
    p15 = df["close"].iloc[-2]
    p30 = df["close"].iloc[-3]
    gain15 = ((now_price - p15) / p15) * 100 if p15 > 0 else 0
    gain30 = ((now_price - p30) / p30) * 100 if p30 > 0 else 0
    return {"price_gain_15m": gain15, "price_gain_30m": gain30}


def is_fomo_block(d):
    """Gec kalmis patlama mumunu AL kapisindan engeller."""
    if not d:
        return True
    price_gain_from_first = d.get("price_gain_from_first", 0)
    price_gain_15m = d.get("price_gain_15m", 0)
    price_gain_30m = d.get("price_gain_30m", 0)
    dist_from_low = d.get("dist_from_low", 0)
    rsi_value = d.get("rsi", d.get("rsi15", 0))

    if price_gain_from_first > 6.0:
        return True
    if price_gain_15m > 6.0:
        return True
    if price_gain_30m > 12.0:
        return True
    if dist_from_low > 18:
        return True
    if rsi_value >= 78:
        return True
    return False


def build_entry_levels(d):
    """SAFE/MONEY/SWEEP fark etmeden Elite AL mesajina giris-stop-TP uretir."""
    price = d.get("entry", d.get("price", 0))
    if price <= 0:
        return {"entry": 0, "stop": 0, "tp1": 0, "tp2": 0, "tp3": 0, "risk_pct": 0}

    if d.get("stop", 0) > 0:
        stop = d["stop"]
    else:
        # Binance karar botunda risk sabit ve net olsun.
        risk_pct = 0.032 if d.get("module") in ("DIP", "SWEEP") else 0.028
        stop = price * (1 - risk_pct)

    risk = max(price - stop, price * 0.01)
    return {
        "entry": price,
        "stop": stop,
        "tp1": price + risk * 1.5,
        "tp2": price + risk * 2.5,
        "tp3": price + risk * 4.0,
        "risk_pct": (risk / price) * 100
    }


def attach_market_impact(d, item):
    """
    Coinin kendi 24s hacmine gore gelen paranin etkisini olcer.
    Mutlak USDT hacim tek basina yeterli degil; 100k USDT bazi coinde dev etki,
    bazi coinde cok kucuk etki yapar.
    """
    if not d or not item:
        return d

    daily_qv = item.get("qv") or item.get("quoteVolume") or 0
    if daily_qv <= 0:
        d["daily_quote_volume"] = 0
        d["impact_usdt_volume"] = 0
        d["market_impact_pct"] = 0
        d["market_impact_score"] = 0
        return d

    module = d.get("module", "")

    # SAFE genelde 1m hacimle gelir. EARLY/MONEY_ACCEL icin 15m/1h hacim verileri olur.
    impact_usdt = (
        d.get("usdt_vol")
        or d.get("usdt_vol_15m")
        or (d.get("usdt_vol_1h", 0) * 0.25)
        or 0
    )

    market_impact_pct = (impact_usdt / daily_qv) * 100 if daily_qv > 0 else 0

    score = 0
    if market_impact_pct >= 0.35:
        score = 20
    elif market_impact_pct >= 0.20:
        score = 15
    elif market_impact_pct >= 0.10:
        score = 10
    elif market_impact_pct >= 0.05:
        score = 6
    elif market_impact_pct >= 0.02:
        score = 3

    d["daily_quote_volume"] = daily_qv
    d["impact_usdt_volume"] = impact_usdt
    d["market_impact_pct"] = market_impact_pct
    d["market_impact_score"] = score

    return d


def market_impact_ok(d):
    """
    Elite AL kapisinda coinin hacmine gore para etkisi yeterli mi kontrol eder.
    Binance daha likit oldugu icin esik MEXC'e gore biraz daha esnek tutuldu.
    """
    if not d:
        return False

    module = d.get("module", "")
    score = d.get("market_impact_score", 0)
    pct = d.get("market_impact_pct", 0)

    # SAFE / MONEY_ACCEL karar sinyali icin market etki gerekli.
    if module in ("SAFE", "MONEY_ACCEL"):
        return score >= 3 or pct >= 0.02

    # Dip / sweep sinyallerinde hacim bazen ani iÄŸneyle gelir; yine de minimum etki ariyoruz.
    if module in ("DIP", "SWEEP"):
        return score >= 3 or pct >= 0.015

    return score >= 3 or pct >= 0.02


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

    score = 0
    reasons = []

    # Dipten ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ok uzaklaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸mÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ coinleri cezalandÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±r
    if dist_from_low > 15:
        score -= 2

    # ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±k early sayÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±lmayacak kadar uzaksa EARLY puanÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸er.
    # Ama None dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶nmÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼yoruz; MoneyState / Money Continue iÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§in radar verisi lazÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±m.
    if dist_from_low > 25:
        score -= 3

    bb_now = df1h["bb_width"].iloc[-1]
    bb_prev = df1h["bb_width"].iloc[-6]
    bb_expanding = bb_now > bb_prev

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

    if volume_power >= 3.2:
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
        score >= 13
        and rs >= MIN_EARLY_RS
        and (vol_ratio_1h >= 1.3 or vol_ratio_15m >= 1.4)
        and (usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000)
        and money_impact >= 1.55
        and (
            obv_up_1h
            or obv_up_15m
            or macd_turn_1h
            or macd_turn_15m
            or bb_expanding
        )
        and 42 <= h1.rsi <= 78
        and dist_from_low <= 12
    )

    return valid, {
        "module": "EARLY",
        "score": score,
        "priority": 10,
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
    """
    BINANCE SAFE ENTRY:
    Breakout bekleyip gec kalmak yerine; para/hacim yeni guclenirken,
    FOMO olmadan AL kapisina aday uretir.
    """
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
    strong_breakout = breakout and m5.body_ratio >= 0.35 and m5.upper_wick <= 0.55

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    avg_usdt_vol = m1.vol_avg * m1.close if m1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100 if prev3.open > 0 else 0

    gains = recent_price_gains(df15, m1.close)
    price_gain_15m = gains["price_gain_15m"]
    price_gain_30m = gains["price_gain_30m"]

    low_24h = df15["low"].tail(96).min()
    dist_from_low = ((m1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    trend_up = t15.ema9 > t15.ema21
    trend_new = t15.close > t15.ema9 and t15.ema9 >= t15.ema21 * 0.998
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd
    macd_turn = t15.macd > t15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    score = 0
    reasons = []
    if rs >= 68: score += 10; reasons.append("RS destekli")
    if vol_ratio >= 1.7: score += 12; reasons.append("1m hacim gucleniyor")
    if usdt_vol >= 30000: score += 8; reasons.append("USDT hacim yeterli")
    if money_impact >= 1.35: score += 10; reasons.append("Para etkisi basladi")
    if volume_power >= 2.6: score += 12; reasons.append("Hacim gucu erken")
    if 0.10 <= change_3m <= 1.20: score += 8; reasons.append("3m kontrollu momentum")
    if trend_new: score += 8; reasons.append("15m EMA geri alindi")
    if macd_turn: score += 8; reasons.append("MACD toparlaniyor")
    if obv_up: score += 8; reasons.append("OBV para girisi")
    if 45 <= t15.rsi <= 70: score += 8; reasons.append("RSI giris bolgesi")
    if strong_breakout: score += 8; reasons.append("5m kontrollu kirilim")
    if dist_from_low <= 12: score += 8; reasons.append("Dipten cok uzak degil")
    if btc_ok: score += 4
    else: score -= 6
    if funding["ok"]: score += 4
    else: score -= 6

    confidence = max(0, min(100, score))

    fomo_block = (
        price_gain_15m > 6
        or price_gain_30m > 12
        or dist_from_low > 18
        or t15.rsi > 72
    )

    valid = (
        confidence >= 72
        and not fomo_block
        and vol_ratio >= 1.7
        and usdt_vol >= 30000
        and money_impact >= 1.35
        and volume_power >= 2.6
        and change_3m >= 0.10
        and (trend_new or trend_up)
        and (macd_turn or macd_bull or obv_up)
        and 45 <= t15.rsi <= 72
        and dist_from_low <= 18
        and (
            strong_breakout
            or volume_power >= 3.0
            or (money_impact >= 1.55 and obv_up)
            or (change_3m >= 0.25 and macd_turn)
        )
    )

    price = m1.close
    stop = max(resistance * 0.990, price * 0.972)
    risk = price - stop

    if risk <= 0:
        return False, None

    risk_pct = (risk / price) * 100
    if risk_pct > MAX_RISK_PCT:
        return False, None

    return valid, {
        "module": "SAFE",
        "score": confidence,
        "priority": 42,
        "price": price,
        "confidence": confidence,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "change_3m": change_3m,
        "price_gain_15m": price_gain_15m,
        "price_gain_30m": price_gain_30m,
        "dist_from_low": dist_from_low,
        "rsi": t15.rsi,
        "rsi15": t15.rsi,
        "trend_up": trend_up,
        "trend_new": trend_new,
        "macd_bull": macd_bull,
        "macd_turn": macd_turn,
        "obv_up": obv_up,
        "breakout": breakout,
        "strong_breakout": strong_breakout,
        "entry": price,
        "stop": stop,
        "tp1": price + risk * 1.5,
        "tp2": price + risk * 2.5,
        "tp3": price + risk * 4.0,
        "risk_pct": risk_pct,
        "reasons": reasons
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
    near_1h_lower_bb = h1.low <= h1.bb_lower * 1.015

    # Sahte dip eleme: yukari trenddeki normal fitil DIP sayilmaz
    if h1.rsi > 45 and not bb_touch:
        return False, None

    if h1.close > h1.ema21 and h1.rsi > 50:
        return False, None

    vol_ratio = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    usdt_vol = h1.volume * h1.close
    avg_usdt_vol = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-5]
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 55
    macd_turn = h1.macd > h1_prev.macd

    low_24h = df1h["low"].tail(24).min()
    dist_from_low = ((h1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    score = 0
    reasons = []

    if bb_touch:
        score += 3
        reasons.append("4H alt Bollinger tepki")
    if near_1h_lower_bb:
        score += 2
        reasons.append("1H alt Bollinger yakin")
    if vol_ratio >= 1.5:
        score += 2
        reasons.append("1H hacim artisi")
    if usdt_vol >= 50000:
        score += 2
        reasons.append("USDT hacim guclu")
    if money_impact >= 1.2:
        score += 2
        reasons.append("Para etkisi guclu")
    if volume_power >= 2.2:
        score += 2
        reasons.append("Hacim gucu guclu")
    if h1.lower_wick >= 0.50:
        score += 2
        reasons.append("Alt fitil")
    if h1.rsi <= 35:
        score += 3
        reasons.append("RSI asiri satim")
    if obv_up:
        score += 1
        reasons.append("OBV yukari")
    if rsi_turn:
        score += 2
        reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlaniyor")
    if dist_from_low <= 8:
        score += 2
        reasons.append("24s dip bolgesine yakin")

    valid = (
        score >= 10
        and vol_ratio >= 1.5
        and usdt_vol >= 75000
        and h1.lower_wick >= 0.50
        and (
            bb_touch
            or near_1h_lower_bb
            or h1.rsi <= 35
            or dist_from_low <= 8
        )
        and (
            rsi_turn
            or obv_up
            or macd_turn
            or money_impact >= 1.2
        )
    )

    return valid, {
        "module": "DIP",
        "score": score,
        "priority": 20,
        "price": h1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": h1.rsi,
        "lower_wick": h1.lower_wick,
        "dist_from_low": dist_from_low,
        "reasons": reasons
    }


def liquidity_sweep_watch(symbol, rs):
    """
    15m alt Bollinger disina igne + alt fitil + bant icine donus radari.
    Bu direkt long sinyali degildir; izleme sinyalidir.
    """
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)

    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    avg_usdt_vol = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    low_24h = df15["low"].tail(96).min()
    dist_from_low = ((m15.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    sweep_now = m15.low < m15.bb_lower and m15.close > m15.bb_lower
    sweep_prev = m15_prev.low < m15_prev.bb_lower and m15_prev.close > m15_prev.bb_lower
    sweep = sweep_now or sweep_prev

    lower_wick = max(m15.lower_wick, m15_prev.lower_wick)
    recovery = max(m15.recovery_ratio, m15_prev.recovery_ratio)

    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-4]
    rsi_turn = m15.rsi > m15_prev.rsi and 28 <= m15.rsi <= 58
    macd_turn = m15.macd > m15_prev.macd
    green_reclaim = m15.close > m15.open and m15.close > m15_prev.close

    if dist_from_low > 8:
        return False, None

    if m15.rsi > 58:
        return False, None

    if h1.close > h1.ema21 and h1.rsi > 60 and not sweep:
        return False, None

    score = 0
    reasons = []

    if sweep:
        score += 4
        reasons.append("15m alt Bollinger disi igne ve geri alis")
    if lower_wick >= 0.50:
        score += 3
        reasons.append("Guclu alt fitil")
    if recovery >= 0.55:
        score += 2
        reasons.append("Mum bant icine toparladi")
    if vol_ratio >= 1.3:
        score += 2
        reasons.append("15m hacim artisi")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if money_impact >= 1.15:
        score += 2
        reasons.append("Para etkisi basliyor")
    if volume_power >= 2.0:
        score += 2
        reasons.append("Hacim gucu destekli")
    if obv_turn:
        score += 2
        reasons.append("OBV yukari dondu")
    if rsi_turn:
        score += 2
        reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlaniyor")
    if green_reclaim:
        score += 2
        reasons.append("Yesil geri alis mumu")
    if rs >= 65:
        score += 1
        reasons.append("RS destekli")

    valid = (
        score >= 10
        and sweep
        and lower_wick >= 0.45
        and recovery >= 0.60
        and vol_ratio >= 1.45
        and usdt_vol >= 40000
        and money_impact >= 1.20
        and 28 <= m15.rsi <= 58
        and dist_from_low <= 8
        and (
            obv_turn
            or rsi_turn
            or macd_turn
            or green_reclaim
        )
    )

    return valid, {
        "module": "SWEEP",
        "score": score,
        "priority": 27,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "dist_from_low": dist_from_low,
        "lower_wick": lower_wick,
        "recovery_ratio": recovery,
        "sweep": sweep,
        "obv_up": obv_turn,
        "macd_turn": macd_turn,
        "rsi_turn": rsi_turn,
        "green_reclaim": green_reclaim,
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
    """
    MONEY ACCELERATION:
    Ilk radar datasindan sonra para/hacim buyuyor ama fiyat henuz kacmamis ise calisir.
    BTW tipi 0.080 gec FOMO sinyalini degil, 0.072-0.075 erken onayi hedefler.
    """
    if symbol not in money_state or not d:
        return False, None

    s = money_state[symbol]
    age = time.time() - s["time"]

    if age < 4 * 60:
        return False, None

    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0

    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01

    money_now = d.get("money_impact", 0)
    power_now = d.get("volume_power", 0)
    rsi_now = d.get("rsi", 0)

    if rsi_now > 72:
        return False, None

    money_growth = money_now / first_money
    power_growth = power_now / first_power
    score_growth = d.get("score", 0) - s.get("first_score", 0)

    cont_score = 0
    reasons = []

    if 0.6 <= price_gain <= 5.0:
        cont_score += 2; reasons.append("Ilk sinyalden sonra kontrollu yukselis")
    if money_now >= 1.45:
        cont_score += 2; reasons.append("Para etkisi gucleniyor")
    if power_now >= 2.8:
        cont_score += 2; reasons.append("Hacim gucu gucleniyor")
    if money_growth >= 1.12:
        cont_score += 2; reasons.append("Para etkisi ilk sinyale gore buyudu")
    if power_growth >= 1.15:
        cont_score += 2; reasons.append("Hacim gucu ilk sinyale gore buyudu")
    if score_growth >= 1:
        cont_score += 1; reasons.append("Radar skoru iyilesti")
    if d.get("bb_expanding", False):
        cont_score += 1; reasons.append("Bollinger aciliyor")

    valid = (
        cont_score >= 7
        and 0.6 <= price_gain <= 5.0
        and money_now >= 1.45
        and power_now >= 2.8
        and rsi_now <= 72
        and (
            money_growth >= 1.10
            or power_growth >= 1.12
            or score_growth >= 2
        )
    )

    if not valid:
        return False, None

    out = dict(d)
    out["module"] = "MONEY_ACCEL"
    out["score"] = cont_score
    out["priority"] = 34
    out["continue_score"] = cont_score
    out["continue_reasons"] = reasons
    out["first_price"] = first_price
    out["price_gain_from_first"] = price_gain
    out["first_money_impact"] = s["first_money_impact"]
    out["money_growth"] = money_growth
    out["first_volume_power"] = s["first_volume_power"]
    out["power_growth"] = power_growth
    out["age_min"] = age / 60
    levels = build_entry_levels(out)
    out.update(levels)
    return True, out

def momentum_continue_signal(symbol, d):
    if symbol not in money_state or not d:
        return False, None

    s = money_state[symbol]
    age = time.time() - s["time"]

    if age < 8 * 60:
        return False, None

    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0

    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01

    money_now = d.get("money_impact", 0)
    power_now = d.get("volume_power", 0)

    if d.get("rsi", 0) > 80:
        return False, None

    money_growth = money_now / first_money
    power_growth = power_now / first_power

    mom_score = 0
    reasons = []

    if price_gain >= 1.7:
        mom_score += 3
        reasons.append("Ilk sinyalden sonra fiyat guclendi")
    if money_now >= 1.5:
        mom_score += 2
        reasons.append("Para etkisi yuksek")
    if power_now >= 3.0:
        mom_score += 2
        reasons.append("Hacim gucu yuksek")
    if money_growth >= 1.15:
        mom_score += 2
        reasons.append("Para etkisi buyuyor")
    if power_growth >= 1.20:
        mom_score += 2
        reasons.append("Hacim gucu buyuyor")
    if 52 <= d.get("rsi", 0) <= 82:
        mom_score += 1
        reasons.append("RSI momentum bolgesinde")
    if d.get("bb_expanding", False):
        mom_score += 1
        reasons.append("Bollinger aciliyor")

    valid = (
        mom_score >= 8
        and price_gain >= 1.5
        and money_now >= 1.55
        and power_now >= 3.2
        and (
            money_growth >= 1.12
            or power_growth >= 1.18
        )
    )

    if not valid:
        return False, None

    out = dict(d)
    out["module"] = "MOMENTUM"
    out["score"] = mom_score
    out["priority"] = 35
    out["momentum_score"] = mom_score
    out["momentum_reasons"] = reasons
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
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
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
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
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
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
""".strip()


def format_signal(symbol, d, funding, btc_status, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")

    if module == "SAFE":
        title = "SAFE LONG"
        body = f"""
Guven: {d['confidence']}/100
Giris: {d['entry']:.8f}
Stop: {d['stop']:.8f}
TP1: {d['tp1']:.8f}
TP2: {d['tp2']:.8f}
TP3: {d['tp3']:.8f}
Risk: %{d['risk_pct']:.2f}

3m Degisim: %{d['change_3m']:.2f}
15m RSI: {d['rsi15']:.2f}
15m Trend: {"YUKARI" if d['trend_up'] else "ZAYIF"}
15m MACD: {"YUKARI" if d['macd_bull'] else "ZAYIF"}
5m Breakout: {"GUCLU" if d['strong_breakout'] else "ZAYIF"}
"""
        decision = "Onayli long adayi. Stop sart, FOMO yok."

    elif module == "MOMENTUM":
        title = "MOMENTUM CONTINUE"
        body = f"""
Ilk Fiyat: {d['first_price']:.8f}
Simdiki Fiyat: {d['price']:.8f}
Ilk Sinyalden Sonra: %{d['price_gain_from_first']:.2f}
Sure: {d['age_min']:.1f} dk
Para Buyume: {d['money_growth']:.2f}x
Hacim Gucu Buyume: {d['power_growth']:.2f}x
"""
        decision = "Para devam etti ve momentum guclendi. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    elif module in ("MONEY", "MONEY_ACCEL"):
        title = "MONEY ACCELERATION" if module == "MONEY_ACCEL" else "MONEY CONTINUE"
        body = f"""
Ilk Fiyat: {d['first_price']:.8f}
Simdiki Fiyat: {d['price']:.8f}
Ilk Sinyalden Sonra: %{d['price_gain_from_first']:.2f}
Sure: {d['age_min']:.1f} dk
Ilk Para Etkisi: {d['first_money_impact']:.2f}x
Para Buyume: {d['money_growth']:.2f}x
Ilk Hacim Gucu: {d['first_volume_power']:.2f}
Hacim Gucu Buyume: {d['power_growth']:.2f}x
"""
        decision = "Ayni coine para girmeye devam ediyor."

    elif module == "DIP":
        title = "BIG DIP RADAR"
        body = f"""
Dip Skoru: {d['score']}/18
Alt Fitil: %{d['lower_wick'] * 100:.1f}
24s Dipten Uzaklik: %{d.get('dist_from_low', 0):.2f}
"""
        decision = "Dip radar. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    elif module == "SWEEP":
        title = "LIQUIDITY SWEEP WATCH"
        body = f"""
Sweep Skoru: {d['score']}/21
15m Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Alt Fitil: %{d.get('lower_wick', 0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio', 0) * 100:.1f}
OBV Donus: {"VAR" if d.get("obv_up") else "YOK"}
MACD Toparlanma: {"VAR" if d.get("macd_turn") else "YOK"}
"""
        decision = "15m alt Bollinger igne + bant icine donus. Direkt long degil; 5m/15m retest takip."

    else:
        title = "EARLY RADAR"
        body = f"""
Radar Skoru: {d['score']}/18
1H Hacim Artisi: {d['vol_ratio_1h']:.2f}x
15m Hacim Artisi: {d['vol_ratio_15m']:.2f}x
1H USDT Hacim: {int(d['usdt_vol_1h'])} USDT
15m USDT Hacim: {int(d['usdt_vol_15m'])} USDT
24s Dipten Uzaklik: %{d['dist_from_low']:.2f}
Bollinger: {"Aciliyor" if d['bb_expanding'] else "Henuz zayif"}
"""
        decision = "Takibe al. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    reasons = d.get("reasons") or d.get("continue_reasons") or d.get("momentum_reasons") or []
    support_text = ", ".join(support_modules) if support_modules else "YOK"

    return f"""
{BOT_NAME}

Mod: {title}
Coin: {symbol}

RS Skoru: {d.get('rs', 0):.1f}/100
Skor: {d.get('score', 0)}
Fiyat: {d.get('price', 0):.8f}

Hacim Artisi: {d.get('vol_ratio', d.get('vol_ratio_1h', 0)):.2f}x
USDT Hacim: {int(d.get('usdt_vol', d.get('usdt_vol_1h', 0)))} USDT
Para Etkisi: {d.get('money_impact', 0):.2f}x
Hacim Gucu: {d.get('volume_power', 0):.2f}
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20
RSI: {d.get('rsi', d.get('rsi15', 0)):.2f}

{body}

BTC: {btc_status}
Funding: {funding['rate']:.6f}
{funding['status']}

Ek Gecen Radarlar:
{support_text}

Sebep:
{", ".join(reasons)}

Karar:
Radar Manager tum filtreleri taradi. En guclu sonuc bu mesajdir.
{decision}
""".strip()



def early_counter_key(symbol):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{symbol}_{today}"


def can_send_early_today(symbol):
    key = early_counter_key(symbol)
    return early_daily_counter.get(key, 0) < EARLY_MAX_PER_SYMBOL_PER_DAY


def mark_early_sent_today(symbol):
    key = early_counter_key(symbol)
    early_daily_counter[key] = early_daily_counter.get(key, 0) + 1


def cleanup_early_daily_counter():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    old_keys = [k for k in early_daily_counter if not k.endswith("_" + today)]
    for k in old_keys:
        early_daily_counter.pop(k, None)


def select_best_signal(signals):
    if not signals:
        return None

    return sorted(
        signals,
        key=lambda x: (x.get("priority", 0), x.get("score", 0)),
        reverse=True
    )[0]



sent_elite = {}

ELITE_MIN_SCORE = 88
ELITE_COOLDOWN = 120 * 60


def radar_combo_score(best, support_modules=None):
    support_modules = support_modules or []
    modules = [best.get("module", "UNKNOWN")] + support_modules
    weights = {
        "SAFE": 3,
        "MONEY_ACCEL": 3,
        "MONEY": 2,
        "SWEEP": 3,
        "DIP": 2,
        "EARLY": 1,
        "MOMENTUM": 0,
    }
    return sum(weights.get(m, 0) for m in modules), len(set(modules))


def elite_score_signal(d, support_modules=None):
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
    combo_score, radar_count = radar_combo_score(d, support_modules)
    market_impact_score = d.get("market_impact_score", 0)
    market_impact_pct = d.get("market_impact_pct", 0)

    if market_impact_score >= 15:
        score += 14
    elif market_impact_score >= 10:
        score += 10
    elif market_impact_score >= 6:
        score += 6
    elif market_impact_score >= 3:
        score += 3

    if rs >= 85: score += 12
    elif rs >= 75: score += 8
    elif rs >= 65: score += 5

    if money_impact >= 2.2: score += 16
    elif money_impact >= 1.8: score += 12
    elif money_impact >= 1.45: score += 8

    if volume_power >= 5: score += 16
    elif volume_power >= 3.5: score += 12
    elif volume_power >= 2.8: score += 8

    if module == "SAFE": score += 28
    elif module == "MONEY_ACCEL": score += 26
    elif module == "SWEEP": score += 22
    elif module == "DIP": score += 14
    elif module == "MONEY": score += 8
    elif module == "MOMENTUM": score -= 10
    elif module == "EARLY": score += 5

    if "SAFE" in support_modules: score += 18
    if "MONEY_ACCEL" in support_modules or "MONEY" in support_modules: score += 12
    if "EARLY" in support_modules: score += 6
    if "SWEEP" in support_modules: score += 12
    if "DIP" in support_modules: score += 8
    if "MOMENTUM" in support_modules: score -= 4

    if combo_score >= 5: score += 12
    elif combo_score >= 4: score += 8

    if 0.6 <= price_gain <= 4.5: score += 10
    elif price_gain > 6: score -= 18

    if money_growth >= 1.35: score += 8
    elif money_growth >= 1.15: score += 5

    if power_growth >= 1.5: score += 8
    elif power_growth >= 1.2: score += 5

    if 45 <= rsi_value <= 68: score += 8
    elif rsi_value >= 76: score -= 18
    elif rsi_value >= 72: score -= 8

    if is_fomo_block(d):
        score -= 30

    return max(0, min(100, score))


def is_elite_al_candidate(best, support_modules=None):
    support_modules = support_modules or []
    module = best.get("module", "UNKNOWN")
    combo_score, radar_count = radar_combo_score(best, support_modules)

    if is_fomo_block(best):
        return False, "FOMO_BLOCK"

    if module == "MOMENTUM":
        return False, "MOMENTUM_AL_DEGIL"

    if best.get("money_impact", 0) < 1.45 or best.get("volume_power", 0) < 2.8:
        return False, "PARA_ZAYIF"

    if not market_impact_ok(best):
        return False, "MARKET_ETKI_ZAYIF"

    rsi_value = best.get("rsi", best.get("rsi15", 0))
    if rsi_value > 72:
        return False, "RSI_YUKSEK"

    # Binance karar botu: en az guclu bir ana radar veya 2 destek ister.
    if module in ("SAFE", "MONEY_ACCEL") and combo_score >= 3:
        return True, "SAFE_MONEY_ONAY"

    if module == "SWEEP" and combo_score >= 4 and best.get("lower_wick", 0) >= 0.45:
        return True, "SWEEP_ONAY"

    if module == "DIP" and combo_score >= 4 and best.get("lower_wick", 0) >= 0.50:
        return True, "DIP_ONAY"

    return False, "RADAR_KOMBINASYON_YETERSIZ"


def format_elite_signal(symbol, d, elite_score, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    support_text = ", ".join(support_modules) if support_modules else "YOK"
    combo_score, radar_count = radar_combo_score(d, support_modules)
    levels = build_entry_levels(d)

    extra = ""
    if module in ("MONEY_ACCEL", "MONEY", "MOMENTUM"):
        extra = f"""
Ilk Fiyat: {d.get('first_price', 0):.8f}
Simdiki Fiyat: {d.get('price', 0):.8f}
Ilk Sinyalden Sonra: %{d.get('price_gain_from_first', 0):.2f}
Para Buyume: {d.get('money_growth', 1):.2f}x
Hacim Gucu Buyume: {d.get('power_growth', 1):.2f}x
Sure: {d.get('age_min', 0):.1f} dk
"""
    elif module == "SWEEP":
        extra = f"""
15m Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Alt Fitil: %{d.get('lower_wick', 0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio', 0) * 100:.1f}
"""

    return f"""
BINANCE ELITE AL ONAY

Coin: {symbol}
Mod: {module}
Karar: AL
Elite Giris Skoru: {elite_score}/100

Giris: {levels['entry']:.8f}
Stop: {levels['stop']:.8f}
TP1: {levels['tp1']:.8f}
TP2: {levels['tp2']:.8f}
TP3: {levels['tp3']:.8f}
Risk: %{levels['risk_pct']:.2f}

Fiyat: {d.get('price', 0):.8f}
RS Skoru: {d.get('rs', 0):.1f}/100
Radar Skoru: {d.get('score', 0)}
Radar Sayisi: {radar_count}
Radar Kombinasyon Puani: {combo_score}

24s Hacim: {int(d.get('daily_quote_volume', 0))} USDT
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20

Para Etkisi: {d.get('money_impact', 0):.2f}x
Hacim Gucu: {d.get('volume_power', 0):.2f}
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20
RSI: {d.get('rsi', d.get('rsi15', 0)):.2f}
FOMO 15m: %{d.get('price_gain_15m', 0):.2f}
FOMO 30m: %{d.get('price_gain_30m', 0):.2f}

Ek Gecen Radarlar:
{support_text}

{extra}

Not:
Bu mesaj Binance karar botunda AL kapisindan gecen sinyal icin atilir.
Momentum tek basina AL degildir. FOMO / gec giris / yuksek RSI elendi.
""".strip()


def send_elite_signal(symbol, best, support):
    if not ELITE_CHAT_ID:
        return False

    ok, reason = is_elite_al_candidate(best, support)
    if not ok:
        print("ELITE BLOCK:", symbol, best.get("module"), reason, flush=True)
        return False

    elite_score = elite_score_signal(best, support)
    if elite_score < ELITE_MIN_SCORE:
        return False

    key = symbol + "_ELITE_AL_" + best.get("module", "UNKNOWN")
    if not can_send(sent_elite, key, ELITE_COOLDOWN):
        return False

    send_telegram(format_elite_signal(symbol, best, elite_score, support), ELITE_CHAT_ID)
    print("ELITE AL SEND:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
    return True
def send_selected_signal(symbol, signals, funding, btc_status):
    if not signals:
        return False

    best = select_best_signal(signals)
    support = [s["module"] for s in signals if s["module"] != best["module"]]

    cooldown_map = {
        "SAFE": (sent_safe, COOLDOWN_SAFE),
        "MOMENTUM": (sent_momentum_continue, COOLDOWN_MOMENTUM_CONTINUE),
        "MONEY": (sent_money_continue, COOLDOWN_MONEY_CONTINUE),
        "MONEY_ACCEL": (sent_money_continue, COOLDOWN_MONEY_CONTINUE),
        "DIP": (sent_dip, COOLDOWN_DIP),
        "SWEEP": (sent_sweep_watch, COOLDOWN_SWEEP_WATCH),
        "EARLY": (sent_early, COOLDOWN_EARLY),
    }

    cache, cooldown = cooldown_map.get(best["module"], (sent_early, COOLDOWN_EARLY))
    key = symbol + "_" + best["module"]

    if best["module"] == "EARLY" and not can_send_early_today(symbol):
        print("EARLY DAILY LIMIT:", symbol, "Limit:", EARLY_MAX_PER_SYMBOL_PER_DAY, flush=True)
        return False

    if can_send(cache, key, cooldown):
        send_telegram(format_signal(symbol, best, funding, btc_status, support))

        if best["module"] == "EARLY":
            mark_early_sent_today(symbol)

        send_elite_signal(symbol, best, support)
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
        if early_data:
            early_data = attach_market_impact(early_data, item)

        # EARLY mesajÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± gelmese bile radar datasÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± oluÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸tuysa MoneyState baÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸lasÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±n.
        if early_data:
            update_money_state(symbol, early_data, "RADAR_DATA")

        money_ok, money_data = money_continue_signal(symbol, early_data)
        if money_data:
            money_data = attach_market_impact(money_data, item)

        momentum_ok, momentum_data = momentum_continue_signal(symbol, early_data)
        if momentum_data:
            momentum_data = attach_market_impact(momentum_data, item)

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        if safe_data:
            safe_data = attach_market_impact(safe_data, item)

        dip_ok, dip_data = big_dip_radar(symbol, rs)
        if dip_data:
            dip_data = attach_market_impact(dip_data, item)

        sweep_ok, sweep_data = liquidity_sweep_watch(symbol, rs)
        if sweep_data:
            sweep_data = attach_market_impact(sweep_data, item)

        if early_ok:
            signals.append(early_data)

        if money_ok:
            signals.append(money_data)

        if momentum_ok:
            signals.append(momentum_data)

        if safe_ok:
            signals.append(safe_data)

        if dip_ok:
            signals.append(dip_data)

        if sweep_ok:
            signals.append(sweep_data)

        if signals:
            sent = send_selected_signal(symbol, signals, funding, btc_status)
            if sent:
                return

        else:
            print(
                symbol,
                "RS:", round(rs, 1),
                "Funding:", funding["status"],
                "Early:", early_ok,
                "Money:", money_ok,
                "Momentum:", momentum_ok,
                "Safe:", safe_ok,
                "Dip:", dip_ok,
                "Sweep:", sweep_ok,
                "MoneyState:", "VAR" if symbol in money_state else "YOK",
                "IC FILTRE",
                flush=True
            )

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
    return "BINANCE FUTURES RADAR MANAGER Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
