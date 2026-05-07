import ccxt
import time
import requests
import math

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

# =====================
# SIKI MEXC AYARLAR
# =====================
SLEEP_SECONDS = 90

COOLDOWN_PREP = 3 * 60 * 60
COOLDOWN_CONFIRM = 6 * 60 * 60

# 🟡 Hazırlık sinyali
MIN_LAST_VOLUME_USDT_PREP = 20000
PREP_MIN_VOL_RATIO = 1.8
PREP_MAX_PRICE_CHANGE_15M = 1.2
PREP_MIN_RSI = 52
PREP_MAX_RSI = 68
PREP_MAX_BB_WIDTH = 0.035
PREP_MIN_BODY_RATIO = 0.30
PREP_MAX_UPPER_WICK = 0.45

# 🚨 Onay sinyali
MIN_LAST_VOLUME_USDT_CONFIRM = 50000
CONFIRM_MIN_VOL_RATIO = 4.0
CONFIRM_MIN_PRICE_CHANGE_5M = 1.0
CONFIRM_MAX_PRICE_CHANGE_5M = 4.0
CONFIRM_MIN_BODY_RATIO = 0.60
CONFIRM_MAX_UPPER_WICK = 0.25

sent_prep = {}
sent_confirm = {}

def telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)

def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains, losses = [], []

    for i in range(1, period + 1):
        diff = values[-i] - values[-i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

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

    body_ratio = abs(close - open_) / rng
    upper_wick = (high - max(open_, close)) / rng

    return body_ratio, upper_wick

def get_pairs():
    markets = exchange.load_markets()

    pairs = []
    blacklist = ["UP/", "DOWN/", "BULL/", "BEAR/"]

    for symbol in markets:
        if not symbol.endswith("/USDT"):
            continue
        if not markets[symbol].get("active", True):
            continue
        if any(x in symbol for x in blacklist):
            continue

        pairs.append(symbol)

    return pairs

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

        volume_3_rising = (
            volumes[-1] > volumes[-2]
            and volumes[-2] > volumes[-3]
        )

        prep = False
        confirm = False

        # =====================
        # 🟡 ERKEN HAZIRLIK
        # =====================
        if (
            volume_usdt >= MIN_LAST_VOLUME_USDT_PREP
            and volume_ratio >= PREP_MIN_VOL_RATIO
            and 0 < price_change_15m <= PREP_MAX_PRICE_CHANGE_15M
            and PREP_MIN_RSI <= rsi_now <= PREP_MAX_RSI
            and bb_width <= PREP_MAX_BB_WIDTH
            and body_ratio >= PREP_MIN_BODY_RATIO
            and upper_wick <= PREP_MAX_UPPER_WICK
            and volume_3_rising
            and c >= ema9
            and ema9 >= ema21
        ):
            prep = True

        # =====================
        # 🚨 PUMP ONAY
        # =====================
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
            "volume_3_rising": volume_3_rising,
            "prep": prep,
            "confirm": confirm
        }

    except Exception as e:
        print("Analiz hata:", symbol, e)
        return None

def run():
    telegram("🚀 MEXC SIKI ERKEN PUMP SCANNER başladı hocam")

    while True:
        try:
            pairs = get_pairs()
            now = time.time()

            for symbol in pairs:
                result = scan_symbol(symbol)

                if not result:
                    continue

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

3 Mum Hacim Artışı: {'VAR ✅' if result['volume_3_rising'] else 'YOK ❌'}
Mum Gücü: {result['body_ratio']:.2f}
Üst Fitil: {result['upper_wick']:.2f}

📍 Karar:
Erken hazırlık var.
Direkt long değil.
Direnç kırılımı + retest bekle.
"""
                        telegram(msg)
                        sent_prep[symbol] = now
                        time.sleep(0.25)

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
                        time.sleep(0.25)

            print("MEXC tarama bitti")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

if __name__ == "__main__":
    run()
