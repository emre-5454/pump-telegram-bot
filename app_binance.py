from flask import Flask
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

MIN_VOLUME = 1_500_000
VOLUME_MULTIPLIER = 3
PREP_MAX_CHANGE = 2
PUMP_MIN_CHANGE = 3.5
SELL_MIN_CHANGE = -1.0

COOLDOWN = 60 * 60
HEARTBEAT = 60 * 30

sent_coins = {}

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)

def get_symbols():
    data = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=15).json()
    return [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
    ]

def get_klines(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=12"
    return requests.get(url, timeout=15).json()

def analyze(symbol):
    candles = get_klines(symbol)

    if len(candles) < 12:
        return None

    last = candles[-1]
    prev = candles[-7:-1]

    open_15m = float(candles[-4][1])
    close_now = float(last[4])

    last_open = float(last[1])
    last_high = float(last[2])
    last_low = float(last[3])
    last_close = float(last[4])

    change = ((close_now - open_15m) / open_15m) * 100

    last_volume = float(last[5]) * close_now
    avg_volume = sum(float(c[5]) * float(c[4]) for c in prev) / len(prev)

    if avg_volume == 0:
        return None

    multiplier = last_volume / avg_volume

    candle_range = last_high - last_low
    body = abs(last_close - last_open)

    if candle_range == 0:
        body_ratio = 0
    else:
        body_ratio = body / candle_range

    if last_volume < MIN_VOLUME or multiplier < VOLUME_MULTIPLIER:
        return None

    if change > PUMP_MIN_CHANGE and last_close > last_open:
        return ("pump", symbol, close_now, change, last_volume, multiplier, body_ratio)

    if 0 < change < PREP_MAX_CHANGE and last_close > last_open:
        return ("buy_prep", symbol, close_now, change, last_volume, multiplier, body_ratio)

    if change < SELL_MIN_CHANGE or last_close < last_open:
        return ("sell_pressure", symbol, close_now, change, last_volume, multiplier, body_ratio)

    return ("neutral", symbol, close_now, change, last_volume, multiplier, body_ratio)

def scan():
    symbols = get_symbols()
    last_heartbeat = 0

    telegram("🚀 BINANCE yön ayıran PRO BOT başladı hocam")

    while True:
        try:
            now = time.time()

            if now - last_heartbeat > HEARTBEAT:
                telegram("🟢 Bot çalışıyor hocam")
                last_heartbeat = now

            for symbol in symbols:
                try:
                    if now - sent_coins.get(symbol, 0) < COOLDOWN:
                        continue

                    result = analyze(symbol)

                    if result:
                        typ, sym, price, change, volume, mult, body_ratio = result
                        sent_coins[symbol] = now

                        if typ == "buy_prep":
                            title = "🟡 ALIM HAZIRLIĞI"
                            note = "Hacim artıyor + fiyat yukarı dönüyor. Pump hazırlığı olabilir."

                        elif typ == "pump":
                            title = "🔴 PUMP BAŞLADI"
                            note = "Fiyat güçlü hareket ediyor. FOMO yapmadan retest kontrol et."

                        elif typ == "sell_pressure":
                            title = "🔻 SATIŞ BASKISI"
                            note = "Hacim artıyor ama fiyat düşüyor. Dump / likidite temizliği olabilir."

                        else:
                            title = "⚪ KARARSIZ HACİM"
                            note = "Hacim var ama yön net değil. İzle, direkt işlem yok."

                        msg = f"""{title}

Coin: {sym.replace("USDT","/USDT")}
Fiyat: {price}
15dk Değişim: %{round(change, 2)}
Hacim: {round(volume):,}
Hacim Artışı: {round(mult, 2)}x
Mum Gövde Gücü: %{round(body_ratio * 100, 1)}

Not: {note}

⚠️ Kontrol:
- 5m mum kapanışı güçlü mü?
- Fitil uzun mu?
- Direnç kırıldı mı?
- Hacim devam ediyor mu?"""

                        telegram(msg)

                    time.sleep(0.2)

                except Exception as e:
                    print("Coin hata:", symbol, e)
                    continue

            time.sleep(60)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "BINANCE yön ayıran PRO BOT aktif", 200

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
