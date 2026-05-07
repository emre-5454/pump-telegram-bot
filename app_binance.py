from flask import Flask
import websocket
import threading
import requests
import json
import time
import os
from collections import defaultdict, deque

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ")
CHAT_ID = os.environ.get("CHAT_ID", "6977265844")

# =====================
# AYARLAR
# =====================
COOLDOWN = 4 * 60 * 60

MIN_QUOTE_VOLUME_USDT = 15000      # 1 dakikalık minimum hacim
MIN_VOLUME_RATIO = 4.0             # son 1dk hacim / ortalama hacim
MAX_PRICE_CHANGE_3M = 1.2          # daha pump uçmadan yakalasın
MIN_PRICE_CHANGE_1M = 0.10         # hareket başlamış olsun
MAX_UPPER_WICK = 0.35
MIN_BODY_RATIO = 0.35

MAX_SYMBOLS = 250                  # çok coin taramasın diye
STREAM_CHUNK_SIZE = 80

sent_cache = {}
data = defaultdict(lambda: {
    "closes": deque(maxlen=30),
    "volumes": deque(maxlen=30),
    "quote_volumes": deque(maxlen=30)
})

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)

def get_binance_usdt_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    r = requests.get(url, timeout=15).json()

    symbols = []

    for s in r["symbols"]:
        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["isSpotTradingAllowed"]
        ):
            base = s["baseAsset"]

            blacklist = ["UP", "DOWN", "BULL", "BEAR"]
            if any(x in base for x in blacklist):
                continue

            symbols.append(s["symbol"].lower())

    return symbols[:MAX_SYMBOLS]

def analyze_kline(symbol, k):
    try:
        close = float(k["c"])
        open_ = float(k["o"])
        high = float(k["h"])
        low = float(k["l"])
        volume = float(k["v"])
        quote_volume = float(k["q"])

        d = data[symbol]

        d["closes"].append(close)
        d["volumes"].append(volume)
        d["quote_volumes"].append(quote_volume)

        if len(d["closes"]) < 20:
            return

        avg_quote_volume = sum(list(d["quote_volumes"])[:-1]) / (len(d["quote_volumes"]) - 1)

        if avg_quote_volume <= 0:
            return

        volume_ratio = quote_volume / avg_quote_volume

        close_1m_ago = list(d["closes"])[-2]
        close_3m_ago = list(d["closes"])[-4]

        price_change_1m = ((close - close_1m_ago) / close_1m_ago) * 100
        price_change_3m = ((close - close_3m_ago) / close_3m_ago) * 100

        candle_range = high - low
        if candle_range <= 0:
            return

        body_ratio = abs(close - open_) / candle_range
        upper_wick = (high - max(open_, close)) / candle_range

        volumes = list(d["quote_volumes"])
        volume_3_rising = (
            volumes[-1] > volumes[-2]
            and volumes[-2] > volumes[-3]
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
🟡 BINANCE WEBSOCKET ERKEN HACİM

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
Erken hacim girişi var.
Direkt long değil.
Direnç kırılımı + retest bekle.
"""
        send_telegram(msg)
        sent_cache[symbol] = now

    except Exception as e:
        print("Analiz hata:", symbol, e)

def on_message(ws, message):
    try:
        msg = json.loads(message)

        if "data" not in msg:
            return

        data_msg = msg["data"]

        if data_msg.get("e") != "kline":
            return

        k = data_msg["k"]

        # Sadece kapanan 1m mum
        if not k["x"]:
            return

        symbol = k["s"].lower()
        analyze_kline(symbol, k)

    except Exception as e:
        print("Mesaj hata:", e)

def on_error(ws, error):
    print("Websocket hata:", error)

def on_close(ws, close_status_code, close_msg):
    print("Websocket kapandı:", close_status_code, close_msg)

def on_open(ws):
    print("Websocket açıldı")

def start_socket(symbols):
    streams = "/".join([f"{s}@kline_1m" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while True:
        try:
            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print("Socket genel hata:", e)

        time.sleep(5)

def run_bot():
    send_telegram("🚀 BINANCE WEBSOCKET ERKEN HACİM BOTU başladı hocam")

    symbols = get_binance_usdt_symbols()
    print("Toplam sembol:", len(symbols))

    chunks = [
        symbols[i:i + STREAM_CHUNK_SIZE]
        for i in range(0, len(symbols), STREAM_CHUNK_SIZE)
    ]

    for chunk in chunks:
        threading.Thread(target=start_socket, args=(chunk,), daemon=True).start()
        time.sleep(1)

@app.route("/")
def home():
    return "Binance websocket erken hacim botu aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
