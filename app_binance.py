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

# =====================
# SNIPER AYARLARI
# =====================
COOLDOWN = 4 * 60 * 60

MIN_QUOTE_VOLUME_USDT = 10000
MIN_VOLUME_RATIO = 3.0
MAX_PRICE_CHANGE_3M = 1.5
MIN_PRICE_CHANGE_1M = 0.08
MAX_UPPER_WICK = 0.35
MIN_BODY_RATIO = 0.45

MAX_SYMBOLS = 150
STREAM_CHUNK_SIZE = 50

sent_cache = {}

data_store = defaultdict(lambda: {
    "closes": deque(maxlen=30),
    "quote_volumes": deque(maxlen=30)
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

def get_binance_usdt_symbols():
    print("BINANCE SEMBOLLER ALINIYOR...", flush=True)

    url = "https://api.binance.com/api/v3/exchangeInfo"
    r = requests.get(url, timeout=20)

    print("BINANCE DURUMU:", r.status_code, flush=True)

    data = r.json()
    symbols = []

    for s in data["symbols"]:
        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s.get("isSpotTradingAllowed", False)
        ):
            base = s["baseAsset"]

            if any(x in base for x in ["UP", "DOWN", "BULL", "BEAR"]):
                continue

            symbols.append(s["symbol"].lower())

    print("SEMBOL SAYISI:", len(symbols), flush=True)
    return symbols[:MAX_SYMBOLS]

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

        vols = list(d["quote_volumes"])
        closes = list(d["closes"])

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

        setup = (
            quote_volume >= MIN_QUOTE_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and 0 < price_change_3m <= MAX_PRICE_CHANGE_3M
            and price_change_1m >= MIN_PRICE_CHANGE_1M
            and body_ratio >= MIN_BODY_RATIO
            and upper_wick <= MAX_UPPER_WICK
            and volume_3_rising
        )

        if not setup:
            return

        msg = f"""
🚨 BINANCE WEBSOCKET SNIPER

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.6f}

1dk Değişim: %{price_change_1m:.2f}
3dk Değişim: %{price_change_3m:.2f}

1dk Hacim: {int(quote_volume)} USDT
Hacim Artışı: {volume_ratio:.2f}x

3 Mum Hacim Artışı: VAR ✅

Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

📍 Karar:
Gerçek hacim girişi olabilir.
Direkt FOMO değil.
Direnç kırılımı + retest izle.
"""

        send_telegram(msg)

        sent_cache[symbol] = now

        print("SNIPER SİNYAL:", symbol, flush=True)

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

        # SADECE KAPANAN 1DK MUM
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
    print("WEBSOCKET AÇILDI", flush=True)

def start_socket(symbols):
    print("SOKET THREAD BAŞLADI:", len(symbols), "sembol", flush=True)

    streams = "/".join([f"{s}@kline_1m" for s in symbols])

    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while True:
        try:
            print("WEBSOCKET BAĞLANIYOR...", flush=True)

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
    print("RUN BOT ÇALIŞTI", flush=True)

    send_telegram("🚀 BINANCE WEBSOCKET SNIPER başladı hocam")

    try:
        symbols = get_binance_usdt_symbols()

    except Exception as e:
        print("SEMBOL ALMA HATASI:", e, flush=True)

        send_telegram(f"❌ Binance sembol alma hatası: {e}")

        return

    if not symbols:
        print("SEMBOL LİSTESİ BOŞ", flush=True)

        send_telegram("❌ Binance sembol listesi boş geldi hocam")

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
    return "Binance websocket sniper aktif", 200

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
