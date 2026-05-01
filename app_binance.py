import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60
COOLDOWN_SECONDS = 10800  # aynı coin aynı modda 3 saat tekrar atmaz

exchanges = {
    "BINANCE": ccxt.binance(),
    "MEXC": ccxt.mexc()
}

ENABLED_MODES = ["ORTA", "SNIPER"]

MODES = {
    "ORTA": {
        "emoji": "🟡",
        "title": "GÜÇLÜ SETUP",
        "bb_width": 0.06,
        "volume": 2.5,
        "rsi_min": 52,
        "rsi_max": 72,
        "score": 8
    },
    "SNIPER": {
        "emoji": "🚨",
        "title": "PUMP HAZIRLIĞI",
        "bb_width": 0.05,
        "volume": 3.0,
        "rsi_min": 55,
        "rsi_max": 78,
        "score": 9
    }
}

sent_cache = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
    except Exception:
        pass

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(df):
    close = df["close"]
    volume = df["volume"]

    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()

    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20

    bb_width = (upper - lower) / ma20
    rsi_val = rsi(close)

    vol_avg = volume.rolling(20).mean()
    volume_ratio = volume / vol_avg

    last_close = close.iloc[-1]
    last_rsi = rsi_val.iloc[-1]
    last_volume_ratio = volume_ratio.iloc[-1]
    last_bb_width = bb_width.iloc[-1]

    upper_break = last_close > upper.iloc[-1]
    above_mid = last_close > ma20.iloc[-1]

    score = 0

    if last_bb_width < 0.06:
        score += 2
    if last_volume_ratio > 2.5:
        score += 3
    if 52 < last_rsi < 72:
        score += 2
    if upper_break:
        score += 3

    return {
        "price": last_close,
        "rsi": last_rsi,
        "volume_ratio": last_volume_ratio,
        "bb_width": last_bb_width,
        "score": score,
        "upper_break": upper_break,
        "above_mid": above_mid
    }

def detect_mode(result):
    signals = []

    for mode_name in ENABLED_MODES:
        mode = MODES[mode_name]

        condition = (
            result["bb_width"] < mode["bb_width"]
            and result["volume_ratio"] > mode["volume"]
            and mode["rsi_min"] < result["rsi"] < mode["rsi_max"]
            and result["above_mid"]
            and result["score"] >= mode["score"]
        )

        if mode_name == "SNIPER":
            condition = condition and result["upper_break"]

        if condition:
            signals.append(mode_name)

    if "SNIPER" in signals:
        return "SNIPER"
    if "ORTA" in signals:
        return "ORTA"

    return None

def get_pairs(exchange):
    markets = exchange.load_markets()
    return [
        symbol for symbol, info in markets.items()
        if symbol.endswith("/USDT") and info.get("active", True)
    ]

def run_bot():
    send_telegram("✅ Spam azaltılmış Pump Scanner Bot çalışmaya başladı.")

    while True:
        for ex_name, exchange in exchanges.items():
            try:
                pairs = get_pairs(exchange)

                for symbol in pairs:
                    try:
                        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)

                        if not ohlcv or len(ohlcv) < 50:
                            continue

                        df = pd.DataFrame(
                            ohlcv,
                            columns=["time", "open", "high", "low", "close", "volume"]
                        )

                        result = analyze(df)
                        mode_name = detect_mode(result)

                        if not mode_name:
                            continue

                        cache_key = f"{ex_name}-{symbol}-{mode_name}"
                        now = time.time()

                        if cache_key in sent_cache and now - sent_cache[cache_key] < COOLDOWN_SECONDS:
                            continue

                        mode = MODES[mode_name]

                        message = f"""
{mode['emoji']} {mode['title']}

Mod: {mode_name}
Borsa: {ex_name}
Coin: {symbol}
Fiyat: {result['price']:.6f}
RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
BB Width: {result['bb_width']:.4f}
Puan: {result['score']}/10

Üst Bant Kırılım: {'VAR ✅' if result['upper_break'] else 'YOK ❌'}
Orta Bant Üstü: {'VAR ✅' if result['above_mid'] else 'YOK ❌'}
"""
                        send_telegram(message)
                        sent_cache[cache_key] = now

                        time.sleep(0.25)

                    except Exception:
                        continue

            except Exception as e:
                send_telegram(f"⚠️ {ex_name} hata: {str(e)}")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    run_bot()
