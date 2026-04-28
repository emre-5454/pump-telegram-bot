from flask import Flask
import requests
import time
import threading
import os

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

# AYARLAR
MIN_VOLUME = 1_500_000
VOLUME_MULTIPLIER = 3
PREP_MAX_CHANGE = 2
PUMP_MIN_CHANGE = 3.5

COOLDOWN = 60 * 60
HEARTBEAT = 60 * 30

sent_coins = {}

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_symbols():
    data = requests.get("https://api.binance.com/api/v3/exchangeInfo").json()
    return [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]

def get_klines(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=12"
    return requests.get(url).json()

def analyze(symbol):
    candles = get_klines(symbol)
    if len(candles) < 12:
        return None

    last = candles[-1]
    prev = candles[-7:-1]

    open_15m = float(candles[-4][1])
    close_now = float(last[4])

    change = ((close_now - open_15m) / open_15m) * 100

    last_volume = float(last[5]) * close_now
    avg_volume = sum(float(c[5]) * float(c[4]) for c in prev) / len(prev)

    if avg_volume == 0:
        return None

    multiplier = last_volume / avg_volume

    if last_volume < MIN_VOLUME or multiplier < VOLUME_MULTIPLIER:
        return None

    # 🟡 ÖN HAZIRLIK
    if change < PREP_MAX_CHANGE:
        return ("prep", symbol, close_now, change, last_volume, multiplier)

    # 🔴 PUMP
    if change > PUMP_MIN_CHANGE:
        return ("pump", symbol, close_now, change, last_volume, multiplier)

    return None

def scan():
    symbols = get_symbols()
    last_heartbeat = 0

    telegram("🚀 BINANCE PRO BOT başladı hocam")

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
                        typ, sym, price, change, volume, mult = result

                        sent_coins[symbol] = now

                        if typ == "prep":
                            msg = f"""🟡 ÖN HAZIRLIK

Coin: {sym.replace("USDT","/USDT")}
Fiyat: {price}
15dk Değişim: %{round(change,2)}
Hacim: {round(volume):,}
Hacim Artışı: {round(mult,2)}x

⚠️ Pump hazırlığı olabilir"""

                        elif typ == "pump":
                            msg = f"""🔴 PUMP BAŞLADI

Coin: {sym.replace("USDT","/USDT")}
Fiyat: {price}
15dk Değişim: %{round(change,2)}
Hacim: {round(volume):,}
Hacim Artışı: {round(mult,2)}x

🚀 Hareket başladı dikkat"""

                        telegram(msg)

                    time.sleep(0.2)

                except Exception as e:
                    print("Coin hata:", e)
                    continue

            time.sleep(60)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "PRO BOT çalışıyor hocam"

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
