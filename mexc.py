import ccxt
import time
import requests
import math

BOT_NAME = "☁️ RENDER LONG/SHORT LİKİDASYON BOTU"

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

TIMEFRAME = "5m"
SLEEP_SECONDS = 60
COOLDOWN = 3 * 60 * 60
MAX_SIGNALS_PER_SCAN = 5

MIN_VOLUME_USDT = 25000
MIN_VOLUME_RATIO = 2.5

MIN_WICK_RATIO = 0.35
MIN_BODY_RATIO = 0.20

MIN_PRICE_CHANGE_15M = -6.0
MAX_PRICE_CHANGE_15M = 6.0

MAX_BB_WIDTH = 0.090

ORDERBOOK_LIMIT = 20
MIN_BID_ASK_RATIO_LONG = 1.20
MAX_BID_ASK_RATIO_SHORT = 0.80
MAX_SPREAD_PERCENT = 0.25

STABLE_BLACKLIST = [
    "USDC/", "FDUSD/", "TUSD/", "USDE/", "DAI/",
    "USDP/", "EUR/", "EURT/", "TRY/"
]

LEVERAGE_BLACKLIST = [
    "UP/", "DOWN/", "BULL/", "BEAR/"
]

sent_cache = {}

def telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram hata:", e)

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def bollinger(values, period=20):
    if len(values) < period:
        return None, None, None, None

    mid = sma(values, period)
    if not mid:
        return None, None, None, None

    variance = sum((x - mid) ** 2 for x in values[-period:]) / period
    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std
    width = (upper - lower) / mid

    return upper, mid, lower, width

def candle_stats(o, h, l, c):
    rng = h - l

    if rng == 0:
        return 0, 0, 0, 0, 0

    body_ratio = abs(c - o) / rng
    upper_wick = (h - max(o, c)) / rng
    lower_wick = (min(o, c) - l) / rng

    close_position = (c - l) / rng
    red_candle = c < o
    green_candle = c > o

    return body_ratio, upper_wick, lower_wick, close_position, green_candle if green_candle else red_candle

def get_pairs():
    markets = exchange.load_markets()
    pairs = []

    for symbol in markets:
        if not symbol.endswith("/USDT"):
            continue

        if not markets[symbol].get("active", True):
            continue

        if any(x in symbol for x in LEVERAGE_BLACKLIST):
            continue

        if any(x in symbol for x in STABLE_BLACKLIST):
            continue

        pairs.append(symbol)

    return pairs

def mini_bookmap(symbol):
    try:
        ob = exchange.fetch_order_book(symbol, limit=ORDERBOOK_LIMIT)

        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = bids[0][0]
        best_ask = asks[0][0]

        if best_bid <= 0 or best_ask <= 0:
            return None

        spread_percent = ((best_ask - best_bid) / best_bid) * 100

        bid_usdt = sum(price * amount for price, amount in bids[:ORDERBOOK_LIMIT])
        ask_usdt = sum(price * amount for price, amount in asks[:ORDERBOOK_LIMIT])

        if ask_usdt == 0:
            return None

        bid_ask_ratio = bid_usdt / ask_usdt

        strongest_bid = max(bids[:ORDERBOOK_LIMIT], key=lambda x: x[0] * x[1])
        strongest_ask = max(asks[:ORDERBOOK_LIMIT], key=lambda x: x[0] * x[1])

        return {
            "spread_percent": spread_percent,
            "bid_usdt": bid_usdt,
            "ask_usdt": ask_usdt,
            "bid_ask_ratio": bid_ask_ratio,
            "strongest_bid_price": strongest_bid[0],
            "strongest_bid_usdt": strongest_bid[0] * strongest_bid[1],
            "strongest_ask_price": strongest_ask[0],
            "strongest_ask_usdt": strongest_ask[0] * strongest_ask[1],
            "long_book": bid_ask_ratio >= MIN_BID_ASK_RATIO_LONG,
            "short_book": bid_ask_ratio <= MAX_BID_ASK_RATIO_SHORT
        }

    except Exception as e:
        print("Bookmap hata:", symbol, e)
        return None

