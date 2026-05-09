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
# FUTURES AGGTRADE AYARLARI
# =====================
MAX_SYMBOLS = 80
STREAM_CHUNK_SIZE = 20

WINDOW_SECONDS = 60
COOLDOWN = 4 * 60 * 60

MIN_SCORE = 6
MIN_1M_VOLUME_USDT = 30000
MIN_VOLUME_RATIO = 3.0
MIN_PRICE_CHANGE_60S = 0.08
MAX_PRICE_CHANGE_60S = 1.50
MIN_BUY_RATIO = 0.55

sent_cache = {}

trade_data = defaultdict(lambda: {
    "trades": deque(),
    "minute_volumes": deque(maxlen=20),
    "prices": deque(maxlen=200)
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

        quote_volume = float(t.get("quoteVolume", 0))
        symbols.append((sym.lower(), quote_volume))

    symbols.sort(key=lambda x: x[1], reverse=True)

    final_symbols = [x[0] for x in symbols[:MAX_SYMBOLS]]

    print("FUTURES SEMBOL SAYISI:", len(final_symbols), flush=True)
    return final_symbols

def clean_old_trades(symbol, now):
    d = trade_data[symbol]

    while d["trades"] and now - d["trades"][0]["time"] > WINDOW_SECONDS:
        d["trades"].popleft()

def analyze_trade(symbol):
    try:
        now = time.time()
        d = trade_data[symbol]

        clean_old_trades(symbol, now)

        trades = list(d["trades"])
        if len(trades) < 5:
            return

        volume_60s = sum(t["quote"] for t in trades)
        buy_volume_60s = sum(t["quote"] for t in trades if t["is_buy"])

        if volume_60s <= 0:
            return

        buy_ratio = buy_volume_60s / volume_60s

        prices = list(d["prices"])
        if len(prices) < 2:
            return

        first_price = prices[0]
        last_price = prices[-1]

        price_change_60s = ((last_price - first_price) / first_price) * 100

        # Her 60 saniyelik hacim penceresini ortalamaya ekle
        if len(d["minute_volumes"]) == 0 or now - getattr(analyze_trade, f"last_store_{symbol}", 0) > 60:
            d["minute_volumes"].append(volume_60s)
            setattr(analyze_trade, f"last_store_{symbol}", now)

        if len(d["minute_volumes"]) < 5:
            avg_volume = max(volume_60s / 2, 1)
        else:
            avg_volume = sum(list(d["minute_volumes"])[:-1]) / max(len(d["minute_volumes"]) - 1, 1)

        volume_ratio = volume_60s / avg_volume if avg_volume > 0 else 0

        if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
            return

        score = 0
        reasons = []

        if volume_60s >= MIN_1M_VOLUME_USDT:
            score += 1
            reasons.append("60sn futures hacim güçlü")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("hacim ortalamaya göre agresif")

        if volume_ratio >= 5:
            score += 1
            reasons.append("kaldıraçlı hacim çok agresif")

        if MIN_PRICE_CHANGE_60S <= price_change_60s <= MAX_PRICE_CHANGE_60S:
            score += 1
            reasons.append("fiyat hareketi kontrollü")

        if buy_ratio >= MIN_BUY_RATIO:
            score += 1
            reasons.append("alıcı oranı baskın")

        if len(trades) >= 20:
            score += 1
            reasons.append("işlem sayısı yeterli")

        valid_setup = (
            score >= MIN_SCORE
            and volume_60s >= MIN_1M_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and MIN_PRICE_CHANGE_60S <= price_change_60s <= MAX_PRICE_CHANGE_60S
            and buy_ratio >= MIN_BUY_RATIO
        )

        if not valid_setup:
            return

        msg = f"""
🔥 BINANCE FUTURES AGGTRADE SETUP

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {last_price:.6f}

Puan: {score}/10

60sn Değişim: %{price_change_60s:.2f}

60sn Futures Hacim: {int(volume_60s)} USDT
Hacim Artışı: {volume_ratio:.2f}x
Alıcı Oranı: %{buy_ratio * 100:.1f}
İşlem Sayısı: {len(trades)}

📌 Sebep:
{", ".join(reasons)}

📍 Karar:
Futures tarafında canlı hacim girişi var.
Tek başına long değil.
Spot hacim + direnç kırılımı + retest ile teyit et.
"""
        send_telegram(msg)
        sent_cache[symbol] = now

        print("FUTURES AGGTRADE SETUP:", symbol, "PUAN:", score, flush=True)

    except Exception as e:
        print("ANALIZ HATA:", symbol, e, flush=True)

def on_message(ws, message):
    try:
        msg = json.loads(message)

        if "data" in msg:
            data_msg = msg["data"]
        else:
            data_msg = msg

        if data_msg.get("e") != "aggTrade":
            return

        symbol = data_msg["s"].lower()
        price = float(data_msg["p"])
        qty = float(data_msg["q"])
        quote = price * qty

        # Binance aggTrade: m=True ise buyer market maker, yani agresif satıcı var
        is_buyer_maker = data_msg["m"]
        is_buy = not is_buyer_maker

        now = time.time()

        d = trade_data[symbol]
        d["trades"].append({
            "time": now,
            "price": price,
            "quote": quote,
            "is_buy": is_buy
        })
        d["prices"].append(price)

        analyze_trade(symbol)

    except Exception as e:
        print("MESAJ HATA:", e, flush=True)

def on_error(ws, error):
    print("FUTURES AGG WS HATA:", error, flush=True)

def on_close(ws, close_status_code, close_msg):
    print("FUTURES AGG WS KAPANDI:", close_status_code, close_msg, flush=True)

def on_open(ws):
    print("FUTURES AGG WS AÇILDI", flush=True)

def start_socket(symbols):
    print("FUTURES AGG SOCKET:", len(symbols), "sembol", flush=True)

    streams = "/".join([f"{s}@aggTrade" for s in symbols])
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    while True:
        try:
            print("FUTURES AGG WS BAĞLANIYOR...", flush=True)

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
            print("FUTURES AGG SOCKET HATA:", e, flush=True)

        print("5 saniye sonra tekrar bağlanacak...", flush=True)
        time.sleep(5)

def run_bot():
    print("FUTURES AGGTRADE BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BINANCE FUTURES AGGTRADE HACİM BOTU başladı hocam")

    try:
        symbols = get_futures_symbols()
    except Exception as e:
        print("SEMBOL HATASI:", e, flush=True)
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
    return "Binance Futures aggTrade hacim botu aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
