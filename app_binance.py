import ccxt
import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

TIMEFRAME = "15m"
LIMIT = 100
SLEEP_SECONDS = 60
COOLDOWN_SECONDS = 7200  # 2 saat

exchanges = {
    "BINANCE": ccxt.binance({
        "options": {"defaultType": "future"}
    }),
    "MEXC": ccxt.mexc({
        "options": {"defaultType": "swap"}
    })
}

ENABLED_MODES = ["ORTA", "SNIPER"]

MODES = {
    "ORTA": {
        "emoji": "🟡",
        "title": "BALİNA ADAYI",
        "bb_width": 0.075,
        "volume": 2.0,
        "rsi_min": 50,
        "rsi_max": 74,
        "score": 8
    },
    "SNIPER": {
        "emoji": "🚨",
        "title": "BALİNA ONAYLI PUMP HAZIRLIĞI",
        "bb_width": 0.06,
        "volume": 2.5,
        "rsi_min": 53,
        "rsi_max": 80,
        "score": 10
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

def get_oi_and_funding(exchange, symbol):
    oi_change = 0
    funding_rate = 0

    try:
        oi_now = exchange.fetch_open_interest(symbol)
        oi_value = oi_now.get("openInterestAmount") or oi_now.get("openInterestValue") or 0
    except Exception:
        oi_value = 0

    try:
        funding = exchange.fetch_funding_rate(symbol)
        funding_rate = funding.get("fundingRate", 0) or 0
    except Exception:
        funding_rate = 0

    # Not: CCXT çoğu borsada geçmiş OI verisini vermez.
    # Bu yüzden burada OI var mı / funding sağlıklı mı filtresi kullanıyoruz.
    return oi_value, funding_rate, oi_change

def analyze(df, exchange, symbol):
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
    prev_close = close.iloc[-2]

    price_change = ((last_close - prev_close) / prev_close) * 100

    last_open = df["open"].iloc[-1]
    last_high = df["high"].iloc[-1]
    last_low = df["low"].iloc[-1]

    last_rsi = rsi_val.iloc[-1]
    last_volume_ratio = volume_ratio.iloc[-1]
    last_bb_width = bb_width.iloc[-1]

    upper_break = last_close > upper.iloc[-1]
    above_mid = last_close > ma20.iloc[-1]

    candle_range = last_high - last_low
    body = abs(last_close - last_open)
    upper_wick = last_high - max(last_close, last_open)

    body_ratio = body / candle_range if candle_range != 0 else 0
    upper_wick_ratio = upper_wick / candle_range if candle_range != 0 else 0

    fake_pump = (
        upper_wick_ratio > 0.45
        or body_ratio < 0.30
        or last_rsi > 82
    )

    real_pump = (
        body_ratio > 0.50
        and upper_wick_ratio < 0.35
        and last_volume_ratio > 2
        and last_rsi < 80
    )

    oi_value, funding_rate, oi_change = get_oi_and_funding(exchange, symbol)

    funding_ok = funding_rate < 0.01
    oi_ok = oi_value > 0

    whale_ok = (
        oi_ok
        and funding_ok
        and last_volume_ratio > 2
        and price_change > 0
        and not fake_pump
    )

    score = 0

    if last_bb_width < 0.075:
        score += 2
    if last_volume_ratio > 2.0:
        score += 3
    if 50 < last_rsi < 74:
        score += 2
    if upper_break:
        score += 3
    if oi_ok:
        score += 1
    if funding_ok:
        score += 1
    if whale_ok:
        score += 2

    return {
        "price": last_close,
        "price_change": price_change,
        "rsi": last_rsi,
        "volume_ratio": last_volume_ratio,
        "bb_width": last_bb_width,
        "score": score,
        "upper_break": upper_break,
        "above_mid": above_mid,
        "body_ratio": body_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "real_pump": real_pump,
        "fake_pump": fake_pump,
        "oi_value": oi_value,
        "funding_rate": funding_rate,
        "oi_ok": oi_ok,
        "funding_ok": funding_ok,
        "whale_ok": whale_ok
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
            and not result["fake_pump"]
            and result["funding_ok"]
        )

        if mode_name == "SNIPER":
            condition = (
                condition
                and result["upper_break"]
                and result["whale_ok"]
                and result["real_pump"]
            )

        if condition:
            signals.append(mode_name)

    if "SNIPER" in signals:
        return "SNIPER"
    if "ORTA" in signals:
        return "ORTA"

    return None

def get_pairs(exchange):
    markets = exchange.load_markets()
    pairs = []

    for symbol, info in markets.items():
        if (
            symbol.endswith("/USDT")
            and info.get("active", True)
            and (info.get("swap") or info.get("future"))
        ):
            pairs.append(symbol)

    return pairs

def run_bot():
    send_telegram("✅ OI + Funding Balina Filtreli Pump Scanner aktif.")

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

                        result = analyze(df, exchange, symbol)
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
Son Mum Değişim: %{result['price_change']:.2f}

RSI: {result['rsi']:.2f}
Hacim: {result['volume_ratio']:.2f}x
BB: {result['bb_width']:.4f}
Puan: {result['score']}/12

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick_ratio']:.2f}

OI Var: {'EVET ✅' if result['oi_ok'] else 'YOK ⚠️'}
Funding: {result['funding_rate']:.5f}
Funding Sağlıklı: {'EVET ✅' if result['funding_ok'] else 'HAYIR ❌'}

Üst Bant Kırılım: {'VAR ✅' if result['upper_break'] else 'YOK ❌'}
Orta Bant Üstü: {'VAR ✅' if result['above_mid'] else 'YOK ❌'}
Fake Pump: {'EVET ❌' if result['fake_pump'] else 'HAYIR ✅'}
Balina Onayı: {'VAR 🐋✅' if result['whale_ok'] else 'YOK ⚠️'}
"""
                        send_telegram(message)
                        sent_cache[cache_key] = now

                        time.sleep(0.35)

                    except Exception:
                        continue

            except Exception as e:
                send_telegram(f"⚠️ {ex_name} hata: {str(e)}")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    run_bot()
