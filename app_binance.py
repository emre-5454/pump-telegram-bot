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

SYMBOL = "btcusdt"
COOLDOWN = 5 * 60

MIN_QUOTE_VOLUME = 1000
MIN_VOLUME_RATIO = 1.0

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

        if len(d["closes"]) < 3:
            return

        closes = list(d["closes"])
        vols = list(d["quote_volumes"])

        avg_volume = sum(vols[:-1]) / (len(vols) - 1)
        if avg_volume <= 0:
            return

        volume_ratio = quote_volume / avg_volume
        price_change_1m = ((close - closes[-2]) / closes[-2]) * 100

        candle_range = high - low
        if candle_range <= 0:
            body_ratio = 0
            upper_wick = 0
        else:
            body_ratio = abs(close - open_) / candle_range
            upper_wick = (high - max(open_, close)) / candle_range

        print(
            "KLINE OKUNDU:",
            symbol,
            "QV:", round(quote_volume, 2),
            "VR:", round(volume_ratio, 2),
            "PC1:", round(price_change_1m, 3),
            flush=True
        )

        now = time.time()
        if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
            return

        if quote_volume >= MIN_QUOTE_VOLUME and volume_ratio >= MIN_VOLUME_RATIO:
            msg = f"""
🧪 BINANCE FUTURES BTC TEST

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.2f}

1dk Değişim: %{price_change_1m:.3f}

1dk Futures Hacim: {int(quote_volume)} USDT
Futures Hacim Artışı: {volume_ratio:.2f}x

Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

📍 Karar:
Bu sadece websocket veri akışı testidir.
"""
            send_telegram(msg)
            sent_cache[symbol] = now
            print("TEST SİNYAL GÖNDERİLDİ:", symbol, flush=True)

    except Exception as e:
        print("ANALIZ HATA:", e, flush=True)

def on_open(ws):
    print("FUTURES WS AÇILDI - SUBSCRIBE GÖNDERİLİYOR", flush=True)

    sub_msg = {
        "method": "SUBSCRIBE",
        "params": [f"{SYMBOL}@kline_1m"],
        "id": 1
    }

    ws.send(json.dumps(sub_msg))
    print("SUBSCRIBE GÖNDERİLDİ:", sub_msg, flush=True)

def on_message(ws, message):
    try:
        print("MESAJ GELDİ", flush=True)

        msg = json.loads(message)
        print(msg, flush=True)

        # Subscribe cevabı
        if "result" in msg:
            print("SUBSCRIBE CEVABI:", msg, flush=True)
            return

        if msg.get("e") != "kline":
            print("KLINE DEĞİL:", msg.get("e"), flush=True)
            return

        k = msg["k"]
        symbol = msg["s"].lower()

        analyze_kline(symbol, k)

    except Exception as e:
        print("MESAJ HATA:", e, flush=True)

def on_error(ws, error):
    print("FUTURES WS HATA:", error, flush=True)

def on_close(ws, close_status_code, close_msg):
    print("FUTURES WS KAPANDI:", close_status_code, close_msg, flush=True)

def start_socket():
    url = "wss://fstream.binance.com/ws"

    while True:
        try:
            print("FUTURES WS BAĞLANIYOR...", flush=True)

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
            print("FUTURES WS GENEL HATA:", e, flush=True)

        print("5 saniye sonra tekrar bağlanacak...", flush=True)
        time.sleep(5)

def run_bot():
    print("FUTURES BTC TEST BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BINANCE FUTURES BTC TEST BOTU başladı hocam")
    threading.Thread(target=start_socket, daemon=True).start()

@app.route("/")
def home():
    return "Binance Futures BTC test botu aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
