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

PREP_COOLDOWN = 4 * 60 * 60
SNIPER_COOLDOWN = 4 * 60 * 60
STRUCTURE_COOLDOWN = 6 * 60 * 60

# 🟡 HAZIRLIK
PREP_MIN_VOLUME_RATIO = 1.6
PREP_MAX_VOLUME_RATIO = 3.5
PREP_MIN_QUOTE_VOLUME = 4000
PREP_MAX_PRICE_CHANGE_3M = 0.80
PREP_MIN_BODY_RATIO = 0.20
PREP_MAX_UPPER_WICK = 0.55

# 🚨 SNIPER
SNIPER_MIN_VOLUME_RATIO = 3.0
SNIPER_MIN_QUOTE_VOLUME = 10000
SNIPER_MIN_PRICE_CHANGE_1M = 0.08
SNIPER_MAX_PRICE_CHANGE_3M = 1.50
SNIPER_MIN_BODY_RATIO = 0.45
SNIPER_MAX_UPPER_WICK = 0.35

# 🟢 STRUCTURE
STRUCTURE_MIN_VOLUME_RATIO = 4.0
STRUCTURE_MIN_BODY_RATIO = 0.55
STRUCTURE_MAX_UPPER_WICK = 0.25
STRUCTURE_LOOKBACK = 20

prep_cache = {}
sniper_cache = {}
structure_cache = {}

