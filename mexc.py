import ccxt
import time
import requests
import math

BOT_NAME = "☁️ RENDER KADEMELİ LONG/SHORT BOTU"

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

exchange = ccxt.mexc({"enableRateLimit": True})

LONG_TIMEFRAME = "5m"
SHORT_TIMEFRAME = "15m"
LONG_BIG_REVERSAL="1h"

SLEEP_SECONDS = 60
COOLDOWN = 2 * 60 * 60
MAX_SIGNALS_PER_SCAN = 5

MIN_VOLUME_USDT = 20000

# LONG ORTA AYAR
MIN_VOLUME_RATIO_LONG = 1.8
MIN_LOWER_WICK_LONG = 0.35
LONG_MEDIUM_SCORE = 8
LONG_HIGH_SCORE = 10

# SHORT ORTA AYAR
MIN_VOLUME_RATIO_SHORT = 1.3
MIN_UPPER_WICK_SHORT = 0.40
SHORT_MEDIUM_SCORE = 9
SHORT_HIGH_SCORE = 11

MIN_BODY_RATIO = 0.20
MIN_BODY_RATIO_SHORT = 0.25

MAX_CLOSE_POSITION_SHORT = 0.45
MIN_CLOSE_POSITION_LONG = 0.45

MAX_BB_WIDTH = 0.090

ORDERBOOK_LIMIT = 20
MIN_BID_ASK_RATIO_LONG = 1.10
MAX_BID_ASK_RATIO_SHORT = 0.80
MAX_SPREAD_PERCENT = 0.30

STABLE_BLACKLIST = [
    "USDC/", "FDUSD/", "TUSD/", "USDE/", "DAI/",
    "USDP/", "EUR/", "EURT/", "TRY/"
]

LEVERAGE_BLACKLIST = ["UP/", "DOWN/", "BULL/", "BEAR/"]

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
        return 0, 0, 0, 0

    body_ratio = abs(c - o) / rng
    upper_wick = (h - max(o, c)) / rng
    lower_wick = (min(o, c) - l) / rng
    close_position = (c - l) / rng

    return body_ratio, upper_wick, lower_wick, close_position

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

def get_quality(direction, score):
    if direction == "LONG":
        if score >= LONG_HIGH_SCORE:
            return "YÜKSEK 🔥"
        if score >= LONG_MEDIUM_SCORE:
            return "ORTA 🟠"

    if direction == "SHORT":
        if score >= SHORT_HIGH_SCORE:
            return "YÜKSEK 🔥"
        if score >= SHORT_MEDIUM_SCORE:
            return "ORTA 🟠"

    return None

def analyze(symbol):
    try:
candles_long = exchange.fetch_ohlcv(
    symbol,
    timeframe=LONG_TIMEFRAME,
    limit=40
)

candles_short = exchange.fetch_ohlcv(
    symbol,
    timeframe=SHORT_TIMEFRAME,
    limit=40
)

