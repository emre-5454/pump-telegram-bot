from flask import Flask
import websocket
import threading
import requests
import json
import time
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("TELEGRAM HATA:", e, flush=True)

def on_message(ws, message):
    try:
        print("HAM MESAJ GELDİ", flush=True)
        msg = json.loads(message)
        print(msg, flush=True)

        price = float(msg["p"])
        qty = float(msg["q"])
        quote = price * qty
        is_buy = not msg["m"]

        text = f"""
🧪 BTC FUTURES AGGTRADE TEST

Fiyat: {price}
İşlem Hacmi: {quote:.2f} USDT
Yön: {'ALICI ✅' if is_buy else 'SATICI ❌'}

Bu sadece canlı veri testidir.
"""
        send_telegram(text)

    except Exception as e:
        print("MESAJ HATA:", e, flush=True)

def on_open(ws):
    print("BTC FUTURES AGGTRADE WS AÇILDI", flush=True)

def on_error(ws, error):
    print("WS HATA:", error, flush=True)

def on_close(ws, code, msg):
    print("WS KAPANDI:", code, msg, flush=True)

def start_socket():
    url = "wss://fstream.binance.com/ws/btcusdt@aggTrade"

    while True:
        try:
            print("BTC FUTURES WS BAĞLANIYOR...", flush=True)

            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws.run_forever(ping_interval=20, ping_timeout=10)

        except Exception as e:
            print("SOCKET HATA:", e, flush=True)

        time.sleep(5)

def run_bot():
    print("BTC FUTURES TEST BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BTC Futures aggTrade test başladı hocam")
    threading.Thread(target=start_socket, daemon=True).start()

@app.route("/")
def home():
    return "BTC Futures aggTrade test aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
