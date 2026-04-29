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

def score_signal(signal_type, change, volume, multiplier, body_ratio):
    score = 0

    if multiplier >= 3:
        score += 2
    if multiplier >= 6:
        score += 1

    if volume >= 1_500_000:
        score += 1
    if volume >= 5_000_000:
        score += 1

    if change > 0:
        score += 2
    if change > 1:
        score += 1

    if body_ratio >= 0.55:
        score += 2

    if signal_type == "pump":
        score += 2
    elif signal_type == "buy_prep":
        score += 1
    elif signal_type == "sell_pressure":
        score -= 3
    elif signal_type == "neutral":
        score -= 1

    if score < 0:
        score = 0
    if score > 10:
        score = 10

    return score

def score_text(score):
    if score >= 8:
        return "🟢 GÜÇLÜ SİNYAL"
    elif score >= 6:
        return "🟡 TAKİP EDİLEBİLİR"
    elif score >= 4:
        return "⚪ ZAYIF / İZLE"
    else:
        return "🔴 UZAK DUR"

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
    body_ratio = body / candle_range if candle_range > 0 else 0

    if last_volume < MIN_VOLUME or multiplier < VOLUME_MULTIPLIER:
        return None

    if change > PUMP_MIN_CHANGE and last_close > last_open:
        signal_type = "pump"
    elif 0 < change < PREP_MAX_CHANGE and last_close > last_open:
        signal_type = "buy_prep"
    elif change < SELL_MIN_CHANGE or last_close < last_open:
        signal_type = "sell_pressure"
    else:
        signal_type = "neutral"

    score = score_signal(signal_type, change, last_volume, multiplier, body_ratio)

    if score < 4:
        return None

    return {
        "type": signal_type,
        "symbol": symbol,
        "price": close_now,
        "change": change,
        "volume": last_volume,
        "multiplier": multiplier,
        "body_ratio": body_ratio,
        "score": score
    }

def scan():
    symbols = get_symbols()
    last_heartbeat = 0

    telegram("🚀 BINANCE SKORLU PRO BOT başladı hocam")

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
                        sent_coins[symbol] = now

                        typ = result["type"]
                        score = result["score"]

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

Coin: {result['symbol'].replace("USDT","/USDT")}
Skor: {score}/10
Durum: {score_text(score)}

Fiyat: {result['price']}
15dk Değişim: %{round(result['change'], 2)}
Hacim: {round(result['volume']):,}
Hacim Artışı: {round(result['multiplier'], 2)}x
Mum Gövde Gücü: %{round(result['body_ratio'] * 100, 1)}

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
    return "BINANCE skorlu PRO BOT aktif", 200

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
