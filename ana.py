import time
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
TELEGRAM_CHAT_ID = "6977265844"

EXCHANGES = ["mexc"]
TIMEFRAME = "15m"

LIMIT = 300
SLEEP_SECONDS = 90
MAX_SYMBOLS = 300

COOLDOWN_PREP = 6 * 60 * 60
COOLDOWN_PUMP = 3 * 60 * 60

PREP_MIN_SCORE = 8
PUMP_MIN_SCORE = 9

PREP_MIN_VOLUME_RATIO = 1.7
PUMP_MIN_VOLUME_RATIO = 3.0

PREP_MIN_15M_VOLUME_USDT = 20000
PUMP_MIN_15M_VOLUME_USDT = 40000

sent_prep = {}
sent_pump = {}

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e, flush=True)

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
    df["upper_wick"] = (high - pd.concat([df["open"], close], axis=1).max(axis=1)) / candle_range.replace(0, np.nan)

    return df

def score_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    volume_ratio = last.volume / last.vol_avg if last.vol_avg > 0 else 0
    usdt_volume_15m = last.volume * last.close

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

    if 50 <= last.rsi <= 70:
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

    if last.body_ratio >= 0.45:
        score += 1
        reasons.append("mum gövdesi güçlü")

    if last.upper_wick <= 0.35:
        score += 1
        reasons.append("üst fitil düşük")

    return score, reasons, volume_ratio, usdt_volume_15m

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

def get_exchange(name):
    ex_class = getattr(ccxt, name)
    return ex_class({"enableRateLimit": True, "timeout": 20000})

def scan_exchange(exchange_name):
    exchange = get_exchange(exchange_name)
    markets = exchange.load_markets()

    symbols = [
        s for s in markets
        if s.endswith("/USDT") and markets[s].get("active", True)
    ]

    print(f"{exchange_name.upper()} toplam coin: {len(symbols)}", flush=True)

    symbols = symbols[:MAX_SYMBOLS]
    print(f"TARANACAK COIN: {len(symbols)}", flush=True)

    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=LIMIT)

            if not ohlcv or len(ohlcv) < 220:
                continue

            df = pd.DataFrame(
                ohlcv,
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
                continue

            score, reasons, volume_ratio, usdt_volume_15m = score_signal(df)
            last = df.iloc[-1]

            change_15m = ((last.close - last.open) / last.open) * 100

            print(
                symbol,
                "SKOR:", score,
                "VOL:", round(volume_ratio, 2),
                "USDT_VOL:", int(usdt_volume_15m),
                "RSI:", round(last.rsi, 2),
                "ROC:", round(last.roc, 2),
                flush=True
            )

            now = time.time()

            prep_valid = (
                score >= PREP_MIN_SCORE
                and volume_ratio >= PREP_MIN_VOLUME_RATIO
                and usdt_volume_15m >= PREP_MIN_15M_VOLUME_USDT
                and 50 <= last.rsi <= 70
                and last.obv > last.obv_ma
            )

            pump_valid = (
                score >= PUMP_MIN_SCORE
                and volume_ratio >= PUMP_MIN_VOLUME_RATIO
                and usdt_volume_15m >= PUMP_MIN_15M_VOLUME_USDT
                and 70 < last.rsi <= 90
                and last.roc > 2
                and last.body_ratio >= 0.45
                and last.upper_wick <= 0.35
            )

            signal_type = None

            if pump_valid:
                if symbol in sent_pump and now - sent_pump[symbol] < COOLDOWN_PUMP:
                    continue
                sent_pump[symbol] = now
                signal_type = "PUMP"

            elif prep_valid:
                if symbol in sent_prep and now - sent_prep[symbol] < COOLDOWN_PREP:
                    continue
                sent_prep[symbol] = now
                signal_type = "PREP"

            else:
                continue

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
15dk USDT Hacim: {int(usdt_volume_15m)}
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

            print("SINYAL:", symbol, signal_type, "SKOR:", score, flush=True)
            send_telegram(msg)

            time.sleep(0.2)

        except Exception as e:
            print(f"HATA {exchange_name} {symbol}: {e}", flush=True)
            time.sleep(0.3)

def main():
    send_telegram("✅ Railway MEXC Hazırlık + Pump Başladı botu başladı.")
    print("BOT BASLADI", flush=True)

    while True:
        print(f"Tarama başladı: {datetime.now()}", flush=True)

        for ex in EXCHANGES:
            try:
                scan_exchange(ex)
            except Exception as e:
                print(f"{ex} genel hata: {e}", flush=True)

        print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()