def analyze(symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=40)

        if len(candles) < 25:
            return None

        last = candles[-1]
        prev = candles[-2]

        o, h, l, c, v = last[1], last[2], last[3], last[4], last[5]

        closes = [x[4] for x in candles]
        volumes = [x[5] for x in candles]

        price_change_5m = ((c - prev[4]) / prev[4]) * 100
        price_change_15m = ((c - candles[-4][4]) / candles[-4][4]) * 100

        avg_volume = sum(volumes[-21:-1]) / 20
        if avg_volume == 0:
            return None

        volume_ratio = v / avg_volume
        volume_usdt = v * c

        bb_upper, bb_mid, bb_lower, bb_width = bollinger(closes, 20)
        if bb_upper is None:
            return None

        body_ratio, upper_wick, lower_wick, close_position, candle_dir = candle_stats(o, h, l, c)

        bb_lower_touch = l <= bb_lower
        bb_upper_touch = h >= bb_upper
        bb_squeeze = bb_width <= MAX_BB_WIDTH

        book = mini_bookmap(symbol)
        if not book:
            return None

        common_valid = (
            volume_usdt >= MIN_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and body_ratio >= MIN_BODY_RATIO
            and MIN_PRICE_CHANGE_15M <= price_change_15m <= MAX_PRICE_CHANGE_15M
            and book["spread_percent"] <= MAX_SPREAD_PERCENT
        )

        long_score = 0
        long_reasons = []

        if volume_usdt >= MIN_VOLUME_USDT:
            long_score += 1
            long_reasons.append("USDT hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            long_score += 2
            long_reasons.append("para girişi / hacim spike")

        if lower_wick >= MIN_WICK_RATIO:
            long_score += 3
            long_reasons.append("alt likidasyon iğnesi")

        if body_ratio >= MIN_BODY_RATIO:
            long_score += 1
            long_reasons.append("dönüş mumu toparlamış")

        if bb_lower_touch:
            long_score += 2
            long_reasons.append("BB alt banttan dönüş")

        if bb_squeeze:
            long_score += 1
            long_reasons.append("BB sıkışma")

        if book["long_book"]:
            long_score += 2
            long_reasons.append("Mini Bookmap alım destekli")

        long_valid = (
            common_valid
            and long_score >= 8
            and lower_wick >= MIN_WICK_RATIO
            and bb_lower_touch
            and close_position >= 0.45
        )

        short_score = 0
        short_reasons = []

        if volume_usdt >= MIN_VOLUME_USDT:
            short_score += 1
            short_reasons.append("USDT hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            short_score += 2
            short_reasons.append("para girişi / hacim spike")

        if upper_wick >= MIN_WICK_RATIO:
            short_score += 3
            short_reasons.append("üst likidasyon iğnesi")

        if body_ratio >= MIN_BODY_RATIO:
            short_score += 1
            short_reasons.append("red/rejection mumu oluşmuş")

        if bb_upper_touch:
            short_score += 2
            short_reasons.append("BB üst bant reddi")

        if bb_squeeze:
            short_score += 1
            short_reasons.append("BB sıkışma sonrası reject")

        if book["short_book"]:
            short_score += 2
            short_reasons.append("Mini Bookmap satış baskılı")

        short_valid = (
            common_valid
            and short_score >= 8
            and upper_wick >= MIN_WICK_RATIO
            and bb_upper_touch
            and close_position <= 0.55
        )

        if not long_valid and not short_valid:
            return None

        if long_valid and long_score >= short_score:
            direction = "LONG"
            score = long_score
            reasons = long_reasons
        else:
            direction = "SHORT"
            score = short_score
            reasons = short_reasons

        return {
            "symbol": symbol,
            "price": c,
            "direction": direction,
            "score": score,
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "volume_usdt": volume_usdt,
            "volume_ratio": volume_ratio,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "close_position": close_position,
            "bb_width": bb_width,
            "bb_lower_touch": bb_lower_touch,
            "bb_upper_touch": bb_upper_touch,
            "bb_squeeze": bb_squeeze,
            "book": book,
            "reasons": reasons
        }

    except Exception as e:
        print("Analiz hata:", symbol, e)
        return None

def run():
    telegram(f"{BOT_NAME} aktif edildi hocam 🚀")

    while True:
        try:
            pairs = get_pairs()
            now = time.time()
            signal_count = 0

            for symbol in pairs:
                if signal_count >= MAX_SIGNALS_PER_SCAN:
                    break

                cache_key = symbol

                if cache_key in sent_cache and now - sent_cache[cache_key] < COOLDOWN:
                    continue

                result = analyze(symbol)

                if not result:
                    continue

                book = result["book"]

                if result["direction"] == "LONG":
                    title = "🟢 MEXC LONG LİKİDASYON TOPLAMA"
                    karar = """
Aşağı likidasyon iğnesi + para girişi + BB alt bant dönüşü var.
Mini Bookmap alım tarafını kontrol etti.

Direkt FOMO yapılmaz.
1m/3m yeşil dönüş ve direnç kırılımı beklenir.
"""
                else:
                    title = "🔴 MEXC SHORT LİKİDASYON REDDİ"
                    karar = """
Yukarı likidasyon iğnesi + hacim spike + BB üst bant reddi var.
Mini Bookmap satış baskısını kontrol etti.

Direkt FOMO yapılmaz.
1m/3m kırmızı onay ve destek kırılımı beklenir.
"""

                msg = f"""
{BOT_NAME}

{title}

Coin:
{result['symbol']}

Fiyat:
{result['price']:.8f}

Yön:
{result['direction']}

Skor:
{result['score']}/13

5dk Değişim:
%{result['price_change_5m']:.2f}

15dk Değişim:
%{result['price_change_15m']:.2f}

USDT Hacim:
{int(result['volume_usdt'])}

Hacim Artışı:
{result['volume_ratio']:.2f}x

Alt Fitil:
{result['lower_wick']:.2f}

Üst Fitil:
{result['upper_wick']:.2f}

Mum Gücü:
{result['body_ratio']:.2f}

Kapanış Konumu:
{result['close_position']:.2f}

BB Width:
{result['bb_width']:.4f}

BB Alt Bant:
{'TEMAS ✅' if result['bb_lower_touch'] else 'YOK ❌'}

BB Üst Bant:
{'TEMAS ✅' if result['bb_upper_touch'] else 'YOK ❌'}

BB Sıkışma:
{'VAR ✅' if result['bb_squeeze'] else 'YOK ❌'}

📊 MINI BOOKMAP:
Bid / Ask Gücü:
{book['bid_ask_ratio']:.2f}x

Spread:
%{book['spread_percent']:.4f}

Bid Toplam:
{int(book['bid_usdt'])} USDT

Ask Toplam:
{int(book['ask_usdt'])} USDT

En Güçlü Bid:
{book['strongest_bid_price']:.8f}
({int(book['strongest_bid_usdt'])} USDT)

En Güçlü Ask:
{book['strongest_ask_price']:.8f}
({int(book['strongest_ask_usdt'])} USDT)

Order Book:
{'ALIM DESTEKLİ ✅' if book['long_book'] else 'SATIŞ BASKILI ✅' if book['short_book'] else 'NÖTR ⚪'}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
{karar}
"""

                telegram(msg)

                sent_cache[cache_key] = now
                signal_count += 1

                print(result["direction"], result["symbol"])
                time.sleep(0.25)

            print("Tarama tamamlandı")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

if __name__ == "__main__":
    run()
