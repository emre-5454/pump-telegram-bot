from flask import Flask
import websocket
import threading
import requests
import json
import time
import os
from collections import defaultdict, deque

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

MAX_SYMBOLS = 150
STREAM_CHUNK_SIZE = 50
COOLDOWN = 6 * 60 * 60

MIN_SCORE = 7

MIN_QUOTE_VOLUME = 50000
MIN_VOLUME_RATIO = 4.0
MAX_PRICE_CHANGE_3M = 1.8
MIN_PRICE_CHANGE_1M = 0.08
MIN_BODY_RATIO = 0.45
MAX_UPPER_WICK = 0.35

sent_cache = {}

data_store = defaultdict(lambda: {
    "closes": deque(maxlen=40),
    "quote_volumes": deque(maxlen=40)
})

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("TELEGRAM HATA:", e, flush=True)

def get_futures_symbols():
    print("FUTURES SEMBOLLER ALINIYOR...", flush=True)

    exchange_info = requests.get(
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        timeout=20
    ).json()

    tradable = set()

    for s in exchange_info["symbols"]:
        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
        ):
            tradable.add(s["symbol"])

    tickers = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        timeout=20
    ).json()

    sorted_symbols = []

    for t in tickers:
        sym = t["symbol"]

        if sym not in tradable:
            continue

        if any(x in sym for x in ["UP", "DOWN", "BULL", "BEAR"]):
            continue

        quote_volume = float(t.get("quoteVolume", 0))
        sorted_symbols.append((sym.lower(), quote_volume))

    sorted_symbols.sort(key=lambda x: x[1], reverse=True)

    symbols = [x[0] for x in sorted_symbols[:MAX_SYMBOLS]]

    print("FUTURES SEMBOL SAYISI:", len(symbols), flush=True)
    return symbols

def analyze_kline(symbol, k):
    try:
        close = float(k["c"])
        open_ = float(k["o"])
        high = float(k["h"])
        low = float(k["l"])
        quote_volume = float(k["q"])

        d = data_store[symbol]
        d["closes"].append(close)
        d["quote_volumes"].append(quote_volume)

        if len(d["closes"]) < 20:
            return

        closes = list(d["closes"])
        vols = list(d["quote_volumes"])

        avg_volume = sum(vols[:-1]) / (len(vols) - 1)

        if avg_volume <= 0:
            return

        volume_ratio = quote_volume / avg_volume

        price_change_1m = ((close - closes[-2]) / closes[-2]) * 100
        price_change_3m = ((close - closes[-4]) / closes[-4]) * 100

        candle_range = high - low
        if candle_range <= 0:
            return

        body_ratio = abs(close - open_) / candle_range
        upper_wick = (high - max(open_, close)) / candle_range

        volume_3_rising = (
            vols[-1] > vols[-2]
            and vols[-2] > vols[-3]
        )

        now = time.time()

        if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
            return

        score = 0
        reasons = []

        if quote_volume >= MIN_QUOTE_VOLUME:
            score += 1
            reasons.append("futures 1dk hacim güçlü")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("futures hacim artışı güçlü")

        if volume_ratio >= 7:
            score += 1
            reasons.append("kaldıraçlı hacim agresif")

        if 0 < price_change_3m <= MAX_PRICE_CHANGE_3M:
            score += 1
            reasons.append("fiyat henüz çok uçmamış")

        if price_change_1m >= MIN_PRICE_CHANGE_1M:
            score += 1
            reasons.append("1dk momentum var")

        if body_ratio >= MIN_BODY_RATIO:
            score += 1
            reasons.append("mum gövdesi güçlü")

        if upper_wick <= MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil düşük")

        if volume_3_rising:
            score += 1
            reasons.append("3 mum futures hacim artıyor")

        valid_setup = (
            score >= MIN_SCORE
            and quote_volume >= MIN_QUOTE_VOLUME
            and volume_ratio >= MIN_VOLUME_RATIO
            and 0 < price_change_3m <= MAX_PRICE_CHANGE_3M
            and body_ratio >= MIN_BODY_RATIO
            and upper_wick <= MAX_UPPER_WICK
        )

        if not valid_setup:
            return

        msg = f"""
🔥 BINANCE FUTURES HACİM SETUP

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.6f}

Puan: {score}/10

1dk Değişim: %{price_change_1m:.2f}
3dk Değişim: %{price_change_3m:.2f}

1dk Futures Hacim: {int(quote_volume)} USDT
Futures Hacim Artışı: {volume_ratio:.2f}x

3 Mum Hacim Artışı: {'VAR ✅' if volume_3_rising else 'YOK ❌'}

Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

📌 Sebep:
{", ".join(reasons)}

📍 Karar:
Futures tarafında kaldıraçlı hacim girişi var.
Tek başına long değil.
Spot hacim + direnç kırılımı + retest ile teyit et.
"""
        send_telegram(msg)
        sent_cache[symbol] = now

        print("FUTURES SETUP:", symbol, "PUAN:", score, flush=True)

    except Exception as e:
        print("ANALIZ HATA:", symbol, e, flush=True)

def on_message(ws, message):
    try:
        msg = json.loads(message)

        if "data" not in msg:
            return

        data_msg = msg["data"]

        if data_msg.get("e") != "kline":
            return

        k = data_msg["k"]

        # sadece kapanan 1dk mum
        if not k["x"]:
            return

        symbol = k["s"].lower()
        analyze_kline(symbol, k)

    except Exception as e:
        print("MESAJ HATA:", e, flush=True)

def on_error(ws, error):
    print("WEBSOCKET HATA:", error, flush=True)

def on_close(ws, close_status_code, close_msg):
    print("WEBSOCKET KAPANDI:", close_status_code, close_msg, flush=True)

def on_open(ws):
    print("FUTURES WEBSOCKET AÇILDI", flush=True)

def start_socket(symbols):
    print("FUTURES SOKET THREAD:", len(symbols), "sembol", flush=True)

    streams = "/".join([f"{s}@kline_1m" for s in symbols])
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    while True:
        try:
            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as e:
            print("SOKET GENEL HATA:", e, flush=True)

        print("5 saniye sonra tekrar bağlanacak...", flush=True)
        time.sleep(5)

def run_bot():
    print("FUTURES BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BINANCE FUTURES HACİM BOTU başladı hocam")

    try:
        symbols = get_futures_symbols()
    except Exception as e:
        print("SEMBOL ALMA HATASI:", e, flush=True)
        send_telegram(f"❌ Futures sembol alma hatası: {e}")
        return

    chunks = [
        symbols[i:i + STREAM_CHUNK_SIZE]
        for i in range(0, len(symbols), STREAM_CHUNK_SIZE)
    ]

    print("CHUNK SAYISI:", len(chunks), flush=True)

    for chunk in chunks:
        threading.Thread(
            target=start_socket,
            args=(chunk,),
            daemon=True
        ).start()

        time.sleep(1)

@app.route("/")
def home():
    return "Binance Futures hacim botu aktif", 200

if __name__ == "__main__":
    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
