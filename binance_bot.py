import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

BOT_NAME = "🚀 BINANCE RAILWAY FUTURES BOT"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 60
TOP_SYMBOL_LIMIT = 120
COOLDOWN_SECONDS = 60 * 30

MIN_SCORE_PREP = 9
MIN_SCORE_CONFIRM = 14

MIN_24H_VOLUME_USDT = 10_000_000
MIN_LAST_VOLUME_USDT = 50_000

WHALE_VOLUME_MULTIPLIER = 2.5
BIG_WICK_RATIO = 0.35
STRONG_BODY_RATIO = 0.55

BB_LENGTH = 20
BB_STD = 2
MA_LENGTH = 200

last_alert = {}


def telegram_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)


def get_top_symbols():
    url = f"{BASE_URL}/fapi/v1/ticker/24hr"
    data = requests.get(url, timeout=15).json()

    symbols = []
    for x in data:
        symbol = x.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if any(bad in symbol for bad in ["BUSD", "USDC"]):
            continue

        quote_vol = float(x.get("quoteVolume", 0))
        if quote_vol >= MIN_24H_VOLUME_USDT:
            symbols.append((symbol, quote_vol))

    symbols = sorted(symbols, key=lambda x: x[1], reverse=True)
    return [s[0] for s in symbols[:TOP_SYMBOL_LIMIT]]


def get_klines(symbol, interval="15m", limit=250):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = requests.get(url, params=params, timeout=15).json()

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    for col in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote"]:
        df[col] = df[col].astype(float)

    return df


def get_open_interest(symbol):
    url = f"{BASE_URL}/fapi/v1/openInterest"
    params = {"symbol": symbol}
    try:
        data = requests.get(url, params=params, timeout=10).json()
        return float(data.get("openInterest", 0))
    except:
        return 0


def add_indicators(df):
    df["ma200"] = df["close"].rolling(MA_LENGTH).mean()

    mid = df["close"].rolling(BB_LENGTH).mean()
    std = df["close"].rolling(BB_LENGTH).std()

    df["bb_mid"] = mid
    df["bb_upper"] = mid + BB_STD * std
    df["bb_lower"] = mid - BB_STD * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    avg_gain = pd.Series(gain).rolling(14).mean()
    avg_loss = pd.Series(loss).rolling(14).mean()

    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df


def candle_stats(row):
    high = row["high"]
    low = row["low"]
    open_ = row["open"]
    close = row["close"]

    rng = max(high - low, 0.00000001)
    body = abs(close - open_) / rng
    upper_wick = (high - max(open_, close)) / rng
    lower_wick = (min(open_, close) - low) / rng

    return body, upper_wick, lower_wick


