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

MAX_SYMBOLS = 60
STREAM_CHUNK_SIZE = 20
COOLDOWN = 15 * 60

# =====================
# FUTURES TEST AYARLARI
# =====================
MIN_SCORE = 4

MIN_QUOTE_VOLUME = 5000
MIN_VOLUME_RATIO = 1.5
MAX_PRICE_CHANGE_3M = 5.0
MIN_PRICE_CHANGE_1M = 0.00
MIN_BODY_RATIO = 0.10
MAX_UPPER_WICK = 0.90

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

    symbols = []

    for t in tickers:
        sym = t["symbol"]

        if sym not in tradable:
            continue

        if any(x in sym for x in ["UP", "DOWN", "BULL", "BEAR"]):
            continue

        quote_volume = float(t.get("quoteVolume", 0))
        symbols.append((sym.lower(), quote_volume))

    symbols.sort(key=lambda x: x[1], reverse=True)

    final_symbols = [x[0] for x in symbols[:MAX_SYMBOLS]]

    print("FUTURES SEMBOL SAYISI:", len(final_symbols), flush=True)
    return final_symbols

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

        # Test için 3 veri yeterli
        if len(d["closes"]) < 3:
            return

        closes = list(d["closes"])
        vols = list(d["quote_volumes"])

        avg_volume = sum(vols[:-1]) / (len(vols) - 1)
        if avg_volume <= 0:
            return

        volume_ratio = quote_volume / avg_volume

        price_change_1m = ((close - closes[-2]) / closes[-2]) * 100

        if len(closes) >= 4:
            price_change_3m = ((close - closes[-4]) / closes[-4]) * 100
        else:
            price_change_3m = price_change_1m

        candle_range = high - low

        if candle_range <= 0:
            body_ratio = 0
            upper_wick = 0
        else:
            body_ratio = abs(close - open_) / candle_range
            upper_wick = (high - max(open_, close)) / candle_range

        volume_3_rising = False
        if len(vols) >= 3:
            volume_3_rising = (
                vols[-1] > vols[-2]
                and vols[-2] > vols[-3]
            )

        print(
            symbol,
            "QV:", round(quote_volume, 2),
            "VR:", round(volume_ratio, 2),
            "PC1:", round(price_change_1m, 3),
            "PC3:", round(price_change_3m, 3),
            flush=True
        )

        now = time.time()

        if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
            return

        score = 0
        reasons = []

        if quote_volume >= MIN_QUOTE_VOLUME:
            score += 1
            reasons.append("futures 1dk hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("futures hacim artışı var")

        if volume_ratio >= 3:
            score += 1
            reasons.append("kaldıraçlı hacim agresif")

        if price_change_3m <= MAX_PRICE_CHANGE_3M:
            score += 1
            reasons.append("fiyat çok uçmamış")

        if price_change_1m >= MIN_PRICE_CHANGE_1M:
            score += 1
            reasons.append("1dk momentum pozitif")

        if body_ratio >= MIN_BODY_RATIO:
            score += 1
            reasons.append("mum gövdesi yeterli")

        if upper_wick <= MAX_UPPER_WICK:
            score += 1
            reasons.append("üst fitil kabul edilebilir")

        if volume_3_rising:
            score += 1
            reasons.append("3 mum futures hacim artıyor")

        valid_setup = (
            score >= MIN_SCORE
            and quote_volume >= MIN_QUOTE_VOLUME
            and volume_ratio >= MIN_VOLUME_RATIO
            and price_change_3m <= MAX_PRICE_CHANGE_3M
            and body_ratio >= MIN_BODY_RATIO
            and upper_wick <= MAX_UPPER_WICK
        )

        if not valid_setup:
            return

        msg = f"""
🧪 BINANCE FUTURES TEST SİNYALİ

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
Bu test sinyali.
Futures veri akışı kontrol ediliyor.
Direkt işlem değil.
Spot hacim + direnç kırılımı ile teyit et.
"""
        send_telegram(msg)
        sent_cache[symbol] = now

        print("FUTURES TEST SİNYAL:", symbol, "PUAN:", score, flush=True)

    except Exception as e:
        print("ANALIZ HATA:", symbol, e, flush=True)
def on_message(ws, message):
    try:
        # Test logu
        print("MESAJ GELDİ", flush=True)

        # JSON parse
        msg = json.loads(message)

        # Ham veriyi loga bas
        print(msg, flush=True)

        # Combined stream kontrolü
        if "data" in msg:
            data_msg = msg["data"]
        else:
            data_msg = msg

        # Event tipi kontrol
        if data_msg.get("e") != "kline":
            print("KLINE DEĞİL", flush=True)
            return

        # Mum verisi
        k = data_msg["k"]

        # Sembol
        symbol = data_msg["s"].lower()

        print(
            "KLINE:",
            symbol,
            "Close:",
            k["c"],
            "Volume:",
            k["q"],
            flush=True
        )

        # Analize gönder
        analyze_kline(symbol, k)

    except Exception as e:
        print("MESAJ HATA:", e, flush=True)

def on_error(ws, error):
    print("FUTURES WEBSOCKET HATA:", error, flush=True)

def on_close(ws, close_status_code, close_msg):
    print("FUTURES WEBSOCKET KAPANDI:", close_status_code, close_msg, flush=True)

def on_open(ws):
    print("FUTURES WEBSOCKET AÇILDI", flush=True)

def start_socket(symbols):
    print("FUTURES SOKET THREAD:", len(symbols), "sembol", flush=True)

    streams = "/".join([f"{s}@kline_1m" for s in symbols])
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    while True:
        try:
            print("FUTURES WEBSOCKET BAĞLANIYOR...", flush=True)

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
            print("FUTURES SOKET GENEL HATA:", e, flush=True)

        print("5 saniye sonra futures tekrar bağlanacak...", flush=True)
        time.sleep(5)

def run_bot():
    print("FUTURES BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BINANCE FUTURES TEST BOTU başladı hocam")

    try:
        symbols = get_futures_symbols()
    except Exception as e:
        print("FUTURES SEMBOL ALMA HATASI:", e, flush=True)
        send_telegram(f"❌ Futures sembol alma hatası: {e}")
        return

    if not symbols:
        print("FUTURES SEMBOL LİSTESİ BOŞ", flush=True)
        send_telegram("❌ Futures sembol listesi boş geldi hocam")
        return

    chunks = [
        symbols[i:i + STREAM_CHUNK_SIZE]
        for i in range(0, len(symbols), STREAM_CHUNK_SIZE)
    ]

    print("FUTURES CHUNK SAYISI:", len(chunks), flush=True)

    for chunk in chunks:
        threading.Thread(
            target=start_socket,
            args=(chunk,),
            daemon=True
        ).start()

        time.sleep(1)

@app.route("/")
def home():
    return "Binance Futures test botu aktif", 200

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
