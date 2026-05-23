import ccxt
import time
import requests
import math

BOT_NAME = "☁️ RENDER LİKİDASYON + BOOKMAP BOTU"

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({
    "enableRateLimit": True
})

TIMEFRAME = "5m"
SLEEP_SECONDS = 60
COOLDOWN = 3 * 60 * 60
MAX_SIGNALS_PER_SCAN = 5

MIN_VOLUME_USDT = 25000
MIN_VOLUME_RATIO = 2.5

MIN_LOWER_WICK = 0.35
MIN_BODY_RATIO = 0.20

MIN_PRICE_CHANGE_15M = -5.0
MAX_PRICE_CHANGE_15M = 2.5

MAX_BB_WIDTH = 0.080

ORDERBOOK_LIMIT = 20
MIN_BID_ASK_RATIO = 1.20
MAX_SPREAD_PERCENT = 0.25

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
    if mid == 0:
        return None, None, None, None

    variance = sum((x - mid) ** 2 for x in values[-period:]) / period
    std = math.sqrt(variance)

    upper = mid + 2 * std
    lower = mid - 2 * std
    width = (upper - lower) / mid

    return upper, mid, lower, width

def candle_stats(open_, high, low, close):
    rng = high - low

    if rng == 0:
        return 0, 0, 0

    body_ratio = abs(close - open_) / rng
    upper_wick = (high - max(open_, close)) / rng
    lower_wick = (min(open_, close) - low) / rng

    return body_ratio, upper_wick, lower_wick

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

def mini_bookmap(symbol):
    try:
        orderbook = exchange.fetch_order_book(symbol, limit=ORDERBOOK_LIMIT)

        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

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

        strongest_bid_price = strongest_bid[0]
        strongest_bid_usdt = strongest_bid[0] * strongest_bid[1]

        strongest_ask_price = strongest_ask[0]
        strongest_ask_usdt = strongest_ask[0] * strongest_ask[1]

        book_support = (
            bid_ask_ratio >= MIN_BID_ASK_RATIO
            and spread_percent <= MAX_SPREAD_PERCENT
        )

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_percent": spread_percent,
            "bid_usdt": bid_usdt,
            "ask_usdt": ask_usdt,
            "bid_ask_ratio": bid_ask_ratio,
            "strongest_bid_price": strongest_bid_price,
            "strongest_bid_usdt": strongest_bid_usdt,
            "strongest_ask_price": strongest_ask_price,
            "strongest_ask_usdt": strongest_ask_usdt,
            "book_support": book_support
        }

    except Exception as e:
        print("Bookmap hata:", symbol, e)
        return None

def analyze(symbol):
    try:
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=40
        )

        if len(candles) < 25:
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

        bb_upper, bb_mid, bb_lower, bb_width = bollinger(closes, 20)

        if bb_lower is None:
            return None

        bb_touch = l <= bb_lower
        bb_squeeze = bb_width <= MAX_BB_WIDTH

        body_ratio, upper_wick, lower_wick = candle_stats(o, h, l, c)

        book = mini_bookmap(symbol)

        if not book:
            return None

        score = 0
        reasons = []

        if volume_usdt >= MIN_VOLUME_USDT:
            score += 1
            reasons.append("USDT hacim yeterli")

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 2
            reasons.append("para girişi / hacim spike")

        if lower_wick >= MIN_LOWER_WICK:
            score += 3
            reasons.append("alt likidasyon iğnesi")

        if body_ratio >= MIN_BODY_RATIO:
            score += 1
            reasons.append("dönüş mumu toparlamış")

        if bb_touch:
            score += 2
            reasons.append("BB alt banttan dönüş")

        if bb_squeeze:
            score += 1
            reasons.append("BB sıkışma var")

        if book["book_support"]:
            score += 2
            reasons.append("Mini Bookmap alım destekli")

        if MIN_PRICE_CHANGE_15M <= price_change_15m <= MAX_PRICE_CHANGE_15M:
            score += 1
            reasons.append("fiyat pump sonrası değil")

        valid = (
            score >= 8
            and volume_usdt >= MIN_VOLUME_USDT
            and volume_ratio >= MIN_VOLUME_RATIO
            and lower_wick >= MIN_LOWER_WICK
            and body_ratio >= MIN_BODY_RATIO
            and bb_touch
            and MIN_PRICE_CHANGE_15M <= price_change_15m <= MAX_PRICE_CHANGE_15M
            and book["spread_percent"] <= MAX_SPREAD_PERCENT
        )

        if not valid:
            return None

        return {
            "symbol": symbol,
            "price": c,
            "score": score,
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "volume_usdt": volume_usdt,
            "volume_ratio": volume_ratio,
            "body_ratio": body_ratio,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "bb_width": bb_width,
            "bb_touch": bb_touch,
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

                if symbol in sent_cache and now - sent_cache[symbol] < COOLDOWN:
                    continue

                result = analyze(symbol)

                if not result:
                    continue

                book = result["book"]

                msg = f"""
{BOT_NAME}

🐋 MEXC LİKİDASYON + PARA GİRİŞİ

Coin:
{result['symbol']}

Fiyat:
{result['price']:.8f}

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

BB Width:
{result['bb_width']:.4f}

BB Alt Bant:
{'TEMAS ✅' if result['bb_touch'] else 'YOK ❌'}

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
{'ALIM DESTEKLİ ✅' if book['book_support'] else 'ZAYIF ❌'}

📌 Sebep:
{", ".join(result['reasons'])}

📍 Karar:
Likidasyon iğnesi + para girişi + BB dönüşü var.
Mini Bookmap alım tarafını kontrol etti.

Direkt FOMO yapılmaz.
1m/3m dönüş onayı beklenir.
"""

                telegram(msg)
                sent_cache[symbol] = now
                signal_count += 1

                print("LİKİDASYON + BOOKMAP:", symbol)
                time.sleep(0.25)

            print("Tarama tamamlandı")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

if __name__ == "__main__":
    run()