def analyze_symbol(symbol):
    try:
        df15 = add_indicators(get_klines(symbol, "15m"))
        df1h = add_indicators(get_klines(symbol, "1h"))
    except Exception as e:
        print(symbol, "kline hata:", e)
        return None

    c15 = df15.iloc[-1]
    p15 = df15.iloc[-2]
    c1h = df1h.iloc[-1]

    price = c15["close"]

    body, upper_wick, lower_wick = candle_stats(c15)

    avg_vol = df15["quote_volume"].iloc[-21:-1].mean()
    last_vol = c15["quote_volume"]
    vol_mult = last_vol / avg_vol if avg_vol > 0 else 0

    taker_buy_ratio = c15["taker_buy_quote"] / last_vol if last_vol > 0 else 0
    taker_sell_ratio = 1 - taker_buy_ratio

    price_change_15m = ((c15["close"] - p15["close"]) / p15["close"]) * 100

    oi = get_open_interest(symbol)

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    # Bollinger LONG
    if price <= c15["bb_lower"] * 1.01:
        long_score += 3
        long_reasons.append("15m BB alt banda temas")

    if price <= c1h["bb_lower"] * 1.015:
        long_score += 4
        long_reasons.append("1h BB alt banda yakın")

    # Bollinger SHORT
    if price >= c15["bb_upper"] * 0.99:
        short_score += 3
        short_reasons.append("15m BB üst banda temas")

    if price >= c1h["bb_upper"] * 0.985:
        short_score += 4
        short_reasons.append("1h BB üst banda yakın")

    # Alttan balina / üstten satış
    if lower_wick >= BIG_WICK_RATIO and taker_buy_ratio >= 0.55:
        long_score += 4
        long_reasons.append("Alttan iğne + alıcı baskısı")

    if upper_wick >= BIG_WICK_RATIO and taker_sell_ratio >= 0.55:
        short_score += 4
        short_reasons.append("Üstten iğne + satıcı baskısı")

    # Hacim / balina hacmi
    if last_vol >= MIN_LAST_VOLUME_USDT and vol_mult >= WHALE_VOLUME_MULTIPLIER:
        long_score += 3
        short_score += 3
        long_reasons.append("Balina hacim artışı")
        short_reasons.append("Balina hacim artışı")

    # Mum gücü
    if body >= STRONG_BODY_RATIO and c15["close"] > c15["open"]:
        long_score += 3
        long_reasons.append("Güçlü yeşil mum")

    if body >= STRONG_BODY_RATIO and c15["close"] < c15["open"]:
        short_score += 3
        short_reasons.append("Güçlü kırmızı mum")

    # MA200 yön
    if price > c15["ma200"]:
        long_score += 2
        long_reasons.append("MA200 üstü")

    if price < c15["ma200"]:
        short_score += 2
        short_reasons.append("MA200 altı")

    # RSI aşırı bölge filtresi
    rsi = c15["rsi"]

    if rsi < 38:
        long_score += 2
        long_reasons.append("RSI dip bölge")

    if rsi > 68:
        short_score += 2
        short_reasons.append("RSI tepe bölge")

    signals = []

    if long_score >= MIN_SCORE_PREP:
        signals.append(("LONG", long_score, long_reasons))

    if short_score >= MIN_SCORE_PREP:
        signals.append(("SHORT", short_score, short_reasons))

    if not signals:
        return None

    best = sorted(signals, key=lambda x: x[1], reverse=True)[0]
    direction, score, reasons = best

    signal_type = "ONAY" if score >= MIN_SCORE_CONFIRM else "HAZIRLIK"

    return {
        "symbol": symbol,
        "direction": direction,
        "signal_type": signal_type,
        "score": score,
        "price": price,
        "price_change_15m": price_change_15m,
        "vol_mult": vol_mult,
        "last_vol": last_vol,
        "oi": oi,
        "rsi": rsi,
        "bb_width_15m": c15["bb_width"],
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "taker_buy_ratio": taker_buy_ratio,
        "reasons": reasons
    }


def can_alert(symbol, direction, signal_type):
    key = f"{symbol}_{direction}_{signal_type}"
    now = time.time()

    if key not in last_alert:
        last_alert[key] = now
        return True

    if now - last_alert[key] >= COOLDOWN_SECONDS:
        last_alert[key] = now
        return True

    return False


def format_signal(s):
    emoji = "🟢" if s["direction"] == "LONG" else "🔴"

    return f"""
{emoji} <b>{BOT_NAME}</b>

<b>{s['direction']} {s['signal_type']}</b>

Coin: <b>{s['symbol']}</b>
Fiyat: <b>{s['price']:.8f}</b>

Skor: <b>{s['score']}</b>

15m Değişim: %{s['price_change_15m']:.2f}
Hacim Artışı: {s['vol_mult']:.2f}x
Son Mum Hacmi: {s['last_vol']:.0f} USDT

OI: {s['oi']:.2f}

RSI: {s['rsi']:.2f}
BB Width 15m: {s['bb_width_15m']:.4f}

Mum Gövde: %{s['body'] * 100:.1f}
Üst Fitil: %{s['upper_wick'] * 100:.1f}
Alt Fitil: %{s['lower_wick'] * 100:.1f}

Taker Buy: %{s['taker_buy_ratio'] * 100:.1f}

Sebep:
- """ + "\n- ".join(s["reasons"]) + """

Not:
Bu sinyal direkt işlem değil hocam.
Direnç kırılımı / destek kırılımı ve 15m kapanış beklemek daha güvenli.
"""


def main():
    telegram_send("✅ Binance Railway Futures Bot başlatıldı hocam.")

    while True:
        try:
            symbols = get_top_symbols()
            print("Taranan coin:", len(symbols), datetime.now())

            for symbol in symbols:
                signal = analyze_symbol(symbol)

                if not signal:
                    continue

                if can_alert(signal["symbol"], signal["direction"], signal["signal_type"]):
                    msg = format_signal(signal)
                    telegram_send(msg)
                    print(msg)

                time.sleep(0.25)

        except Exception as e:
            print("Ana döngü hata:", e)
            telegram_send(f"⚠️ Bot hata verdi hocam:\n{e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
