import ccxt
import time
import requests

# =========================================================
# BOT ADI
# =========================================================
BOT_NAME = "☁️ RENDER PARA GİRİŞİ BOTU"

# =========================================================
# TELEGRAM
# =========================================================
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

def telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

    except Exception as e:

        print("Telegram hata:", e)

# =========================================================
# MEXC
# =========================================================
exchange = ccxt.mexc({
    "enableRateLimit": True
})

# =========================================================
# AYARLAR
# =========================================================
TIMEFRAME = "5m"

SLEEP_SECONDS = 60

COOLDOWN = 3 * 60 * 60

# =========================================================
# PARA GİRİŞİ AYARLARI
# =========================================================
MIN_VOLUME_USDT = 25000

MIN_VOLUME_RATIO = 2.5

MIN_PRICE_CHANGE_5M = -0.50

MAX_PRICE_CHANGE_15M = 4.0

# =========================================================
# CACHE
# =========================================================
sent_cache = {}

# =========================================================
# PAIRS
# =========================================================
def get_pairs():

    markets = exchange.load_markets()

    pairs = []

    blacklist = [
        "UP/",
        "DOWN/",
        "BULL/",
        "BEAR/"
    ]

    for symbol in markets:

        if not symbol.endswith("/USDT"):
            continue

        if not markets[symbol].get("active", True):
            continue

        if any(x in symbol for x in blacklist):
            continue

        pairs.append(symbol)

    return pairs

# =========================================================
# ANALİZ
# =========================================================
def analyze(symbol):

    try:

        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=30
        )

        if len(candles) < 20:
            return None

        last = candles[-1]
        prev = candles[-2]

        c = last[4]
        v = last[5]

        volumes = [x[5] for x in candles]

        # =====================================================
        # FİYAT DEĞİŞİMİ
        # =====================================================
        price_change_5m = (
            (c - prev[4]) / prev[4]
        ) * 100

        price_change_15m = (
            (c - candles[-4][4]) / candles[-4][4]
        ) * 100

        # =====================================================
        # HACİM
        # =====================================================
        avg_volume = sum(
            volumes[-21:-1]
        ) / 20

        if avg_volume == 0:
            return None

        volume_ratio = v / avg_volume

        volume_usdt = v * c

        # =====================================================
        # ŞARTLAR
        # =====================================================
        valid = (

            volume_usdt >= MIN_VOLUME_USDT

            and

            volume_ratio >= MIN_VOLUME_RATIO

            and

            price_change_5m >= MIN_PRICE_CHANGE_5M

            and

            price_change_15m <= MAX_PRICE_CHANGE_15M
        )

        if not valid:
            return None

        return {

            "symbol": symbol,

            "price": c,

            "price_change_5m": price_change_5m,

            "price_change_15m": price_change_15m,

            "volume_usdt": volume_usdt,

            "volume_ratio": volume_ratio
        }

    except Exception as e:

        print("Analiz hata:", symbol, e)

        return None

# =========================================================
# RUN
# =========================================================
def run():

    telegram(
        f"{BOT_NAME} aktif edildi hocam 🚀"
    )

    while True:

        try:

            pairs = get_pairs()

            now = time.time()

            for symbol in pairs:

                # =============================================
                # COOLDOWN
                # =============================================
                if (
                    symbol in sent_cache
                    and
                    now - sent_cache[symbol] < COOLDOWN
                ):
                    continue

                result = analyze(symbol)

                if not result:
                    continue

                # =============================================
                # MESAJ
                # =============================================
                msg = f"""
{BOT_NAME}

💰 MEXC PARA GİRİŞİ

Coin:
{result['symbol']}

Fiyat:
{result['price']:.8f}

5dk Değişim:
%{result['price_change_5m']:.2f}

15dk Değişim:
%{result['price_change_15m']:.2f}

USDT Hacim:
{int(result['volume_usdt'])}

Hacim Artışı:
{result['volume_ratio']:.2f}x

📌 Karar:
Likidite girişi var.
Takibe alınabilir.
Direkt FOMO yapılmaz.
"""

                telegram(msg)

                sent_cache[symbol] = now

                print("PARA GİRİŞİ:", symbol)

                time.sleep(0.2)

            print("Tarama tamamlandı")

            time.sleep(SLEEP_SECONDS)

        except Exception as e:

            print("Genel hata:", e)

            time.sleep(10)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    run()