data_store = defaultdict(lambda: {
    "closes": deque(maxlen=40),
    "highs": deque(maxlen=40),
    "lows": deque(maxlen=40),
    "opens": deque(maxlen=40),
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

def get_binance_usdt_symbols():
    print("BINANCE SEMBOLLER ALINIYOR...", flush=True)
    r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=20)
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

def calc_structure(closes, highs, lows):
    if len(closes) < STRUCTURE_LOOKBACK + 1:
        return False, False, None, None

    recent_highs = list(highs)[-STRUCTURE_LOOKBACK:-1]
    recent_lows = list(lows)[-STRUCTURE_LOOKBACK:-1]
    recent_closes = list(closes)[-6:]

    prev_high = max(recent_highs)
    prev_low = min(recent_lows)

    last_close = closes[-1]
    last_low = lows[-1]

    ma5 = sum(recent_closes) / len(recent_closes)

    bos = last_close > prev_high
    msb = last_low > prev_low and last_close > ma5

    return bos, msb, prev_high, prev_low

def analyze_kline(symbol, k):
    try:
        close = float(k["c"])
        open_ = float(k["o"])
        high = float(k["h"])
        low = float(k["l"])
        quote_volume = float(k["q"])

        d = data_store[symbol]
        d["closes"].append(close)
        d["opens"].append(open_)
        d["highs"].append(high)
        d["lows"].append(low)
        d["quote_volumes"].append(quote_volume)

        if len(d["closes"]) < 20:
            return

        closes = list(d["closes"])
        highs = list(d["highs"])
        lows = list(d["lows"])
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

        volume_3_rising = vols[-1] > vols[-2] and vols[-2] > vols[-3]

        bos, msb, prev_high, prev_low = calc_structure(
            d["closes"], d["highs"], d["lows"]
        )

        now = time.time()

        # 🟡 HAZIRLIK RADAR
        prep_setup = (
            quote_volume >= PREP_MIN_QUOTE_VOLUME
            and PREP_MIN_VOLUME_RATIO <= volume_ratio <= PREP_MAX_VOLUME_RATIO
            and 0 < price_change_3m <= PREP_MAX_PRICE_CHANGE_3M
            and body_ratio >= PREP_MIN_BODY_RATIO
            and upper_wick <= PREP_MAX_UPPER_WICK
        )

        if prep_setup:
            if symbol not in prep_cache or now - prep_cache[symbol] > PREP_COOLDOWN:
                msg = f"""
🟡 BINANCE PUMP HAZIRLIĞI

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.6f}

1dk Değişim: %{price_change_1m:.2f}
3dk Değişim: %{price_change_3m:.2f}

1dk Hacim: {int(quote_volume)} USDT
Hacim Artışı: {volume_ratio:.2f}x

Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

BOS: {'VAR ✅' if bos else 'YOK ❌'}
MSB: {'VAR ✅' if msb else 'YOK ❌'}

📍 Karar:
Radar sinyali.
Direkt long değil.
Direnç kırılımı + hacim devamı bekle.
"""
                send_telegram(msg)
                prep_cache[symbol] = now
                print("HAZIRLIK:", symbol, flush=True)

        # 🚨 WEBSOCKET SNIPER
        sniper_setup = (
            quote_volume >= SNIPER_MIN_QUOTE_VOLUME
            and volume_ratio >= SNIPER_MIN_VOLUME_RATIO
            and 0 < price_change_3m <= SNIPER_MAX_PRICE_CHANGE_3M
            and price_change_1m >= SNIPER_MIN_PRICE_CHANGE_1M
            and body_ratio >= SNIPER_MIN_BODY_RATIO
            and upper_wick <= SNIPER_MAX_UPPER_WICK
            and volume_3_rising
        )

        if sniper_setup:
            if symbol not in sniper_cache or now - sniper_cache[symbol] > SNIPER_COOLDOWN:
                msg = f"""
🚨 BINANCE WEBSOCKET SNIPER

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.6f}

1dk Değişim: %{price_change_1m:.2f}
3dk Değişim: %{price_change_3m:.2f}

1dk Hacim: {int(quote_volume)} USDT
Hacim Artışı: {volume_ratio:.2f}x
3 Mum Hacim Artışı: {'VAR ✅' if volume_3_rising else 'YOK ❌'}

Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

BOS: {'VAR ✅' if bos else 'YOK ❌'}
MSB: {'VAR ✅' if msb else 'YOK ❌'}

📍 Karar:
Hacim girişi güçlendi.
FOMO değil.
Retest / direnç kırılımı izle.
"""
                send_telegram(msg)
                sniper_cache[symbol] = now
                print("SNIPER:", symbol, flush=True)

        # 🟢 STRUCTURE ONAY
        structure_setup = (
            volume_ratio >= STRUCTURE_MIN_VOLUME_RATIO
            and body_ratio >= STRUCTURE_MIN_BODY_RATIO
            and upper_wick <= STRUCTURE_MAX_UPPER_WICK
            and price_change_1m > 0
            and (bos or msb)
        )

        if structure_setup:
            if symbol not in structure_cache or now - structure_cache[symbol] > STRUCTURE_COOLDOWN:
                msg = f"""
🟢 BINANCE STRUCTURE ONAY

Coin: {symbol.upper().replace('USDT', '/USDT')}
Fiyat: {close:.6f}

1dk Değişim: %{price_change_1m:.2f}
3dk Değişim: %{price_change_3m:.2f}

Hacim Artışı: {volume_ratio:.2f}x
Mum Gücü: {body_ratio:.2f}
Üst Fitil: {upper_wick:.2f}

BOS: {'VAR ✅' if bos else 'YOK ❌'}
MSB: {'VAR ✅' if msb else 'YOK ❌'}
Kırılan Seviye: {prev_high:.6f if prev_high else 0}

📍 Karar:
Yapı onayı geldi.
Retest başarılı olursa daha temiz setup.
🛑 Stop: kırılan seviye altı / son dip
"""
                send_telegram(msg)
                structure_cache[symbol] = now
                print("STRUCTURE:", symbol, flush=True)

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

        # Sadece kapanan 1 dakikalık mum
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
            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)

        except Exception as e:
            print("SOKET GENEL HATA:", e, flush=True)

        print("5 saniye sonra tekrar bağlanacak...", flush=True)
        time.sleep(5)

def run_bot():
    print("RUN BOT ÇALIŞTI", flush=True)
    send_telegram("🚀 BINANCE BİRLEŞİK PUMP RADAR + SNIPER başladı hocam")

    try:
        symbols = get_binance_usdt_symbols()
    except Exception as e:
        print("SEMBOL ALMA HATASI:", e, flush=True)
        send_telegram(f"❌ Binance sembol alma hatası: {e}")
        return

    chunks = [
        symbols[i:i + STREAM_CHUNK_SIZE]
        for i in range(0, len(symbols), STREAM_CHUNK_SIZE)
    ]

    print("CHUNK SAYISI:", len(chunks), flush=True)

    for chunk in chunks:
        threading.Thread(target=start_socket, args=(chunk,), daemon=True).start()
        time.sleep(1)

@app.route("/")
def home():
    return "Binance birleşik pump radar + sniper aktif", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
