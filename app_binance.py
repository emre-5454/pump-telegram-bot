import ccxt
import time
import requests
import pandas as pd

# TELEGRAM BİLGİLERİ
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

# AYARLAR
TIMEFRAME = "15m"
LIMIT = 80
SLEEP_SECONDS = 60
COOLDOWN = 7200  # aynı coin 1 saat tekrar atmaz

# FİLTRE AYARLARI
MIN_VOLUME_RATIO = 2.0
RSI_MIN = 50
RSI_MAX = 72
MIN_BODY_RATIO = 0.35

exchange = ccxt.binance()

sent_cache = {}

def send_telegram(message):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        print("TELEGRAM:", r.status_code, r.text)
    except Exception as e:
        print("TELEGRAM HATA:", e)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)

        if not ohlcv or len(ohlcv) < 30:
            return None

        df = pd.DataFrame(
            ohlcv,
            columns=["time", "open", "high", "low", "close", "volume"]
        )

        close = df["close"]
        volume = df["volume"]

        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20

        rsi = calculate_rsi(close).iloc[-1]

        vol_avg = volume.rolling(20).mean().iloc[-1]
        if vol_avg == 0 or pd.isna(vol_avg):
            return None

        volume_ratio = volume.iloc[-1] / vol_avg

        last_price = close.iloc[-1]
        prev_price = close.iloc[-2]
        price_change = ((last_price - prev_price) / prev_price) * 100

        candle_range = df["high"].iloc[-1] - df["low"].iloc[-1]
        candle_body = abs(df["close"].iloc[-1] - df["open"].iloc[-1])
        body_ratio = candle_body / candle_range if candle_range != 0 else 0

        upper_break = last_price > upper.iloc[-1]

        signal = (
            volume_ratio > MIN_VOLUME_RATIO
            and RSI_MIN < rsi < RSI_MAX
            and upper_break
            and price_change > 0
            and body_ratio > MIN_BODY_RATIO
        )

        if signal:
            return {
                "symbol": symbol,
                "price": last_price,
                "price_change": price_change,
                "rsi": rsi,
                "volume_ratio": volume_ratio,
                "body_ratio": body_ratio
            }

    except Exception as e:
        print("ANALIZ HATA:", symbol, e)

    return None

def get_pairs():
    markets = exchange.load_markets()
    pairs = []

    for symbol, info in markets.items():
        if symbol.endswith("/USDT") and info.get("active", True):
            pairs.append(symbol)

    return pairs

def run_bot():
    send_telegram("✅ Binance Pump Bot aktif hocam.")

    while True:
        try:
            pairs = get_pairs()

            for symbol in pairs:
                try:
                    now = time.time()

                    if symbol in sent_cache:
                        if now - sent_cache[symbol] < COOLDOWN:
                            continue

                    result = analyze(symbol)

                    if not result:
                        continue

                    message = f"""
🚨 BINANCE PUMP ADAYI

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}
Son Mum Değişim: %{result['price_change']:.2f}

RSI: {result['rsi']:.2f}
Hacim Artışı: {result['volume_ratio']:.2f}x
Mum Gücü: {result['body_ratio']:.2f}

⚠️ Kontrol:
- 5m mum güçlü mü?
- Üst direnç yakın mı?
- Hacim devam ediyor mu?
"""

                    send_telegram(message)
                    sent_cache[symbol] = now

                    time.sleep(0.25)

                except Exception as e:
                    print("PAIR HATA:", symbol, e)

            print("TARAMA BİTTİ")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e)
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
