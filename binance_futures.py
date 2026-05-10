
from flask import Flask
import requests
import threading
import time
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

SLEEP_SECONDS = 30
COOLDOWN = 4 * 60 * 60

MAX_SYMBOLS = 120
MIN_SCORE = 4

MIN_QUOTE_VOLUME_24H = 20_000_000
MIN_VOLUME_SPIKE = 1.15
MIN_PRICE_CHANGE = 0.05
MAX_PRICE_CHANGE = 5.00

sent_cache = {}
last_volume_cache = {}

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("TELEGRAM HATA:", e, flush=True)

def get_futures_tickers():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    data = requests.get(url, timeout=20).json()

    tickers = []

    for t in data:
        symbol = t.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in ["UP", "DOWN", "BULL", "BEAR"]):
            continue

        try:
            quote_volume = float(t["quoteVolume"])
            price_change_percent = float(t["priceChangePercent"])
            last_price = float(t["lastPrice"])
        except:
            continue

        if quote_volume < MIN_QUOTE_VOLUME_24H:
            continue

        tickers.append({
            "symbol": symbol,
            "price": last_price,
            "quote_volume": quote_volume,
            "price_change_percent": price_change_percent
        })

    tickers.sort(key=lambda x: x["quote_volume"], reverse=True)

    return tickers[:MAX_SYMBOLS]

def analyze_ticker(t):
    symbol = t["symbol"]
    price = t["price"]
    quote_volume = t["quote_volume"]
    price_change_percent = t["price_change_percent"]

    prev_volume = last_volume_cache.get(symbol)

    last_volume_cache[symbol] = quote_volume

    if prev_volume is None or prev_volume <= 0:
        return None

    volume_spike = quote_volume / prev_volume

    now = time.time()

    if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
        return None

    score = 0
    reasons = []

    if quote_volume >= MIN_QUOTE_VOLUME_24H:
        score += 1
        reasons.append("24h futures hacmi güçlü")

    if volume_spike >= MIN_VOLUME_SPIKE:
        score += 3
        reasons.append("son taramaya göre futures hacim artışı var")

    if volume_spike >= 1.80:
        score += 1
        reasons.append("hacim artışı agresif")

    if MIN_PRICE_CHANGE <= abs(price_change_percent) <= MAX_PRICE_CHANGE:
        score += 1
        reasons.append("fiyat hareketi kontrollü")

    if price_change_percent > 0:
        score += 1
        reasons.append("fiyat pozitif")

    valid_setup = (
        score >= MIN_SCORE
        and volume_spike >= MIN_VOLUME_SPIKE
        and MIN_PRICE_CHANGE <= abs(price_change_percent) <= MAX_PRICE_CHANGE
    )

    if not valid_setup:
        return None

    sent_cache[symbol] = now

    return {
        "symbol": symbol,
        "price": price,
        "quote_volume": quote_volume,
        "volume_spike": volume_spike,
        "price_change_percent": price_change_percent,
        "score": score,
        "reasons": reasons
    }

def run_bot():
    send_telegram("🚀 BINANCE FUTURES REST SCANNER başladı hocam")
    print("BINANCE FUTURES REST BOT ÇALIŞTI", flush=True)

    while True:
        try:
            tickers = get_futures_tickers()
            print("Taranan futures coin:", len(tickers), flush=True)

            for t in tickers:
                result = analyze_ticker(t)

                if not result:
                    continue

                msg = f"""
🔥 BINANCE FUTURES REST SETUP

Coin: {result['symbol'].replace('USDT', '/USDT')}
Fiyat: {result['price']:.6f}

Puan: {result['score']}/10

24h Futures Hacim: {int(result['quote_volume'])} USDT
Hacim Artışı: {result['volume_spike']:.2f}x

24h Fiyat Değişimi: %{result['price_change_percent']:.2f}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Futures tarafında hacim artışı var.
Direkt long/short değil.
Spot hacim + direnç kırılımı + retest ile teyit et.
"""
                send_telegram(msg)
                print("FUTURES SETUP:", result["symbol"], result["score"], flush=True)
                time.sleep(0.2)

            print("Futures tarama bitti", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("GENEL HATA:", e, flush=True)
            time.sleep(10)

@app.route("/")
def home():
    return "Binance Futures REST scanner aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