candles_big_long = exchange.fetch_ohlcv(
    symbol,
    timeframe=LONG_BIG_REVERSAL,
    limit=40
)

        if len(candles_long) < 25 or len(candles_short) < 25:
            return None

        last_long = candles_long[-1]
        prev_long = candles_long[-2]

        o_long, h_long, l_long, c_long, v_long = (
            last_long[1], last_long[2], last_long[3], last_long[4], last_long[5]
        )

        last_short = candles_short[-1]
        prev_short = candles_short[-2]

        o_short, h_short, l_short, c_short, v_short = (
            last_short[1], last_short[2], last_short[3], last_short[4], last_short[5]
        )

        closes_long = [x[4] for x in candles_long]
        volumes_long = [x[5] for x in candles_long]

        closes_short = [x[4] for x in candles_short]
        volumes_short = [x[5] for x in candles_short]

        price_change_5m = ((c_long - prev_long[4]) / prev_long[4]) * 100
        price_change_15m = ((c_short - prev_short[4]) / prev_short[4]) * 100

        avg_volume_long = sum(volumes_long[-21:-1]) / 20
        avg_volume_short = sum(volumes_short[-21:-1]) / 20

        if avg_volume_long == 0 or avg_volume_short == 0:
            return None

        volume_ratio_long = v_long / avg_volume_long
        volume_ratio_short = v_short / avg_volume_short

        volume_usdt_long = v_long * c_long
        volume_usdt_short = v_short * c_short

        bb_upper_long, _, bb_lower_long, bb_width_long = bollinger(closes_long, 20)
        bb_upper_short, _, bb_lower_short, bb_width_short = bollinger(closes_short, 20)

        if bb_upper_long is None or bb_upper_short is None:
            return None

        body_long, upper_long, lower_long, close_pos_long = candle_stats(
            o_long, h_long, l_long, c_long
        )

        body_short, upper_short, lower_short, close_pos_short = candle_stats(
            o_short, h_short, l_short, c_short
        )

        bb_lower_touch = l_long <= bb_lower_long
        bb_upper_touch = h_short >= bb_upper_short

        bb_squeeze_long = bb_width_long <= MAX_BB_WIDTH
        bb_squeeze_short = bb_width_short <= MAX_BB_WIDTH

        book = mini_bookmap(symbol)
        if not book:
            return None

        if book["spread_percent"] > MAX_SPREAD_PERCENT:
            return None

        long_score = 0
        long_reasons = []

        if volume_usdt_long >= MIN_VOLUME_USDT:
            long_score += 1
            long_reasons.append("USDT hacim yeterli")

        if volume_ratio_long >= MIN_VOLUME_RATIO_LONG:
            long_score += 2
            long_reasons.append("para girişi var")

        if lower_long >= MIN_LOWER_WICK_LONG:
            long_score += 3
            long_reasons.append("alt likidasyon iğnesi")

        if body_long >= MIN_BODY_RATIO:
            long_score += 1
            long_reasons.append("dönüş mumu")

        if bb_lower_touch:
            long_score += 2
            long_reasons.append("BB alt bant dönüşü")

        if bb_squeeze_long:
            long_score += 1
            long_reasons.append("BB sıkışma")

        if book["long_book"]:
            long_score += 2
            long_reasons.append("Mini Bookmap alım destekli")

        long_valid = (
            volume_usdt_long >= MIN_VOLUME_USDT
            and volume_ratio_long >= MIN_VOLUME_RATIO_LONG
            and lower_long >= MIN_LOWER_WICK_LONG
            and body_long >= MIN_BODY_RATIO
            and bb_lower_touch
            and close_pos_long >= MIN_CLOSE_POSITION_LONG
            and long_score >= LONG_MEDIUM_SCORE
        )

        short_score = 0
        short_reasons = []

        if volume_usdt_short >= MIN_VOLUME_USDT:
            short_score += 1
            short_reasons.append("USDT hacim yeterli")

        if volume_ratio_short >= MIN_VOLUME_RATIO_SHORT:
            short_score += 2
            short_reasons.append("short hacim desteği var")

        if upper_short >= MIN_UPPER_WICK_SHORT:
            short_score += 3
            short_reasons.append("üst likidasyon iğnesi")

        if body_short >= MIN_BODY_RATIO_SHORT:
            short_score += 1
            short_reasons.append("rejection mumu")

        if bb_upper_touch:
            short_score += 2
            short_reasons.append("BB üst bant reddi")

        if bb_squeeze_short:
            short_score += 1
            short_reasons.append("BB sıkışma sonrası reject")

        if book["short_book"]:
            short_score += 2
            short_reasons.append("Mini Bookmap satış baskılı")

        short_valid = (
            volume_usdt_short >= MIN_VOLUME_USDT
            and volume_ratio_short >= MIN_VOLUME_RATIO_SHORT
            and upper_short >= MIN_UPPER_WICK_SHORT
            and body_short >= MIN_BODY_RATIO_SHORT
            and bb_upper_touch
            and close_pos_short <= MAX_CLOSE_POSITION_SHORT
            and book["short_book"]
            and short_score >= SHORT_MEDIUM_SCORE
        )

        if not long_valid and not short_valid:
            return None

        if long_valid and long_score >= short_score:
            quality = get_quality("LONG", long_score)
            if not quality:
                return None

            return {
                "symbol": symbol,
                "direction": "LONG",
                "quality": quality,
                "price": c_long,
                "score": long_score,
                "price_change_5m": price_change_5m,
                "price_change_15m": price_change_15m,
                "volume_usdt": volume_usdt_long,
                "volume_ratio": volume_ratio_long,
                "body_ratio": body_long,
                "upper_wick": upper_long,
                "lower_wick": lower_long,
                "close_position": close_pos_long,
                "bb_width": bb_width_long,
                "bb_lower_touch": bb_lower_touch,
                "bb_upper_touch": False,
                "bb_squeeze": bb_squeeze_long,
                "book": book,
                "reasons": long_reasons
            }

        quality = get_quality("SHORT", short_score)
        if not quality:
            return None

        return {
            "symbol": symbol,
            "direction": "SHORT",
            "quality": quality,
            "price": c_short,
            "score": short_score,
            "price_change_5m": price_change_5m,
            "price_change_15m": price_change_15m,
            "volume_usdt": volume_usdt_short,
            "volume_ratio": volume_ratio_short,
            "body_ratio": body_short,
            "upper_wick": upper_short,
            "lower_wick": lower_short,
            "close_position": close_pos_short,
            "bb_width": bb_width_short,
            "bb_lower_touch": False,
            "bb_upper_touch": bb_upper_touch,
            "bb_squeeze": bb_squeeze_short,
            "book": book,
            "reasons": short_reasons
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

                cache_key = f"{symbol}"

                if cache_key in sent_cache and now - sent_cache[cache_key] < COOLDOWN:
                    continue

                result = analyze(symbol)

                if not result:
                    continue

                book = result["book"]

                if result["direction"] == "LONG":
                    title = "🟢 MEXC LONG LİKİDASYON"
                    karar = """
Alt likidasyon iğnesi + BB alt bant dönüşü var.

ORTA kaliteyse sadece takip.
YÜKSEK kaliteyse 1m/3m yeşil dönüş onayı beklenir.
Direkt FOMO yapılmaz.
"""
                else:
                    title = "🔴 MEXC SHORT LİKİDASYON"
                    karar = """
15m üst likidasyon iğnesi + BB üst bant reddi var.

ORTA kaliteyse sadece takip.
YÜKSEK kaliteyse 15m rejection onayı beklenir.
Direkt FOMO yapılmaz.
"""

                msg = f"""
{BOT_NAME}

{title}

Kalite:
{result['quality']}

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

📊 MINI BOOKMAP

Bid / Ask:
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

                print(result["quality"], result["direction"], result["symbol"])

                time.sleep(0.25)

            print("Tarama tamamlandı")
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e)
            time.sleep(10)

if __name__ == "__main__":
    run()
