import time
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
TELEGRAM_CHAT_ID = "6977265844"

EXCHANGE_NAME = "mexc"

MAX_SYMBOLS = 800
SLEEP_SECONDS = 90

LIMIT_15M = 300
LIMIT_1M = 60

COOLDOWN_PREP = 4 * 60 * 60
COOLDOWN_EARLY = 2 * 60 * 60
COOLDOWN_PUMP = 3 * 60 * 60

PREP_MIN_SCORE = 7
PUMP_MIN_SCORE = 9
EARLY_MIN_SCORE = 6

PREP_MIN_VOLUME_RATIO = 1.4
PUMP_MIN_VOLUME_RATIO = 3.0
EARLY_MIN_VOLUME_RATIO = 4.0

PREP_MIN_15M_VOLUME_USDT = 10000
PUMP_MIN_15M_VOLUME_USDT = 40000
EARLY_MIN_1M_VOLUME_USDT = 8000

sent_prep = {}
sent_early = {}
sent_pump = {}

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def get_exchange():
    ex_class = getattr(ccxt, EXCHANGE_NAME)
    return ex_class({
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": "spot"
        }
    })

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

    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()
    df["ma200"] = close.rolling(200).mean()

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std() * 2
    df["bb_width"] = ((basis + dev) - (basis - dev)) / basis

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close, 14)
    df["roc"] = close.pct_change(9) * 100

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    obv_values = [0]
    for i in range(1, len(df)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv_values.append(obv_values[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i - 1]:
            obv_values.append(obv_values[-1] - volume.iloc[i])
        else:
            obv_values.append(obv_values[-1])

    df["obv"] = obv_values
    df["obv_ma"] = pd.Series(obv_values).rolling(20).mean().values

    candle_range = high - low
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range.replace(0, np.nan)

    return df

def score_15m(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume = last.volume * last.close

    if last.close > last.ema200 and last.ema20 > last.ema50:
        score += 2
        reasons.append("EMA trend yukarı")

    if last.close > last.ma200:
        score += 1
        reasons.append("MA200 üstü")

    bb_avg = df["bb_width"].rolling(50).mean().iloc[-1]
    if pd.notna(bb_avg) and last.bb_width < bb_avg:
        score += 1
        reasons.append("BB sıkışma")

    if volume_ratio >= PREP_MIN_VOLUME_RATIO:
        score += 2
        reasons.append("hacim hazırlık seviyesinde")

    if volume_ratio >= PUMP_MIN_VOLUME_RATIO:
        score += 2
        reasons.append("hacim patlaması var")

    if 45 <= last.rsi <= 75:
        score += 2
        reasons.append("RSI hazırlık bölgesi")

    if 70 < last.rsi <= 90:
        score += 2
        reasons.append("RSI pump bölgesi")

    if last.roc > 0.5:
        score += 1
        reasons.append("ROC pozitif")

    if last.roc > 2:
        score += 1
        reasons.append("ROC güçlü")

    if last.obv > last.obv_ma:
        score += 2
        reasons.append("OBV toplama")

    if last.macd > last.macd_signal and last.macd > prev.macd:
        score += 1
        reasons.append("MACD güçleniyor")

    if last.body_ratio >= 0.40:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if last.upper_wick <= 0.40:
        score += 1
        reasons.append("üst fitil düşük")

    return score, reasons, volume_ratio, usdt_volume

def early_1m_score(df):
    if len(df) < 25:
        return None

    last = df.iloc[-1]
    prev3 = df.iloc[-4]

    vol_avg = df["volume"].rolling(20).mean().iloc[-1]
    volume_ratio = last.volume / vol_avg if vol_avg > 0 else 0

    change_1m = ((last.close - last.open) / last.open) * 100
    change_3m = ((last.close - prev3.open) / prev3.open) * 100
    usdt_volume = last.volume * last.close

    candle_range = last.high - last.low
    body_ratio = abs(last.close - last.open) / candle_range if candle_range > 0 else 0
    upper_wick = (last.high - max(last.open, last.close)) / candle_range if candle_range > 0 else 0

    score = 0
    reasons = []

    if volume_ratio >= EARLY_MIN_VOLUME_RATIO:
        score += 2
        reasons.append("1m hacim patlaması")

    if usdt_volume >= EARLY_MIN_1M_VOLUME_USDT:
        score += 1
        reasons.append("1m USDT hacim yeterli")

    if change_1m >= 0.40:
        score += 1
        reasons.append("1m fiyat hareketi başladı")

    if change_3m >= 0.80:
        score += 1
        reasons.append("3m momentum var")

    if body_ratio >= 0.50:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if upper_wick <= 0.35:
        score += 1
        reasons.append("üst fitil düşük")

    if last.close > last.open:
        score += 1
        reasons.append("yeşil mum")

    return {
        "score": score,
        "reasons": reasons,
        "volume_ratio": volume_ratio,
        "usdt_volume": usdt_volume,
        "change_1m": change_1m,
        "change_3m": change_3m,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick,
        "price": last.close
    }

def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    swing_low = recent["low"].min()
    swing_high = recent["high"].max()
    impulse = swing_high - swing_low

    if impulse <= 0:
        return None

    return {
        "swing_low": swing_low,
        "swing_high": swing_high,
        "tp1": swing_high,
        "tp2": swing_low + impulse * 1.272,
        "tp3": swing_low + impulse * 1.618,
        "tp4": swing_low + impulse * 2.0,
        "invalidation": swing_low
    }

def build_symbols(exchange):
    markets = exchange.load_markets()

    symbols = [
        s for s in markets
        if s.endswith("/USDT")
        and markets[s].get("active", True)
        and not any(x in s for x in ["UP/", "DOWN/", "3L/", "3S/", "5L/", "5S/"])
    ]

    try:
        tickers = exchange.fetch_tickers(symbols)
        ranked = []

        for s in symbols:
            t = tickers.get(s, {})
            qv = t.get("quoteVolume") or 0
            ranked.append((s, qv))

        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)
        symbols = [x[0] for x in ranked]

    except Exception as e:
        print("Ticker sıralama yapılamadı:", e, flush=True)

    return symbols[:MAX_SYMBOLS]

def scan_symbol(exchange, symbol):
    now = time.time()

    try:
        ohlcv_1m = exchange.fetch_ohlcv(symbol, "1m", limit=LIMIT_1M)

        if ohlcv_1m and len(ohlcv_1m) >= 25:
            df1 = pd.DataFrame(
                ohlcv_1m,
                columns=["time", "open", "high", "low", "close", "volume"]
            )

            early = early_1m_score(df1)

            if early and early["score"] >= EARLY_MIN_SCORE:
                if early["volume_ratio"] >= EARLY_MIN_VOLUME_RATIO and early["usdt_volume"] >= EARLY_MIN_1M_VOLUME_USDT:
                    if symbol not in sent_early or now - sent_early[symbol] >= COOLDOWN_EARLY:
                        sent_early[symbol] = now

                        msg = f"""
🚨 MEXC ERKEN HACİM RADARI

Coin: {symbol}
Fiyat: {early['price']:.8f}

Skor: {early['score']}/8

1dk Değişim: %{early['change_1m']:.2f}
3dk Değişim: %{early['change_3m']:.2f}

1dk USDT Hacim: {int(early['usdt_volume'])}
Hacim Artışı: {early['volume_ratio']:.2f}x

Mum Gücü: {early['body_ratio']:.2f}
Üst Fitil: {early['upper_wick']:.2f}

📌 Sebep:
{", ".join(early['reasons'])}

📍 Karar:
Bu erken radar sinyalidir.
Direkt FOMO değil.
5m direnç kırılımı + retest kontrol et.
""".strip()

                        print("ERKEN SINYAL:", symbol, early["score"], flush=True)
                        send_telegram(msg)

        ohlcv_15m = exchange.fetch_ohlcv(symbol, "15m", limit=LIMIT_15M)

        if not ohlcv_15m or len(ohlcv_15m) < 220:
            return

        df = pd.DataFrame(
            ohlcv_15m,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        df = indicators(df)

        needed_cols = [
            "ema20", "ema50", "ema200", "ma200", "bb_width",
            "vol_avg", "rsi", "roc", "macd", "macd_signal",
            "obv", "obv_ma", "body_ratio", "upper_wick"
        ]

        df = df.dropna(subset=needed_cols).copy()

        if len(df) < 20:
            return

        score, reasons, volume_ratio, usdt_volume = score_15m(df)
        last = df.iloc[-1]

        change_15m = ((last.close - last.open) / last.open) * 100

        print(
            symbol,
            "SKOR:", score,
            "VOL:", round(volume_ratio, 2),
            "USDT_VOL:", int(usdt_volume),
            "RSI:", round(last.rsi, 2),
            "ROC:", round(last.roc, 2),
            flush=True
        )

        prep_valid = (
            score >= PREP_MIN_SCORE
            and volume_ratio >= PREP_MIN_VOLUME_RATIO
            and usdt_volume >= PREP_MIN_15M_VOLUME_USDT
            and 45 <= last.rsi <= 75
            and last.obv > last.obv_ma
        )

        pump_valid = (
            score >= PUMP_MIN_SCORE
            and volume_ratio >= PUMP_MIN_VOLUME_RATIO
            and usdt_volume >= PUMP_MIN_15M_VOLUME_USDT
            and 70 < last.rsi <= 90
            and last.roc > 2
            and last.body_ratio >= 0.45
            and last.upper_wick <= 0.35
        )

        signal_type = None

        if pump_valid:
            if symbol in sent_pump and now - sent_pump[symbol] < COOLDOWN_PUMP:
                return
            sent_pump[symbol] = now
            signal_type = "PUMP"

        elif prep_valid:
            if symbol in sent_prep and now - sent_prep[symbol] < COOLDOWN_PREP:
                return
            sent_prep[symbol] = now
            signal_type = "PREP"

        else:
            return

        fib = fib_targets(df)

        if fib:
            fib_text = f"""
Swing Dip: {fib['swing_low']:.8f}
Swing Tepe: {fib['swing_high']:.8f}

TP1: {fib['tp1']:.8f}
TP2: {fib['tp2']:.8f}
TP3: {fib['tp3']:.8f}
TP4: {fib['tp4']:.8f}

Geçersiz: {fib['invalidation']:.8f}
""".strip()
        else:
            fib_text = "Fib hesaplanamadı."

        title = "🔥 MEXC PUMP BAŞLADI" if signal_type == "PUMP" else "🟡 MEXC HAZIRLIK"

        msg = f"""
{title}

Coin: {symbol}
Fiyat: {last.close:.8f}

Skor: {score}/16

15dk Değişim: %{change_15m:.2f}
15dk USDT Hacim: {int(usdt_volume)}
Hacim Artışı: {volume_ratio:.2f}x

RSI: {last.rsi:.2f}
ROC: {last.roc:.2f}
BB Width: {last.bb_width:.4f}

Mum Gücü: {last.body_ratio:.2f}
Üst Fitil: {last.upper_wick:.2f}

📌 Sebep:
{", ".join(reasons)}

🎯 Fib:
{fib_text}

📍 Karar:
Hazırlık erken radardır.
Pump başladı sinyali hareket başlamış olabilir demektir.
Direkt FOMO değil, kırılım + retest kontrol et.
""".strip()

        print("15M SINYAL:", symbol, signal_type, "SKOR:", score, flush=True)
        send_telegram(msg)

    except Exception as e:
        print(f"HATA {symbol}: {e}", flush=True)

def main():
    send_telegram("✅ Railway MEXC erken radar + 15m hazırlık botu başladı.")
    print("BOT BASLADI", flush=True)

    exchange = get_exchange()

    while True:
        try:
            print(f"Tarama başladı: {datetime.now()}", flush=True)

            symbols = build_symbols(exchange)

            print(f"Taranacak coin sayısı: {len(symbols)}", flush=True)

            for symbol in symbols:
                scan_symbol(exchange, symbol)
                time.sleep(0.15)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e, flush=True)
            time.sleep(30)

if __name__ == "__main__":
    main()
