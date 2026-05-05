import ccxt
import time
import requests
import math

TELEGRAM_TOKEN =  "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

# =========================
# AYARLAR
# =========================
SLEEP_SECONDS = 60
COOLDOWN_PREP = 60 * 60          # hazırlık sinyali 1 saat
COOLDOWN_CONFIRM = 3 * 60 * 60   # onay sinyali 3 saat

# Likidite filtresi
MIN_LAST_VOLUME_USDT_PREP = 8000
MIN_LAST_VOLUME_USDT_CONFIRM = 20000

# Hazırlık modu: pump başlamadan önce
PREP_MIN_VOL_RATIO = 1.25
PREP_MAX_PRICE_CHANGE_15M = 2.0
PREP_MIN_RSI = 48
PREP_MAX_RSI = 72
PREP_MAX_BB_WIDTH = 0.060

# Onay modu: pump başladıktan sonra
CONFIRM_MIN_VOL_RATIO = 2.8
CONFIRM_MIN_PRICE_CHANGE_5M = 0.6
CONFIRM_MAX_PRICE_CHANGE_5M = 5.0
CONFIRM_MIN_BODY_RATIO = 0.45
CONFIRM_MAX_UPPER_WICK = 0.45

sent_prep = {}
sent_confirm = {}

# =========================
# TELEGRAM
# =========================
def telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)

# =========================
# İNDİKATÖRLER
# =========================
def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = values[-i] - values[-i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def bollinger_width(values, period=20):
    if len(values) < period:
        return None

    mid = sma(values, period)
    variance = sum((x - mid) ** 2 for x in values[-period:]) / period
    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std

    if mid == 0:
        return None

    return (upper - lower) / mid

def candle_power(open_, high, low, close):
    rng = high - low
    if rng == 0:
        return 0, 1

    body = abs(close - open_) / rng
    upper_wick = (high - max(open_, close)) / rng

    return body, upper_wick

# =========================
# MARKETLER
# =========================
def get_pairs():
    markets = exchange.load_markets()
    return [
        symbol for symbol in markets
        if symbol.endswith("/USDT") and markets[symbol].get("active", True)
    ]

# =========================
# TARAMA
# =========================
def scan_symbol(symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=60)

        if len(candles) < 30:
            return None

        last = candles[-1]
        prev = candles[-2]

        o = last[1]
        h = last[2]
        l = last[3]
        c = last[4]
        v = last[5]

        closes = [x[4] for x in candles]
        volumes = [x[5] for x in candles]

        price_change_5m = ((c - prev[4]) / prev[4]) * 100
        price_change_15m = ((c - candles[-4][4]) / candles[-4][4]) * 100

        avg_volume = sum(volumes[-21:-1]) / 20
        if avg_volume == 0:
            return None

        volume_ratio = v / avg_volume
        volume_usdt = v * c

        rsi_now = rsi(closes, 14)
        bb_width = bollinger_width(closes, 20)
        body_ratio, upper_wick = candle_power(o, h, l, c)

        ema9 = sma(closes, 9)
        ema21 = sma(closes, 21)

        if rsi_now is None or bb_width is None or ema9 is None or ema21 is None:
            return None

        # =========================
        # 🟡 ERKEN HAZIRLIK MODU
        # =========================
        prep = False

        if (
            volume_usdt >= MIN_LAST_VOLUME_USDT_PREP
            and volume_ratio >= PREP_MIN_VOL_RATIO
            and price_change_15m <= PREP_MAX_PRICE_CHANGE_15M
            and PREP_MIN_RSI <= rsi_now <= PREP_MAX_RSI
            and bb_width <= PREP_MAX_BB_WIDTH
            and c >= ema9
            and ema9 >= ema21
        ):
            prep = True

        # =========================
        # 🚨 PUMP ONAY MODU
        # =========================
        confirm = False

        if (
            volume_usdt >= MIN_LAST_VOLUME_USDT_CONFIRM
            and volume_ratio >= CONFIRM_MIN_VOL_RATIO
            and CONFIRM_MIN_PRICE_CHANGE_5M <= price_change_5m <= CONFIRM_MAX_PRICE_CHANGE_5M
            and body_ratio >= CONFIRM_MIN_BODY_RATIO
            and upper_wick <= CONFIRM_MAX_UPPER_WICK
        ):
            confirm = True

        return {
            "symbol": symbol,
            "price": c,
            "volume_usdt": volume_usdt,
            "volume_ratio": volume_ratio,
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "rsi": rsi_now,
            "bb_width": bb_width,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "prep": prep,
            "confirm": confirm
        }

    except Exception:
        return None

# =========================
# ÇALIŞTIR
# =========================
def run():
    telegram("🚀 MEXC ERKEN PUMP SCANNER başladı hocam")

    while True:
        try:
            pairs = get_pairs()
            now = time.time()

            for symbol in pairs:
                result = scan_symbol(symbol)
                if not result:
                    continue

                # 🟡 HAZIRLIK SİNYALİ
                if result["prep"]:
                    if symbol not in sent_prep or now - sent_prep[symbol] > COOLDOWN_PREP:
                        msg = f"""
🟡 MEXC PUMP HAZIRLIĞI

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

15dk Değişim: %{result['price_change_15m']:.2f}
Hacim: {int(result['volume_usdt'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

RSI: {result['rsi']:.2f}
BB Genişlik: {result['bb_width']:.4f}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

📍 Karar:
Pump başlamadan önce hazırlık var.
Direkt long değil, direnç kırılımı + retest bekle.
"""
                        telegram(msg)
                        sent_prep[symbol] = now
                        time.sleep(0.2)

                # 🚨 ONAY SİNYALİ
                if result["confirm"]:
                    if symbol not in sent_confirm or now - sent_confirm[symbol] > COOLDOWN_CONFIRM:
                        msg = f"""
🚨 MEXC PARA GİRİŞİ / ONAY

Coin: {result['symbol']}
Fiyat: {result['price']:.6f}

5dk Değişim: %{result['price_change_5m']:.2f}
15dk Değişim: %{result['price_change_15m']:.2f}

Hacim: {int(result['volume_usdt'])} USDT
Hacim Artışı: {result['volume_ratio']:.2f}x

RSI: {result['rsi']:.2f}
BB Genişlik: {result['bb_width']:.4f}

Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

⚠️ Kontrol:
- Geç kaldı mı?
- Direnç üstünde kapanış var mı?
- Retest verdi mi?
"""
                        telegram(msg)
                        sent_confirm[symbol] = now
                        time.sleep(0.2)

            print("MEXC tarama bitti")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

if __name__ == "__main__":
    run()
