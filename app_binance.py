import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60

MIN_EARLY_SCORE = 8
MIN_PUMP_SCORE = 9
COOLDOWN_SECONDS = 3600  # aynı coin 1 saat tekrar atmaz

exchanges = {
    "BINANCE": ccxt.binance(),
    "MEXC": ccxt.mexc()
}

sent_cache = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
    except:
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

    upper = ma20 + (2 * std20)
    lower = ma20 - (2 * std20)

    bb_width = (upper - lower) / ma20
    rsi_val = rsi(close)

    vol_avg = volume.rolling(20).mean()
    volume_ratio = volume / vol_avg

    last_close = close.iloc[-1]
    last_rsi = rsi_val.iloc[-1]
    last_volume_ratio = volume_ratio.iloc[-1]
    last_bb_width = bb_width.iloc[-1]

    bb_squeeze = last_bb_width < 0.08
    upper_break = last_close > upper.iloc[-1]
    above_mid = last_close > ma20.iloc[-1]

    score = 0
    if bb_squeeze:
        score += 2
    if last_volume_ratio > 2:
        score += 3
    if last_rsi > 50:
        score += 2
    if upper_break:
        score += 3

    early = (
        bb_squeeze
        and last_volume_ratio > 2
        and 50 < last_rsi < 70
        and above_mid
        and score >= MIN_EARLY_SCORE
    )

    pump = (
        bb_squeeze
        and last_volume_ratio > 2.5
        and 55 < last_rsi < 80
        and upper_break
        and score >= MIN_PUMP_SCORE
    )

    return {
        "price": last_close,
        "rsi": last_rsi,
        "volume_ratio": last_volume_ratio,
        "bb_width": last_bb_width,
        "score": score,
        "early": early,
        "pump": pump
    }

def get_pairs(exchange):
    markets = exchange.load_markets()
    pairs = []
    for symbol, info in markets.items():
        if symbol.endswith("/USDT") and info.get("active", True):
            pairs.append(symbol)
    return pairs

def run_bot():
    send_telegram("✅ Pump scanner bot çalışmaya başladı.")

    while True:
        for ex_name, exchange in exchanges.items():
            try:
                pairs = get_pairs(exchange)

                for symbol in pairs:
                    try:
                        cache_key = f"{ex_name}-{symbol}"
                        now = time.time()

                        if cache_key in sent_cache:
                            if now - sent_cache[cache_key] < COOLDOWN_SECONDS:
                                continue

                        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)

                        if not ohlcv or len(ohlcv) < 50:
                            continue

                        df = pd.DataFrame(
                            ohlcv,
                            columns=["time", "open", "high", "low", "close", "volume"]
                        )

                        result = analyze(df)

                        if result["pump"]:
                            message = f"""
🚨 PUMP HAZIRLIĞI

Borsa: {ex_name}
Coin: {symbol}
Fiyat: {result['price']:.6f}
RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
BB Width: {result['bb_width']:.4f}
Puan: {result['score']}/10

Sinyal: ÜST BANT KIRILIM + HACİM
"""
                            send_telegram(message)
                            sent_cache[cache_key] = now

                        elif result["early"]:
                            message = f"""
🟡 ERKEN PARA GİRİŞİ

Borsa: {ex_name}
Coin: {symbol}
Fiyat: {result['price']:.6f}
RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
BB Width: {result['bb_width']:.4f}
Puan: {result['score']}/10

Sinyal: ORTA BANT ÜSTÜ + HACİM ARTIŞI
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
