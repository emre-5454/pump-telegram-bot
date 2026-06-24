# Binance Futures SAFE ENTRY DECISION BOT V15
# Binance MEXC kopyasi degil: Money Acceleration + Safe Entry + Elite AL + FOMO Block mantigi.
# Ortam degiskenleri: TELEGRAM_TOKEN, CHAT_ID, ELITE_CHAT_ID

from flask import Flask
import threading
import time
import os
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8937020446:AAEmdROw4hfDYArdz4eJ47oGHAT_9u4HhIM"
CHAT_ID = "7553607277"

ELITE_CHAT_ID = os.getenv("ELITE_CHAT_ID") or "-1003961962823"

BOT_NAME = "BINANCE SAFE ENTRY DECISION BOT V22"

MAX_SYMBOLS = 120
SLEEP_SECONDS = 120

COOLDOWN_EARLY = 180 * 60
EARLY_MAX_PER_SYMBOL_PER_DAY = 1
COOLDOWN_SAFE = 90 * 60
COOLDOWN_DIP = 120 * 60
COOLDOWN_SWEEP_WATCH = 120 * 60
COOLDOWN_FAST_LIQUIDITY_SWEEP = 90 * 60
COOLDOWN_MONEY_CONTINUE = 120 * 60
COOLDOWN_MOMENTUM_CONTINUE = 150 * 60
COOLDOWN_TREND_BUILDUP = 150 * 60
COOLDOWN_HISTORY_BUILDUP = 150 * 60
COOLDOWN_PRE_ROCKET_SQUEEZE = 90 * 60
MONEY_STATE_EXPIRE_SECONDS = 120 * 60

# MEXC V18'den tasinan hafiza katmani
RADAR_HISTORY_EXPIRE_SECONDS = 4 * 60 * 60
RADAR_HISTORY_DEDUP_SECONDS = 25 * 60
RADAR_HISTORY_WEIGHTS = {
    "EARLY": 4,
    "SAFE": 5,
    "MONEY": 5,
    "MONEY_ACCEL": 6,
    "MOMENTUM": 2,
    "DIP": 4,
    "SWEEP": 5,
    "FAST_LIQUIDITY_SWEEP": 6,
    "TREND_BUILDUP": 7,
    "HISTORY_BUILDUP": 8,
    "PRE_ROCKET_SQUEEZE": 8,
}

MONEY_MEMORY_EXPIRE_SECONDS = 60 * 60
MONEY_MEMORY_MIN_EVENT_USDT = 15_000
MONEY_MEMORY_MIN_EVENT_MARKET = 0.02
MONEY_MEMORY_MIN_EVENT_POWER = 1.15
MONEY_MEMORY_MIN_TOTAL_USDT = 250_000
MONEY_MEMORY_MIN_WAVES = 3
MONEY_MEMORY_MIN_MARKET_60M = 0.25
MONEY_MEMORY_MIN_15M_USDT = 30_000
MONEY_MEMORY_MIN_30M_USDT = 80_000

# V15 BLESS / LUMIA / BTW FIX:
# Ana kanal tekrarlarini, Memory Re-Entry ve Second Wave yapisini Elite puanina cevirir.
MAIN_SIGNAL_MEMORY_EXPIRE_SECONDS = 2 * 60 * 60
MAIN_SIGNAL_DEDUP_SECONDS = 10 * 60
MAIN_SIGNAL_BONUS_60M_3 = 8
MAIN_SIGNAL_BONUS_120M_5 = 12
MAIN_SIGNAL_BONUS_120M_8 = 18
MEMORY_REENTRY_MIN_HISTORY = 24
MEMORY_REENTRY_MIN_MONEY = 1.80
MEMORY_REENTRY_MIN_POWER = 3.00
SECOND_WAVE_MIN_15M_USDT = 30_000
SECOND_WAVE_MIN_30M_USDT = 80_000
ELITE_REENTRY_COOLDOWN = 90 * 60

# V16 STO/BEL/LUMIA FIX: Ana kanalda tam yerinde görünen squeeze patlamaları
# tek radar diye Elite kapısından dönmesin. Henüz fiyat kaçmadan gelen
# sıkışma kırılımı + para/hacim + OBV/MACD birleşimini Elite’e zorlar.
PRE_ROCKET_MIN_MONEY = 2.0
PRE_ROCKET_MIN_VOL_RATIO = 2.2
PRE_ROCKET_MIN_POWER = 6.0
PRE_ROCKET_MAX_RSI = 78
PRE_ROCKET_MAX_15M_GAIN = 7.0
PRE_ROCKET_MAX_30M_GAIN = 13.0
PRE_ROCKET_ELITE_BONUS = 18

# V17 UB / SKYAI FIX:
# Ana kanalda guclenmeye devam eden coinler Elite'e terfi edebilsin.
# Ozellikle MOMENTUM CONTINUE ve HISTORY_BUILDUP icin canli para 0 gorunse bile
# hafiza para/momentum gucu dikkate alinir.
RELOAD_MIN_MONEY = 3.0
RELOAD_MIN_POWER = 12.0
RELOAD_MIN_MARKET = 0.70
REPEAT_FORCE_MIN_120M = 5
REPEAT_FORCE_MIN_WAVES = 3
REPEAT_FORCE_MIN_60M_USDT = 1_000_000
REPEAT_FORCE_MIN_MARKET_60M = 1.0
HISTORY_FORCE_MIN_POINTS = 16
HISTORY_FORCE_MIN_WAVES = 3
HISTORY_FORCE_MIN_60M_USDT = 750_000
V17_RELOAD_ELITE_BONUS = 20

# V18 BLESS / COHR FIX:
# Binance radarlari coinleri yakaliyor ama Elite terfi kapisi fazla sert kaliyordu.
# Momentum + MoneyAccel reload ve History/Memory/Second Wave yapilari Elite puanina daha guclu yansitilir.
V18_HISTORY_MEMORY_BONUS = 18
V18_MOMENTUM_RELOAD_BONUS = 28
V18_MAIN_REPEAT_BONUS = 10

# V19 DESTEK / DIRENC FILTRESI:
# Para + hacim guclu olsa bile fiyat direkt dirence carparken Elite AL vermesin.
# Direnc kirildiysa veya destek ustunde saglikliysa Elite puanina bonus verir.
SR_LOOKBACK_15M = 64
SR_LOOKBACK_1H = 48
SR_TOO_CLOSE_BLOCK_PCT = 0.80
SR_CLOSE_PENALTY_PCT = 1.50
SR_NEAR_PENALTY_PCT = 2.50
SR_BREAKOUT_BUFFER_PCT = 0.25
SR_SUPPORT_NEAR_BONUS_PCT = 2.50
SR_SUPPORT_OK_MAX_PCT = 5.00
SR_STRONG_EXCEPTION_MARKET = 3.00
SR_STRONG_EXCEPTION_POWER = 20.00
SR_STRONG_EXCEPTION_MONEY = 5.00

# V21 GEC YUKSELIS / TEPE SONRASI ELITE KORUMASI:
# SYN tipi: coin son 6 saatte zaten %15-20 gitmis, dipten %20+ uzaklasmis
# ve tepeden geri donerken TREND_BUILDUP tek radar olarak Elite AL vermesin.
LATE_RISE_MAX_6H_FOR_SINGLE_RADAR = 15.0
LATE_RISE_MAX_DIST_FROM_LOW = 22.0
LATE_RISE_PULLBACK_FROM_HIGH_BLOCK = 8.0
LATE_RISE_HARD_6H = 18.0
LATE_RISE_HARD_DIST = 25.0
LATE_RISE_SCORE_PENALTY = 35

MIN_EARLY_RS = 74
MIN_SAFE_CONFIDENCE = 72
MAX_RISK_PCT = 4.5

sent_early = {}
early_daily_counter = {}
sent_safe = {}
sent_dip = {}
sent_sweep_watch = {}
sent_fast_liquidity_sweep = {}
sent_money_continue = {}
sent_momentum_continue = {}
sent_trend_buildup = {}
sent_history_buildup = {}
sent_pre_rocket_squeeze = {}
money_state = {}
radar_history = {}
money_memory = {}
main_signal_memory = {}

# V8 OI / Open Interest hafizasi
# Fiyat yukari giderken OI artiyorsa yeni long destegi,
# fiyat yukari giderken OI dusuyorsa short kapama rallisi olarak yorumlanir.
OI_CACHE_SECONDS = 90
oi_cache = {}

# V11 Taker Buy/Sell Flow / Net Delta
# Binance Futures takerlongshortRatio verisi ile agresif alici-satici baskisini olcer.
TAKER_FLOW_CACHE_SECONDS = 90
taker_flow_cache = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {
        "defaultType": "future",
        "adjustForTimeDifference": True
    }
})


def send_telegram(msg, chat_id=None):
    target_chat_id = chat_id or CHAT_ID

    if not TELEGRAM_TOKEN or not target_chat_id:
        print(msg, flush=True)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": target_chat_id, "text": msg},
            timeout=15
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)

def can_send(cache, key, cooldown):
    now = time.time()
    if key in cache and now - cache[key] < cooldown:
        return False
    cache[key] = now
    return True


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def indicators(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std()
    df["bb_middle"] = basis
    df["bb_upper"] = basis + dev * 2
    df["bb_lower"] = basis - dev * 2
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / basis.replace(0, np.nan)

    candle_range = (high - low).replace(0, np.nan)
    df["body_ratio"] = (close - df["open"]).abs() / candle_range
    df["upper_wick"] = (
        high - pd.concat([df["open"], close], axis=1).max(axis=1)
    ) / candle_range
    df["lower_wick"] = (
        pd.concat([df["open"], close], axis=1).min(axis=1) - low
    ) / candle_range

    df["recovery_ratio"] = (close - low) / candle_range

    df["obv"] = np.where(
        close > close.shift(1),
        volume,
        np.where(close < close.shift(1), -volume, 0)
    ).cumsum()

    return df.dropna().copy()


def fetch_df(symbol, timeframe, limit=120):
    for _ in range(3):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data or len(data) < 40:
                return None

            df = pd.DataFrame(
                data,
                columns=["time", "open", "high", "low", "close", "volume"]
            )
            return indicators(df)

        except Exception as e:
            print("Fetch hata:", symbol, timeframe, e, flush=True)
            time.sleep(1.2)

    return None


def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0

        if -0.001 <= rate <= 0.0015:
            return {"ok": True, "rate": rate, "status": "NORMAL"}

        if rate > 0.0015:
            return {"ok": False, "rate": rate, "status": "LONG KALABALIK"}

        return {"ok": True, "rate": rate, "status": "SHORT BASKI"}

    except Exception:
        return {"ok": True, "rate": 0, "status": "VERI YOK"}



def binance_symbol_id(symbol):
    """CCXT sembolunu Binance futures API sembolune cevirir. BTC/USDT:USDT -> BTCUSDT"""
    try:
        return symbol.split('/')[0].replace(':USDT', '') + 'USDT'
    except Exception:
        return str(symbol).replace('/', '').replace(':USDT', '')


def fetch_oi_change(symbol, period="15m", limit=6):
    """Binance Futures openInterestHist verisinden yuzdesel OI degisimi hesaplar."""
    cache_key = f"{symbol}_{period}_{limit}"
    now = time.time()
    cached = oi_cache.get(cache_key)
    if cached and now - cached.get("time", 0) < OI_CACHE_SECONDS:
        return cached.get("data")

    try:
        r = requests.get(
            "https://fapi.binance.com/futures/data/openInterestHist",
            params={"symbol": binance_symbol_id(symbol), "period": period, "limit": limit},
            timeout=10,
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            out = {"ok": False, "change_pct": 0.0, "first_oi": 0.0, "last_oi": 0.0}
        else:
            first = float(data[0].get("sumOpenInterest", 0) or 0)
            last = float(data[-1].get("sumOpenInterest", 0) or 0)
            change = ((last - first) / first * 100) if first > 0 else 0.0
            out = {"ok": True, "change_pct": change, "first_oi": first, "last_oi": last}
    except Exception as e:
        print("OI veri hata:", symbol, period, e, flush=True)
        out = {"ok": False, "change_pct": 0.0, "first_oi": 0.0, "last_oi": 0.0}

    oi_cache[cache_key] = {"time": now, "data": out}
    return out


def get_oi_context(symbol, price_gain_hint=0.0):
    """15m ve 1h OI degisiminden hareketin long mu short kapama mi oldugunu yorumlar."""
    oi15 = fetch_oi_change(symbol, "15m", 6)
    oi1h = fetch_oi_change(symbol, "1h", 6)
    oi15_pct = oi15.get("change_pct", 0.0)
    oi1h_pct = oi1h.get("change_pct", 0.0)

    long_supported = (oi15_pct >= 2.0 or oi1h_pct >= 4.0)
    strong_long_supported = (oi15_pct >= 5.0 or oi1h_pct >= 8.0)
    short_cover = (price_gain_hint >= 0.4 and oi15_pct <= -1.5 and oi1h_pct <= 0.5)
    oi_weak = (oi15_pct < 0 and oi1h_pct < 1.0)

    if strong_long_supported:
        status = "GUCLU LONG DESTEKLI"
    elif long_supported:
        status = "LONG DESTEKLI"
    elif short_cover:
        status = "SHORT KAPAMA RALLISI"
    elif oi_weak:
        status = "OI ZAYIF"
    else:
        status = "OI NOTR"

    return {
        "oi_ok": bool(oi15.get("ok") or oi1h.get("ok")),
        "oi_15m_pct": oi15_pct,
        "oi_1h_pct": oi1h_pct,
        "oi_status": status,
        "oi_long_supported": long_supported,
        "oi_strong_long_supported": strong_long_supported,
        "oi_short_cover": short_cover,
        "oi_weak": oi_weak,
    }


def attach_oi_context(d, oi_context):
    if d and oi_context:
        d.update(oi_context)
    return d


def fetch_taker_flow(symbol, period="15m", limit=4):
    """Binance Futures Taker Buy/Sell Volume verisinden long/short akisi ve net delta hesaplar."""
    cache_key = f"{symbol}_{period}_{limit}"
    now = time.time()
    cached = taker_flow_cache.get(cache_key)
    if cached and now - cached.get("time", 0) < TAKER_FLOW_CACHE_SECONDS:
        return cached.get("data")

    try:
        r = requests.get(
            "https://fapi.binance.com/futures/data/takerlongshortRatio",
            params={"symbol": binance_symbol_id(symbol), "period": period, "limit": limit},
            timeout=10,
        )
        data = r.json()
        if not isinstance(data, list) or not data:
            out = {
                "ok": False,
                "long_flow_usdt": 0.0,
                "short_flow_usdt": 0.0,
                "net_delta_usdt": 0.0,
                "delta_ratio": 0.0,
                "buy_ratio_pct": 0.0,
                "sell_ratio_pct": 0.0,
                "status": "DELTA VERI YOK",
            }
        else:
            buy_vol = 0.0
            sell_vol = 0.0
            for x in data:
                # Endpoint bazi cevaplarda buyVol/sellVol, bazi dokumanlarda takerBuyVol/takerSellVol seklinde gelebilir.
                buy_vol += float(x.get("buyVol", x.get("takerBuyVol", 0)) or 0)
                sell_vol += float(x.get("sellVol", x.get("takerSellVol", 0)) or 0)

            # buyVol/sellVol coin miktari gibi gelir; USDT karsiligina cevirmek icin son fiyati kullan.
            ticker = exchange.fetch_ticker(symbol)
            last_price = float(ticker.get("last") or ticker.get("close") or 0)
            long_flow = buy_vol * last_price
            short_flow = sell_vol * last_price
            total = long_flow + short_flow
            net_delta = long_flow - short_flow
            delta_ratio = (net_delta / total * 100) if total > 0 else 0.0
            buy_ratio = (long_flow / total * 100) if total > 0 else 0.0
            sell_ratio = (short_flow / total * 100) if total > 0 else 0.0

            if delta_ratio >= 18:
                status = "GUCLU ALICI BASKIN"
            elif delta_ratio >= 8:
                status = "ALICI BASKIN"
            elif delta_ratio <= -18:
                status = "GUCLU SATICI BASKIN"
            elif delta_ratio <= -8:
                status = "SATICI BASKIN"
            else:
                status = "DELTA NOTR"

            out = {
                "ok": True,
                "long_flow_usdt": long_flow,
                "short_flow_usdt": short_flow,
                "net_delta_usdt": net_delta,
                "delta_ratio": delta_ratio,
                "buy_ratio_pct": buy_ratio,
                "sell_ratio_pct": sell_ratio,
                "status": status,
            }
    except Exception as e:
        print("Taker flow hata:", symbol, period, e, flush=True)
        out = {
            "ok": False,
            "long_flow_usdt": 0.0,
            "short_flow_usdt": 0.0,
            "net_delta_usdt": 0.0,
            "delta_ratio": 0.0,
            "buy_ratio_pct": 0.0,
            "sell_ratio_pct": 0.0,
            "status": "DELTA VERI YOK",
        }

    taker_flow_cache[cache_key] = {"time": now, "data": out}
    return out


def get_taker_flow_context(symbol):
    """Son 15m ve yaklasik 1h taker akisini birlestirir."""
    f15 = fetch_taker_flow(symbol, "15m", 2)
    f1h = fetch_taker_flow(symbol, "1h", 2)

    long15 = f15.get("long_flow_usdt", 0.0)
    short15 = f15.get("short_flow_usdt", 0.0)
    delta15 = f15.get("net_delta_usdt", 0.0)
    ratio15 = f15.get("delta_ratio", 0.0)

    long1h = f1h.get("long_flow_usdt", 0.0)
    short1h = f1h.get("short_flow_usdt", 0.0)
    delta1h = f1h.get("net_delta_usdt", 0.0)
    ratio1h = f1h.get("delta_ratio", 0.0)

    buyer_dominant = ratio15 >= 8 or ratio1h >= 8
    strong_buyer_dominant = ratio15 >= 18 or ratio1h >= 18
    seller_dominant = ratio15 <= -8 or ratio1h <= -8
    strong_seller_dominant = ratio15 <= -18 or ratio1h <= -18

    if strong_buyer_dominant:
        status = "GUCLU ALICI BASKIN"
    elif buyer_dominant:
        status = "ALICI BASKIN"
    elif strong_seller_dominant:
        status = "GUCLU SATICI BASKIN"
    elif seller_dominant:
        status = "SATICI BASKIN"
    else:
        status = "DELTA NOTR"

    return {
        "taker_ok": bool(f15.get("ok") or f1h.get("ok")),
        "long_flow_15m": long15,
        "short_flow_15m": short15,
        "net_delta_15m": delta15,
        "delta_ratio_15m": ratio15,
        "long_flow_1h": long1h,
        "short_flow_1h": short1h,
        "net_delta_1h": delta1h,
        "delta_ratio_1h": ratio1h,
        "delta_status": status,
        "buyer_dominant": buyer_dominant,
        "strong_buyer_dominant": strong_buyer_dominant,
        "seller_dominant": seller_dominant,
        "strong_seller_dominant": strong_seller_dominant,
    }


def attach_taker_flow_context(d, taker_context):
    if d and taker_context:
        d.update(taker_context)
    return d

def btc_filter():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)

    if df is None:
        return True, "BTC VERI YOK"

    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.macd > last.macd_signal and last.rsi >= 42

    return ok, "BTC DESTEKLI" if ok else "BTC ZAYIF"


def build_universe():
    try:
        markets = exchange.load_markets()
        symbols = [
            s for s in markets
            if s.endswith("/USDT:USDT") and markets[s].get("active", True)
        ]

        tickers = exchange.fetch_tickers(symbols)
        rows = []

        for s in symbols:
            t = tickers.get(s, {})
            qv = t.get("quoteVolume") or 0
            pct = t.get("percentage") or 0
            last = t.get("last") or 0
            high = t.get("high") or 0
            low = t.get("low") or 0

            if last <= 0 or high <= 0 or low <= 0 or qv <= 0:
                continue

            volatility = ((high - low) / last) * 100

            if qv < 3_000_000:
                continue

            if volatility < 1.5:
                continue

            rows.append({
                "symbol": s,
                "qv": qv,
                "pct": pct,
                "last": last,
                "high": high,
                "low": low,
                "volatility": volatility
            })

        if not rows:
            return []

        df = pd.DataFrame(rows)
        df["pct_rank"] = df["pct"].rank(pct=True) * 100
        df["vol_rank"] = df["qv"].rank(pct=True) * 100
        df["volatility_rank"] = df["volatility"].rank(pct=True) * 100

        df["rs_score"] = (
            df["pct_rank"] * 0.45 +
            df["vol_rank"] * 0.30 +
            df["volatility_rank"] * 0.25
        )

        df = df.sort_values(["rs_score", "qv"], ascending=False).head(MAX_SYMBOLS)
        result = df.to_dict("records")

        print("RS evren secildi:", len(result), flush=True)
        for r in result[:15]:
            print(
                r["symbol"],
                "RS:", round(r["rs_score"], 1),
                "24h%:", round(r["pct"], 2),
                "Vol:", int(r["qv"]),
                flush=True
            )

        return result

    except Exception as e:
        print("Universe hata:", e, flush=True)
        return []


def fib_targets(df, lookback=60):
    recent = df.tail(lookback)
    low = recent["low"].min()
    high = recent["high"].max()
    impulse = high - low

    if impulse <= 0:
        return None

    return {"low": low, "high": high}


def recent_price_gains(df, price=None):
    """FOMO filtresi: son 15m / 30m hareketini olcer."""
    if df is None or len(df) < 3:
        return {"price_gain_15m": 0, "price_gain_30m": 0}
    now_price = price if price is not None else df["close"].iloc[-1]
    p15 = df["close"].iloc[-2]
    p30 = df["close"].iloc[-3]
    gain15 = ((now_price - p15) / p15) * 100 if p15 > 0 else 0
    gain30 = ((now_price - p30) / p30) * 100 if p30 > 0 else 0
    return {"price_gain_15m": gain15, "price_gain_30m": gain30}


def is_fomo_block(d):
    """Gec kalmis patlama mumunu AL kapisindan engeller."""
    if not d:
        return True
    if d.get("fomo_exempt") and d.get("module") in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        return False
    price_gain_from_first = d.get("price_gain_from_first", 0)
    price_gain_15m = d.get("price_gain_15m", 0)
    price_gain_30m = d.get("price_gain_30m", 0)
    dist_from_low = d.get("dist_from_low", 0)
    rsi_value = d.get("rsi", d.get("rsi15", 0))

    if price_gain_from_first > 6.0:
        return True
    if price_gain_15m > 6.0:
        return True
    if price_gain_30m > 12.0:
        return True
    if dist_from_low > 18:
        return True
    if rsi_value >= 78:
        return True
    return False


def support_resistance_context(symbol, price=None):
    """
    V22 EN YAKIN DESTEK / DIRENC OKUMA:
    Eski sistem son 15m/1H araligindaki en buyuk tepeyi direnc aliyordu.
    Bu versiyon fiyat USTUNDEKI en yakin 15m/1H swing high'i direnc,
    fiyat ALTINDAKI en yakin 15m/1H swing low'u destek olarak secer.
    Boylece saatlik ara direncler mesajda daha dogru gorunur.
    """
    out = {
        "sr_ok": False,
        "support_level": 0.0,
        "resistance_level": 0.0,
        "support_distance_pct": 0.0,
        "resistance_distance_pct": 999.0,
        "resistance_broken": False,
        "support_near": False,
        "sr_status": "SR VERI YOK",
        "sr_penalty": 0,
        "sr_bonus": 0,
    }

    try:
        df15 = fetch_df(symbol, "15m", max(120, SR_LOOKBACK_15M + 20))
        df1h = fetch_df(symbol, "1h", max(80, SR_LOOKBACK_1H + 10))

        if df15 is None or len(df15) < 30:
            return out

        last_price = float(price if price is not None else df15["close"].iloc[-1])
        if last_price <= 0:
            return out

        # Son mumu disarida birakiyoruz; aktif mum fitili sahte direnc/destek yapmasin.
        high_values = []
        low_values = []

        h15 = df15["high"].iloc[-SR_LOOKBACK_15M-1:-1]
        l15 = df15["low"].iloc[-SR_LOOKBACK_15M-1:-1]
        if len(h15) > 0:
            high_values += [float(x) for x in h15.dropna().tolist()]
            low_values += [float(x) for x in l15.dropna().tolist()]

        if df1h is not None and len(df1h) >= 20:
            h1 = df1h["high"].iloc[-SR_LOOKBACK_1H-1:-1]
            l1 = df1h["low"].iloc[-SR_LOOKBACK_1H-1:-1]
            if len(h1) > 0:
                high_values += [float(x) for x in h1.dropna().tolist()]
                low_values += [float(x) for x in l1.dropna().tolist()]

        # En yakin direnç = fiyat ustundeki en dusuk swing high.
        highs_above = [x for x in high_values if x > last_price]
        # En yakin destek = fiyat altindaki en yuksek swing low.
        lows_below = [x for x in low_values if 0 < x < last_price]

        resistance = min(highs_above) if highs_above else (max(high_values) if high_values else 0.0)
        support = max(lows_below) if lows_below else (min(low_values) if low_values else 0.0)

        resistance_distance = ((resistance - last_price) / last_price * 100) if resistance > 0 else 999.0
        support_distance = ((last_price - support) / support * 100) if support > 0 else 999.0

        resistance_broken = resistance > 0 and last_price > resistance * (1 + SR_BREAKOUT_BUFFER_PCT / 100)
        support_near = support > 0 and 0 <= support_distance <= SR_SUPPORT_NEAR_BONUS_PCT

        penalty = 0
        bonus = 0
        if resistance_broken:
            status = "DIRENC KIRILDI"
            bonus += 12
        elif 0 <= resistance_distance <= SR_TOO_CLOSE_BLOCK_PCT:
            status = "DIRENC COK YAKIN"
            penalty -= 25
        elif 0 <= resistance_distance <= SR_CLOSE_PENALTY_PCT:
            status = "DIRENC YAKIN"
            penalty -= 15
        elif 0 <= resistance_distance <= SR_NEAR_PENALTY_PCT:
            status = "DIRENC BOLGESI"
            penalty -= 8
        else:
            status = "DIRENC UZAK/RAHAT"

        if support_near:
            bonus += 8
            status += " + DESTEK USTU"
        elif 0 <= support_distance <= SR_SUPPORT_OK_MAX_PCT:
            bonus += 4
            status += " + DESTEK YAKIN"

        out.update({
            "sr_ok": True,
            "support_level": support,
            "resistance_level": resistance,
            "support_distance_pct": support_distance if support_distance < 900 else 0.0,
            "resistance_distance_pct": resistance_distance,
            "resistance_broken": bool(resistance_broken),
            "support_near": bool(support_near),
            "sr_status": status,
            "sr_penalty": penalty,
            "sr_bonus": bonus,
        })
        return out
    except Exception as e:
        print("SR context hata:", symbol, e, flush=True)
        return out

def attach_support_resistance_context(symbol, d):
    if not d:
        return d
    price = float(d.get("entry", d.get("price", 0)) or 0)
    sr = support_resistance_context(symbol, price)
    d.update(sr)
    return d


def build_entry_levels(d):
    """
    V20 SR TP SISTEMI:
    Elite AL icin giris/stop ayni kalir; TP'ler varsa destek/direnc yapisina gore hazirlanir.
    Direnc fiyat ustundeyse TP1 dirence yakin, TP2/TP3 direnc kirilimi sonrasi hedefler olur.
    Direnc yoksa/kirilmis ise eski risk-katlari sistemi yedek olarak calisir.
    """
    price = float(d.get("entry", d.get("price", 0)) or 0)
    if price <= 0:
        return {
            "entry": 0, "stop": 0, "tp1": 0, "tp2": 0, "tp3": 0, "risk_pct": 0,
            "tp_system": "YOK", "tp_reference": "YOK"
        }

    if d.get("stop", 0) > 0:
        stop = float(d["stop"])
    else:
        # Binance karar botunda risk sabit ve net olsun.
        risk_pct = 0.032 if d.get("module") in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP") else 0.028
        stop = price * (1 - risk_pct)

    risk = max(price - stop, price * 0.01)

    resistance = float(d.get("resistance_level", 0) or 0)
    support = float(d.get("support_level", 0) or 0)
    resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
    resistance_broken = bool(d.get("resistance_broken"))

    # Varsayilan klasik TP sistemi.
    tp1 = price + risk * 1.5
    tp2 = price + risk * 2.5
    tp3 = price + risk * 4.0
    tp_system = "RISK_KATLI"
    tp_reference = "Stop mesafesi"

    # Direnc fiyat ustundeyse TP'leri piyasa yapisina bagla.
    if resistance > price and resistance_distance < 25:
        # TP1: direncin hemen onu; ilk kar alma.
        tp1 = max(price + risk * 0.80, resistance * 0.995)
        # TP2/TP3: direnc kirilimi sonrasi genisleme hedefleri.
        tp2 = max(tp1 * 1.002, resistance * 1.020)
        tp3 = max(tp2 * 1.002, resistance * 1.050)
        tp_system = "DESTEK_DIRENC"
        tp_reference = f"Direnc {resistance:.8f}"

        # Direnc cok yakin ise TP1'i asiri uzaklastirma; risk/odul bozulmasin.
        if resistance_distance <= 1.5:
            tp1 = resistance * 0.997
            tp2 = resistance * 1.012
            tp3 = resistance * 1.030
            tp_reference = f"Yakin direnc {resistance:.8f}"

    elif resistance_broken and resistance > 0:
        # Direnc zaten kirilmissa eski direnc yeni destek gibi kabul edilir.
        tp1 = max(price + risk * 1.2, price * 1.012)
        tp2 = max(tp1 * 1.002, price * 1.024)
        tp3 = max(tp2 * 1.002, price * 1.040)
        tp_system = "KIRILIM_DEVAM"
        tp_reference = f"Kirilmis direnc {resistance:.8f}"

    # TP'ler fiyat ustunde ve sirali kalsin.
    tp1 = max(tp1, price * 1.003)
    tp2 = max(tp2, tp1 * 1.002)
    tp3 = max(tp3, tp2 * 1.002)

    return {
        "entry": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pct": (risk / price) * 100,
        "tp_system": tp_system,
        "tp_reference": tp_reference,
        "tp_support_reference": support,
        "tp_resistance_reference": resistance,
    }


def attach_market_impact(d, item):
    """
    Coinin kendi 24s hacmine gore gelen paranin etkisini olcer.
    Mutlak USDT hacim tek basina yeterli degil; 100k USDT bazi coinde dev etki,
    bazi coinde cok kucuk etki yapar.
    """
    if not d or not item:
        return d

    daily_qv = item.get("qv") or item.get("quoteVolume") or 0
    if daily_qv <= 0:
        d["daily_quote_volume"] = 0
        d["impact_usdt_volume"] = 0
        d["market_impact_pct"] = 0
        d["market_impact_score"] = 0
        return d

    module = d.get("module", "")

    # SAFE genelde 1m hacimle gelir. EARLY/MONEY_ACCEL icin 15m/1h hacim verileri olur.
    impact_usdt = (
        d.get("usdt_vol")
        or d.get("usdt_vol_15m")
        or (d.get("usdt_vol_1h", 0) * 0.25)
        or 0
    )

    market_impact_pct = (impact_usdt / daily_qv) * 100 if daily_qv > 0 else 0

    score = 0
    if market_impact_pct >= 0.35:
        score = 20
    elif market_impact_pct >= 0.20:
        score = 15
    elif market_impact_pct >= 0.10:
        score = 10
    elif market_impact_pct >= 0.05:
        score = 6
    elif market_impact_pct >= 0.02:
        score = 3

    d["daily_quote_volume"] = daily_qv
    d["impact_usdt_volume"] = impact_usdt
    d["market_impact_pct"] = market_impact_pct
    d["market_impact_score"] = score

    apply_fast_money_bonus(d)
    return d


def market_impact_ok(d):
    """
    Elite AL kapisinda coinin hacmine gore para etkisi yeterli mi kontrol eder.
    Binance daha likit oldugu icin esik MEXC'e gore biraz daha esnek tutuldu.
    """
    if not d:
        return False

    module = d.get("module", "")
    score = d.get("market_impact_score", 0)
    pct = d.get("market_impact_pct", 0)

    # SAFE / MONEY_ACCEL karar sinyali icin market etki gerekli.
    if module in ("SAFE", "MONEY_ACCEL"):
        return score >= 3 or pct >= 0.02

    # Dip / sweep sinyallerinde hacim bazen ani iÄŸneyle gelir; yine de minimum etki ariyoruz.
    if module in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        return score >= 3 or pct >= 0.015

    return score >= 3 or pct >= 0.02






def apply_fast_money_bonus(d):
    """
    V12 FAST MONEY BONUS:
    AGT/ESPORTS tipi hafiza olusmadan ani para-hacim patlamasi yapan coinleri one cikarir.
    Bu tek basina AL degildir; sadece radar/hafiza/elite puanina kontrollu bonus verir.
    """
    if not d:
        return d

    volume_ratio = max(
        float(d.get("vol_ratio", 0) or 0),
        float(d.get("vol_ratio_1h", 0) or 0),
        float(d.get("vol_ratio_15m", 0) or 0),
    )
    para_etkisi = float(d.get("money_impact", 0) or 0)
    market_impact = float(d.get("market_impact_pct", 0) or 0)
    rsi_value = float(d.get("rsi", d.get("rsi15", 0)) or 0)

    fast_money_bonus = (
        para_etkisi >= 3.0
        and volume_ratio >= 3.0
        and market_impact >= 1.0
        and rsi_value <= 75
    )

    d["fast_money_bonus"] = bool(fast_money_bonus)
    d["fast_money_volume_ratio"] = volume_ratio

    if fast_money_bonus and not d.get("_fast_money_score_applied"):
        d["score"] = d.get("score", 0) + 3
        d["_fast_money_score_applied"] = True
        reasons = d.setdefault("reasons", [])
        if "FAST MONEY BONUS" not in reasons:
            reasons.append("FAST MONEY BONUS")

    return d

def cleanup_radar_history():
    now = time.time()
    for symbol in list(radar_history.keys()):
        radar_history[symbol] = [e for e in radar_history[symbol] if now - e.get("time", 0) <= RADAR_HISTORY_EXPIRE_SECONDS]
        if not radar_history[symbol]:
            radar_history.pop(symbol, None)


def record_radar_history(symbol, signals):
    if not signals:
        return
    now = time.time()
    events = radar_history.setdefault(symbol, [])
    for d in signals:
        if not d:
            continue
        module = d.get("module", "UNKNOWN")
        duplicate = False
        for e in events:
            if e.get("module") == module and now - e.get("time", 0) < RADAR_HISTORY_DEDUP_SECONDS:
                e.update({
                    "time": now,
                    "price": d.get("price", e.get("price", 0)),
                    "score": max(e.get("score", 0), d.get("score", 0)),
                    "money_impact": max(e.get("money_impact", 0), d.get("money_impact", 0)),
                    "volume_power": max(e.get("volume_power", 0), d.get("volume_power", 0)),
                    "market_impact_pct": max(e.get("market_impact_pct", 0), d.get("market_impact_pct", 0)),
                    "rsi": d.get("rsi", d.get("rsi15", e.get("rsi", 0))),
                    "fast_money_bonus": bool(e.get("fast_money_bonus") or d.get("fast_money_bonus")),
                })
                duplicate = True
                break
        if duplicate:
            continue
        events.append({
            "time": now,
            "module": module,
            "price": d.get("price", 0),
            "score": d.get("score", 0),
            "money_impact": d.get("money_impact", 0),
            "volume_power": d.get("volume_power", 0),
            "market_impact_pct": d.get("market_impact_pct", 0),
            "rsi": d.get("rsi", d.get("rsi15", 0)),
            "fast_money_bonus": bool(d.get("fast_money_bonus")),
        })
    cleanup_radar_history()


def radar_history_summary(symbol):
    cleanup_radar_history()
    events = sorted(radar_history.get(symbol, []), key=lambda x: x.get("time", 0))
    if not events:
        return {"history_points": 0, "history_modules": [], "history_text": "YOK", "history_age_min": 0, "history_first_price": 0, "history_price_gain": 0, "history_money_max": 0, "history_power_max": 0, "history_market_max": 0, "history_unique_count": 0, "fast_money_count": 0, "fast_money_bonus": False}
    modules = []
    for e in events:
        m = e.get("module", "UNKNOWN")
        if m not in modules:
            modules.append(m)
    points = sum(RADAR_HISTORY_WEIGHTS.get(m, 0) for m in modules)
    s = set(modules)
    if {"EARLY", "MONEY"}.issubset(s) or {"EARLY", "MONEY_ACCEL"}.issubset(s):
        points += 5
    if {"TREND_BUILDUP", "EARLY"}.issubset(s):
        points += 5
    if {"TREND_BUILDUP", "MONEY"}.issubset(s) or {"TREND_BUILDUP", "MONEY_ACCEL"}.issubset(s):
        points += 6
    if {"SAFE", "MONEY_ACCEL"}.issubset(s):
        points += 4
    if "MOMENTUM" in s and ("MONEY" in s or "MONEY_ACCEL" in s or "TREND_BUILDUP" in s):
        points += 3
    fast_money_count = sum(1 for e in events if e.get("fast_money_bonus"))
    if fast_money_count > 0:
        points += 4
    first = events[0]
    last = events[-1]
    first_price = first.get("price", 0)
    last_price = last.get("price", first_price)
    gain = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0
    return {
        "history_points": points,
        "history_modules": modules,
        "history_text": ", ".join(modules),
        "history_age_min": (time.time() - first.get("time", time.time())) / 60,
        "history_first_price": first_price,
        "history_price_gain": gain,
        "history_money_max": max(e.get("money_impact", 0) for e in events),
        "history_power_max": max(e.get("volume_power", 0) for e in events),
        "history_market_max": max(e.get("market_impact_pct", 0) for e in events),
        "history_unique_count": len(modules),
        "fast_money_count": fast_money_count,
        "fast_money_bonus": fast_money_count > 0,
    }


def cleanup_money_memory():
    now = time.time()
    for symbol in list(money_memory.keys()):
        money_memory[symbol] = [e for e in money_memory[symbol] if now - e.get("time", 0) <= MONEY_MEMORY_EXPIRE_SECONDS]
        if not money_memory[symbol]:
            money_memory.pop(symbol, None)


def update_money_memory(symbol, d):
    if not d:
        return
    usdt = d.get("impact_usdt_volume") or d.get("usdt_vol") or d.get("usdt_vol_15m") or d.get("usdt_vol_1h") or 0
    market = d.get("market_impact_pct", 0)
    power = d.get("volume_power", 0)
    money = d.get("money_impact", 0)
    if usdt < MONEY_MEMORY_MIN_EVENT_USDT and market < MONEY_MEMORY_MIN_EVENT_MARKET and power < MONEY_MEMORY_MIN_EVENT_POWER:
        return
    events = money_memory.setdefault(symbol, [])
    events.append({
        "time": time.time(),
        "price": d.get("price", 0),
        "module": d.get("module", "UNKNOWN"),
        "usdt": float(usdt or 0),
        "market": float(market or 0),
        "power": float(power or 0),
        "money": float(money or 0),
    })
    cleanup_money_memory()


def money_memory_summary(symbol):
    cleanup_money_memory()
    events = money_memory.get(symbol, [])
    now = time.time()
    if not events:
        return {"money_mem_60m": 0, "money_mem_30m": 0, "money_mem_15m": 0, "money_wave_count": 0, "money_market_60m": 0, "money_first_price": 0, "money_gain_from_first": 0, "money_memory_bonus": False}
    e60 = [e for e in events if now - e["time"] <= 60 * 60]
    e30 = [e for e in events if now - e["time"] <= 30 * 60]
    e15 = [e for e in events if now - e["time"] <= 15 * 60]
    buckets = set(int(e["time"] // (5 * 60)) for e in e60)
    first_price = e60[0].get("price", 0) if e60 else 0
    last_price = e60[-1].get("price", first_price) if e60 else first_price
    gain = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0
    total60 = sum(e.get("usdt", 0) for e in e60)
    total30 = sum(e.get("usdt", 0) for e in e30)
    total15 = sum(e.get("usdt", 0) for e in e15)
    market60 = sum(e.get("market", 0) for e in e60)
    waves = len(buckets)
    bonus = (
        waves >= MONEY_MEMORY_MIN_WAVES
        and total15 >= MONEY_MEMORY_MIN_15M_USDT
        and total30 >= MONEY_MEMORY_MIN_30M_USDT
        and (total60 >= MONEY_MEMORY_MIN_TOTAL_USDT or market60 >= MONEY_MEMORY_MIN_MARKET_60M)
        and gain <= 9.0
    )
    return {"money_mem_60m": total60, "money_mem_30m": total30, "money_mem_15m": total15, "money_wave_count": waves, "money_market_60m": market60, "money_first_price": first_price, "money_gain_from_first": gain, "money_memory_bonus": bonus}


def cleanup_main_signal_memory():
    now = time.time()
    for symbol in list(main_signal_memory.keys()):
        main_signal_memory[symbol] = [
            e for e in main_signal_memory[symbol]
            if now - e.get("time", 0) <= MAIN_SIGNAL_MEMORY_EXPIRE_SECONDS
        ]
        if not main_signal_memory[symbol]:
            main_signal_memory.pop(symbol, None)


def record_main_signal_memory(symbol, signals):
    """Ana kanala tekrar tekrar dusen coinleri hafizada tutar."""
    if not signals:
        return
    now = time.time()
    events = main_signal_memory.setdefault(symbol, [])
    for d in signals:
        if not d:
            continue
        module = d.get("module", "UNKNOWN")
        duplicate = False
        for e in events:
            if e.get("module") == module and now - e.get("time", 0) < MAIN_SIGNAL_DEDUP_SECONDS:
                e.update({
                    "time": now,
                    "price": d.get("price", e.get("price", 0)),
                    "score": max(e.get("score", 0), d.get("score", 0)),
                    "money_impact": max(e.get("money_impact", 0), d.get("money_impact", 0)),
                    "volume_power": max(e.get("volume_power", 0), d.get("volume_power", 0)),
                    "market_impact_pct": max(e.get("market_impact_pct", 0), d.get("market_impact_pct", 0)),
                })
                duplicate = True
                break
        if duplicate:
            continue
        events.append({
            "time": now,
            "module": module,
            "price": d.get("price", 0),
            "score": d.get("score", 0),
            "money_impact": d.get("money_impact", 0),
            "volume_power": d.get("volume_power", 0),
            "market_impact_pct": d.get("market_impact_pct", 0),
        })
    cleanup_main_signal_memory()


def main_signal_memory_summary(symbol):
    cleanup_main_signal_memory()
    events = sorted(main_signal_memory.get(symbol, []), key=lambda x: x.get("time", 0))
    now = time.time()
    if not events:
        return {
            "main_signal_count_60m": 0,
            "main_signal_count_120m": 0,
            "main_signal_modules": [],
            "main_signal_text": "YOK",
            "main_signal_first_price": 0,
            "main_signal_gain": 0,
            "main_signal_bonus": 0,
        }
    e60 = [e for e in events if now - e.get("time", 0) <= 60 * 60]
    e120 = [e for e in events if now - e.get("time", 0) <= 120 * 60]
    modules = []
    for e in e120:
        m = e.get("module", "UNKNOWN")
        if m not in modules:
            modules.append(m)
    first_price = e120[0].get("price", 0) if e120 else 0
    last_price = e120[-1].get("price", first_price) if e120 else first_price
    gain = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0
    bonus = 0
    if len(e60) >= 3:
        bonus += MAIN_SIGNAL_BONUS_60M_3
    if len(e120) >= 5:
        bonus += MAIN_SIGNAL_BONUS_120M_5
    if len(e120) >= 8:
        bonus += MAIN_SIGNAL_BONUS_120M_8
    return {
        "main_signal_count_60m": len(e60),
        "main_signal_count_120m": len(e120),
        "main_signal_modules": modules,
        "main_signal_text": ", ".join(modules),
        "main_signal_first_price": first_price,
        "main_signal_gain": gain,
        "main_signal_bonus": bonus,
    }


def apply_reentry_second_wave_flags(d):
    if not d:
        return d
    history_points = d.get("history_points", 0)
    main_count_120 = d.get("main_signal_count_120m", 0)

    # V17: HISTORY_BUILDUP mesajinda canli para 0 gorunebilir. Bu durumda
    # hafizadaki max para / max hacim / toplam market etki esas alinmali.
    money_impact = max(float(d.get("money_impact", 0) or 0), float(d.get("history_money_max", 0) or 0))
    volume_power = max(float(d.get("volume_power", 0) or 0), float(d.get("history_power_max", 0) or 0))
    market_impact_pct = max(
        float(d.get("market_impact_pct", 0) or 0),
        float(d.get("history_market_max", 0) or 0),
        float(d.get("money_market_60m", 0) or 0),
    )
    money_mem_15m = float(d.get("money_mem_15m", 0) or 0)
    money_mem_30m = float(d.get("money_mem_30m", 0) or 0)
    money_mem_60m = float(d.get("money_mem_60m", 0) or 0)
    money_waves = int(d.get("money_wave_count", 0) or 0)
    money_gain = float(d.get("money_gain_from_first", 0) or 0)

    repeat_force = (
        main_count_120 >= REPEAT_FORCE_MIN_120M
        and money_waves >= REPEAT_FORCE_MIN_WAVES
        and (money_mem_60m >= REPEAT_FORCE_MIN_60M_USDT or market_impact_pct >= REPEAT_FORCE_MIN_MARKET_60M)
        and money_gain <= 12
    )

    history_force = (
        history_points >= HISTORY_FORCE_MIN_POINTS
        and money_waves >= HISTORY_FORCE_MIN_WAVES
        and money_mem_60m >= HISTORY_FORCE_MIN_60M_USDT
        and money_gain <= 12
    )

    memory_reentry = (
        (history_points >= MEMORY_REENTRY_MIN_HISTORY or main_count_120 >= 3 or d.get("money_memory_bonus") or repeat_force or history_force)
        and (
            (money_impact >= MEMORY_REENTRY_MIN_MONEY and volume_power >= MEMORY_REENTRY_MIN_POWER and market_impact_pct >= 0.02)
            or repeat_force
            or history_force
        )
    )

    second_wave = (
        money_waves >= 3
        and money_mem_15m >= SECOND_WAVE_MIN_15M_USDT
        and money_mem_30m >= SECOND_WAVE_MIN_30M_USDT
        and (
            money_mem_30m >= money_mem_15m * 1.05
            or money_mem_60m >= REPEAT_FORCE_MIN_60M_USDT
            or market_impact_pct >= REPEAT_FORCE_MIN_MARKET_60M
        )
        and money_gain <= 12
    )
    main_repeat_buildup = (main_count_120 >= 5 and d.get("main_signal_bonus", 0) > 0) or repeat_force

    d["effective_money_impact"] = money_impact
    d["effective_volume_power"] = volume_power
    d["effective_market_impact_pct"] = market_impact_pct
    d["repeat_force"] = bool(repeat_force)
    d["history_force"] = bool(history_force)
    d["memory_reentry"] = bool(memory_reentry)
    d["second_wave_bonus"] = bool(second_wave)
    d["main_repeat_buildup"] = bool(main_repeat_buildup)
    return d


def trend_buildup_signal(symbol, rs):
    """Sessiz trend: Higher Low + EMA21 ustu tutunma + OBV/MACD + parca parca para."""
    df15 = fetch_df(symbol, "15m", 180)
    df1h = fetch_df(symbol, "1h", 120)
    if df15 is None or df1h is None or len(df15) < 60:
        return False, None
    m15 = df15.iloc[-1]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    price = m15.close
    p6h = df15["close"].iloc[-25]
    p12h = df15["close"].iloc[-49] if len(df15) >= 49 else df15["close"].iloc[0]
    price_change_6h = ((price - p6h) / p6h) * 100 if p6h > 0 else 0
    price_change_12h = ((price - p12h) / p12h) * 100 if p12h > 0 else 0
    low_24h = df15["low"].tail(96).min()
    high_24h = df15["high"].tail(96).max()
    dist_from_low = ((price - low_24h) / low_24h) * 100 if low_24h > 0 else 999
    pullback_from_high = ((high_24h - price) / high_24h) * 100 if high_24h > 0 else 999

    lows = df15["low"].tail(24).reset_index(drop=True)
    highs = df15["high"].tail(24).reset_index(drop=True)
    higher_low_count = 0
    higher_high_count = 0
    for i in range(4, len(lows), 4):
        if lows.iloc[i] > lows.iloc[i-4]:
            higher_low_count += 1
        if highs.iloc[i] > highs.iloc[i-4]:
            higher_high_count += 1

    close_above_ema21_count = int((df15["close"].tail(12) > df15["ema21"].tail(12)).sum())
    last8_vol = df15["volume"].tail(8).mean()
    prev16_vol = df15["volume"].iloc[-24:-8].mean()
    vol_ratio = last8_vol / prev16_vol if prev16_vol > 0 else 0
    usdt_vol = df15["volume"].tail(8).sum() * price
    avg_usdt_vol = df15["vol_avg"].tail(8).sum() * price if df15["vol_avg"].tail(8).sum() > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-16]
    macd_turn = m15.macd > df15["macd"].iloc[-4] or h1.macd > h1_prev.macd
    ema_structure = m15.close > m15.ema21 and m15.ema9 >= m15.ema21 * 0.995
    h1_structure = h1.close > h1.ema21 or h1.ema9 >= h1.ema21 * 0.995

    if price_change_6h < 1.0 or price_change_6h > 24 or price_change_12h > 45:
        return False, None
    if not (45 <= m15.rsi <= 74):
        return False, None
    if dist_from_low > 32:
        return False, None

    score = 0
    reasons = []
    if higher_low_count >= 3:
        score += 3; reasons.append("Higher Low yapisi")
    elif higher_low_count >= 2:
        score += 2; reasons.append("Higher Low basliyor")
    if higher_high_count >= 2:
        score += 2; reasons.append("Higher High basliyor")
    if close_above_ema21_count >= 8:
        score += 3; reasons.append("15m EMA21 ustu tutunma")
    if ema_structure:
        score += 2; reasons.append("EMA yapi yukari")
    if h1_structure:
        score += 2; reasons.append("1H yapi toparliyor")
    if 50 <= m15.rsi <= 68:
        score += 2; reasons.append("RSI trend bolgesi")
    if 1.15 <= vol_ratio <= 3.8:
        score += 2; reasons.append("Hacim sessiz artiyor")
    if money_impact >= 1.20:
        score += 2; reasons.append("Para etkisi surekli pozitif")
    if volume_power >= 1.8:
        score += 2; reasons.append("Hacim gucu birikiyor")
    if obv_up:
        score += 3; reasons.append("OBV birikim")
    if macd_turn:
        score += 2; reasons.append("MACD toparlanma")
    if 1.5 <= price_change_6h <= 14:
        score += 3; reasons.append("6s kontrollu yukselis")
    if pullback_from_high <= 8:
        score += 1; reasons.append("Tepeye yakin tutunuyor")
    if rs >= 65:
        score += 1; reasons.append("RS yeterli")

    valid = (
        score >= 17
        and higher_low_count >= 2
        and close_above_ema21_count >= 7
        and ema_structure
        and h1_structure
        and 1.0 <= price_change_6h <= 24
        and price_change_12h <= 45
        and money_impact >= 1.15
        and volume_power >= 1.5
        and (obv_up or macd_turn)
    )
    return valid, {
        "module": "TREND_BUILDUP", "score": score, "priority": 33, "price": price, "rs": rs,
        "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "money_impact": money_impact, "volume_power": volume_power,
        "rsi": m15.rsi, "dist_from_low": dist_from_low, "price_change_6h": price_change_6h, "price_change_12h": price_change_12h,
        "higher_low_count": higher_low_count, "higher_high_count": higher_high_count, "close_above_ema21_count": close_above_ema21_count,
        "obv_up": obv_up, "macd_turn": macd_turn, "ema_structure": ema_structure, "h1_structure": h1_structure, "pullback_from_high": pullback_from_high,
        "reasons": reasons,
    }


def build_history_signal(symbol, rs, latest_signals=None):
    latest_signals = latest_signals or []
    hist = radar_history_summary(symbol)
    mem = money_memory_summary(symbol)
    if not latest_signals and hist.get("history_points", 0) <= 0:
        return False, None
    ref = latest_signals[0] if latest_signals else {"price": hist.get("history_first_price", 0), "rsi": 0, "money_impact": 0, "volume_power": 0, "market_impact_pct": 0, "score": 0}
    rsi_value = ref.get("rsi", ref.get("rsi15", 0))
    points = hist.get("history_points", 0)
    age = hist.get("history_age_min", 0)
    gain = hist.get("history_price_gain", 0)
    modules = hist.get("history_modules", [])
    valid = (
        points >= 16
        and age >= 25
        and gain <= 8
        and rsi_value <= 72
        and (
            hist.get("history_unique_count", 0) >= 3
            or mem.get("money_memory_bonus", False)
            or {"TREND_BUILDUP", "EARLY"}.issubset(set(modules))
        )
    )
    if not valid:
        return False, None
    d = dict(ref)
    d.update(hist)
    d.update(mem)
    if hist.get("fast_money_bonus"):
        d["fast_money_bonus"] = True
        d["fast_money_count"] = hist.get("fast_money_count", 0)
    d["module"] = "HISTORY_BUILDUP"
    d["priority"] = 36
    d["score"] = max(ref.get("score", 0), int(points))
    d["rs"] = rs
    d["price"] = ref.get("price", hist.get("history_first_price", 0))
    d["reasons"] = ["Radar hafizasi gucleniyor", "Son 1 saatte para/radar birikimi var"]
    return True, d

def early_radar(symbol, rs):
    df1h = fetch_df(symbol, "1h", 120)
    df15 = fetch_df(symbol, "15m", 120)

    if df1h is None or df15 is None:
        return False, None

    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]

    vol_ratio_1h = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    vol_ratio_15m = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0

    usdt_vol_1h = h1.volume * h1.close
    usdt_vol_15m = m15.volume * m15.close

    avg_usdt_1h = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    avg_usdt_15m = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0

    money_impact_1h = usdt_vol_1h / avg_usdt_1h if avg_usdt_1h > 0 else 0
    money_impact_15m = usdt_vol_15m / avg_usdt_15m if avg_usdt_15m > 0 else 0
    money_impact = max(money_impact_1h, money_impact_15m)

    volume_power = money_impact * max(vol_ratio_1h, vol_ratio_15m)

    obv_up_1h = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-6]
    obv_up_15m = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    macd_turn_1h = h1.macd > h1_prev.macd
    macd_turn_15m = m15.macd > m15_prev.macd

    macd_cross_near = (
        h1.macd > h1.macd_signal
        or abs(h1.macd - h1.macd_signal) < abs(h1.macd) * 0.45
    )

    low_24h = df1h["low"].tail(24).min()
    dist_from_low = ((h1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    score = 0
    reasons = []

    # Dipten ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ok uzaklaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸mÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ coinleri cezalandÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±r
    if dist_from_low > 15:
        score -= 2

    # ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±k early sayÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±lmayacak kadar uzaksa EARLY puanÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â± dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸er.
    # Ama None dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶nmÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼yoruz; MoneyState / Money Continue iÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§in radar verisi lazÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±m.
    if dist_from_low > 25:
        score -= 3

    bb_now = df1h["bb_width"].iloc[-1]
    bb_prev = df1h["bb_width"].iloc[-6]
    bb_expanding = bb_now > bb_prev

    if rs >= MIN_EARLY_RS:
        score += 3
        reasons.append("RS guclu")

    if vol_ratio_1h >= 1.5:
        score += 2
        reasons.append("1H hacim uyaniyor")

    if vol_ratio_15m >= 1.4:
        score += 2
        reasons.append("15m hacim erken artiyor")

    if usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000:
        score += 1
        reasons.append("USDT hacim yeterli")

    if money_impact >= 1.4:
        score += 2
        reasons.append("Para etkisi guclu")

    if volume_power >= 3.2:
        score += 2
        reasons.append("Hacim gucu guclu")

    if 42 <= h1.rsi <= 85:
        score += 2
        reasons.append("RSI erken/aktif bolge")

    if obv_up_1h or obv_up_15m:
        score += 2
        reasons.append("OBV para girisi")

    if macd_turn_1h or macd_turn_15m:
        score += 1
        reasons.append("MACD toparlaniyor")

    if macd_cross_near:
        score += 1
        reasons.append("MACD kesisime yakin")

    if dist_from_low <= 35:
        score += 2
        reasons.append("24s dibinden cok uzak degil")

    if bb_expanding:
        score += 1
        reasons.append("Bollinger acilmaya basliyor")

    if m15.close > m15.ema21:
        score += 1
        reasons.append("15m EMA21 ustu")

    valid = (
        score >= 13
        and rs >= MIN_EARLY_RS
        and (vol_ratio_1h >= 1.3 or vol_ratio_15m >= 1.4)
        and (usdt_vol_1h >= 25000 or usdt_vol_15m >= 12000)
        and money_impact >= 1.55
        and (
            obv_up_1h
            or obv_up_15m
            or macd_turn_1h
            or macd_turn_15m
            or bb_expanding
        )
        and 42 <= h1.rsi <= 78
        and dist_from_low <= 12
    )

    return valid, {
        "module": "EARLY",
        "score": score,
        "priority": 10,
        "price": h1.close,
        "rs": rs,
        "vol_ratio_1h": vol_ratio_1h,
        "vol_ratio_15m": vol_ratio_15m,
        "usdt_vol_1h": usdt_vol_1h,
        "usdt_vol_15m": usdt_vol_15m,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": h1.rsi,
        "dist_from_low": dist_from_low,
        "bb_expanding": bb_expanding,
        "reasons": reasons
    }


def safe_long(symbol, rs, btc_ok, funding):
    """
    BINANCE SAFE ENTRY:
    Breakout bekleyip gec kalmak yerine; para/hacim yeni guclenirken,
    FOMO olmadan AL kapisina aday uretir.
    """
    df1m = fetch_df(symbol, "1m", 90)
    df5 = fetch_df(symbol, "5m", 100)
    df15 = fetch_df(symbol, "15m", 150)

    if df1m is None or df5 is None or df15 is None:
        return False, None

    m1 = df1m.iloc[-1]
    prev3 = df1m.iloc[-4]
    m5 = df5.iloc[-1]
    t15 = df15.iloc[-1]
    t15_prev = df15.iloc[-2]

    fib = fib_targets(df15)
    if not fib:
        return False, None

    resistance = fib["high"]
    breakout = m5.close > resistance
    strong_breakout = breakout and m5.body_ratio >= 0.35 and m5.upper_wick <= 0.55

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    avg_usdt_vol = m1.vol_avg * m1.close if m1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100 if prev3.open > 0 else 0

    gains = recent_price_gains(df15, m1.close)
    price_gain_15m = gains["price_gain_15m"]
    price_gain_30m = gains["price_gain_30m"]

    low_24h = df15["low"].tail(96).min()
    dist_from_low = ((m1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    trend_up = t15.ema9 > t15.ema21
    trend_new = t15.close > t15.ema9 and t15.ema9 >= t15.ema21 * 0.998
    macd_bull = t15.macd > t15.macd_signal and t15.macd > t15_prev.macd
    macd_turn = t15.macd > t15_prev.macd
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]

    score = 0
    reasons = []
    if rs >= 68: score += 10; reasons.append("RS destekli")
    if vol_ratio >= 1.7: score += 12; reasons.append("1m hacim gucleniyor")
    if usdt_vol >= 30000: score += 8; reasons.append("USDT hacim yeterli")
    if money_impact >= 1.35: score += 10; reasons.append("Para etkisi basladi")
    if volume_power >= 2.6: score += 12; reasons.append("Hacim gucu erken")
    if 0.10 <= change_3m <= 1.20: score += 8; reasons.append("3m kontrollu momentum")
    if trend_new: score += 8; reasons.append("15m EMA geri alindi")
    if macd_turn: score += 8; reasons.append("MACD toparlaniyor")
    if obv_up: score += 8; reasons.append("OBV para girisi")
    if 45 <= t15.rsi <= 70: score += 8; reasons.append("RSI giris bolgesi")
    if strong_breakout: score += 8; reasons.append("5m kontrollu kirilim")
    if dist_from_low <= 12: score += 8; reasons.append("Dipten cok uzak degil")
    if btc_ok: score += 4
    else: score -= 6
    if funding["ok"]: score += 4
    else: score -= 6

    confidence = max(0, min(100, score))

    fomo_block = (
        price_gain_15m > 6
        or price_gain_30m > 12
        or dist_from_low > 18
        or t15.rsi > 72
    )

    valid = (
        confidence >= 72
        and not fomo_block
        and vol_ratio >= 1.7
        and usdt_vol >= 30000
        and money_impact >= 1.35
        and volume_power >= 2.6
        and change_3m >= 0.10
        and (trend_new or trend_up)
        and (macd_turn or macd_bull or obv_up)
        and 45 <= t15.rsi <= 72
        and dist_from_low <= 18
        and (
            strong_breakout
            or volume_power >= 3.0
            or (money_impact >= 1.55 and obv_up)
            or (change_3m >= 0.25 and macd_turn)
        )
    )

    price = m1.close
    stop = max(resistance * 0.990, price * 0.972)
    risk = price - stop

    if risk <= 0:
        return False, None

    risk_pct = (risk / price) * 100
    if risk_pct > MAX_RISK_PCT:
        return False, None

    return valid, {
        "module": "SAFE",
        "score": confidence,
        "priority": 42,
        "price": price,
        "confidence": confidence,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "change_3m": change_3m,
        "price_gain_15m": price_gain_15m,
        "price_gain_30m": price_gain_30m,
        "dist_from_low": dist_from_low,
        "rsi": t15.rsi,
        "rsi15": t15.rsi,
        "trend_up": trend_up,
        "trend_new": trend_new,
        "macd_bull": macd_bull,
        "macd_turn": macd_turn,
        "obv_up": obv_up,
        "breakout": breakout,
        "strong_breakout": strong_breakout,
        "entry": price,
        "stop": stop,
        "tp1": price + risk * 1.5,
        "tp2": price + risk * 2.5,
        "tp3": price + risk * 4.0,
        "risk_pct": risk_pct,
        "reasons": reasons
    }

def big_dip_radar(symbol, rs):
    df1h = fetch_df(symbol, "1h", 120)
    df4h = fetch_df(symbol, "4h", 120)

    if df1h is None or df4h is None:
        return False, None

    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    h4 = df4h.iloc[-1]
    h4_prev = df4h.iloc[-2]

    bb_touch = h4.low <= h4.bb_lower or h4_prev.low <= h4_prev.bb_lower
    near_1h_lower_bb = h1.low <= h1.bb_lower * 1.015

    # Sahte dip eleme: yukari trenddeki normal fitil DIP sayilmaz
    if h1.rsi > 45 and not bb_touch:
        return False, None

    if h1.close > h1.ema21 and h1.rsi > 50:
        return False, None

    vol_ratio = h1.volume / h1.vol_avg if h1.vol_avg > 0 else 0
    usdt_vol = h1.volume * h1.close
    avg_usdt_vol = h1.vol_avg * h1.close if h1.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    obv_up = df1h["obv"].iloc[-1] > df1h["obv"].iloc[-5]
    rsi_turn = h1.rsi > h1_prev.rsi and h1.rsi < 55
    macd_turn = h1.macd > h1_prev.macd

    low_24h = df1h["low"].tail(24).min()
    dist_from_low = ((h1.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    score = 0
    reasons = []

    if bb_touch:
        score += 3
        reasons.append("4H alt Bollinger tepki")
    if near_1h_lower_bb:
        score += 2
        reasons.append("1H alt Bollinger yakin")
    if vol_ratio >= 1.5:
        score += 2
        reasons.append("1H hacim artisi")
    if usdt_vol >= 50000:
        score += 2
        reasons.append("USDT hacim guclu")
    if money_impact >= 1.2:
        score += 2
        reasons.append("Para etkisi guclu")
    if volume_power >= 2.2:
        score += 2
        reasons.append("Hacim gucu guclu")
    if h1.lower_wick >= 0.50:
        score += 2
        reasons.append("Alt fitil")
    if h1.rsi <= 35:
        score += 3
        reasons.append("RSI asiri satim")
    if obv_up:
        score += 1
        reasons.append("OBV yukari")
    if rsi_turn:
        score += 2
        reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlaniyor")
    if dist_from_low <= 8:
        score += 2
        reasons.append("24s dip bolgesine yakin")

    valid = (
        score >= 10
        and vol_ratio >= 1.5
        and usdt_vol >= 75000
        and h1.lower_wick >= 0.50
        and (
            bb_touch
            or near_1h_lower_bb
            or h1.rsi <= 35
            or dist_from_low <= 8
        )
        and (
            rsi_turn
            or obv_up
            or macd_turn
            or money_impact >= 1.2
        )
    )

    return valid, {
        "module": "DIP",
        "score": score,
        "priority": 20,
        "price": h1.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": h1.rsi,
        "lower_wick": h1.lower_wick,
        "dist_from_low": dist_from_low,
        "reasons": reasons
    }


def liquidity_sweep_watch(symbol, rs):
    """
    15m alt Bollinger disina igne + alt fitil + bant icine donus radari.
    Bu direkt long sinyali degildir; izleme sinyalidir.
    """
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)

    if df15 is None or df1h is None:
        return False, None

    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    avg_usdt_vol = m15.vol_avg * m15.close if m15.vol_avg > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    low_24h = df15["low"].tail(96).min()
    dist_from_low = ((m15.close - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    sweep_now = m15.low < m15.bb_lower and m15.close > m15.bb_lower
    sweep_prev = m15_prev.low < m15_prev.bb_lower and m15_prev.close > m15_prev.bb_lower
    sweep = sweep_now or sweep_prev

    lower_wick = max(m15.lower_wick, m15_prev.lower_wick)
    recovery = max(m15.recovery_ratio, m15_prev.recovery_ratio)

    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-4]
    rsi_turn = m15.rsi > m15_prev.rsi and 28 <= m15.rsi <= 58
    macd_turn = m15.macd > m15_prev.macd
    green_reclaim = m15.close > m15.open and m15.close > m15_prev.close

    if dist_from_low > 8:
        return False, None

    if m15.rsi > 58:
        return False, None

    if h1.close > h1.ema21 and h1.rsi > 60 and not sweep:
        return False, None

    score = 0
    reasons = []

    if sweep:
        score += 4
        reasons.append("15m alt Bollinger disi igne ve geri alis")
    if lower_wick >= 0.50:
        score += 3
        reasons.append("Guclu alt fitil")
    if recovery >= 0.55:
        score += 2
        reasons.append("Mum bant icine toparladi")
    if vol_ratio >= 1.3:
        score += 2
        reasons.append("15m hacim artisi")
    if usdt_vol >= 30000:
        score += 1
        reasons.append("USDT hacim yeterli")
    if money_impact >= 1.15:
        score += 2
        reasons.append("Para etkisi basliyor")
    if volume_power >= 2.0:
        score += 2
        reasons.append("Hacim gucu destekli")
    if obv_turn:
        score += 2
        reasons.append("OBV yukari dondu")
    if rsi_turn:
        score += 2
        reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 1
        reasons.append("MACD toparlaniyor")
    if green_reclaim:
        score += 2
        reasons.append("Yesil geri alis mumu")
    if rs >= 65:
        score += 1
        reasons.append("RS destekli")

    valid = (
        score >= 10
        and sweep
        and lower_wick >= 0.45
        and recovery >= 0.60
        and vol_ratio >= 1.45
        and usdt_vol >= 40000
        and money_impact >= 1.20
        and 28 <= m15.rsi <= 58
        and dist_from_low <= 8
        and (
            obv_turn
            or rsi_turn
            or macd_turn
            or green_reclaim
        )
    )

    return valid, {
        "module": "SWEEP",
        "score": score,
        "priority": 27,
        "price": m15.close,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "dist_from_low": dist_from_low,
        "lower_wick": lower_wick,
        "recovery_ratio": recovery,
        "sweep": sweep,
        "obv_up": obv_turn,
        "macd_turn": macd_turn,
        "rsi_turn": rsi_turn,
        "green_reclaim": green_reclaim,
        "reasons": reasons
    }


def fast_liquidity_sweep_signal(symbol, rs):
    """
    V14 FAST_LIQUIDITY_SWEEP:
    BSB tipi asagi likidasyon alma + hizli geri alis hareketini daha erken yakalar.
    Klasik SWEEP kadar sert BB disi igne beklemez; dip bolgesi, toparlanma orani, hacim ve OBV/MACD donusune bakar.
    """
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)
    if df15 is None or df1h is None or len(df15) < 40:
        return False, None

    m15 = df15.iloc[-1]
    p1 = df15.iloc[-2]
    p2 = df15.iloc[-3]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    price = m15.close

    recent_low = df15["low"].tail(32).min()
    recent_high = df15["high"].iloc[-40:-3].max() if len(df15) >= 45 else df15["high"].tail(32).max()
    dist_from_low = ((price - recent_low) / recent_low) * 100 if recent_low > 0 else 999
    drop_from_high = ((recent_high - recent_low) / recent_high) * 100 if recent_high > 0 else 0

    candles = [m15, p1, p2]
    lower_wick = max(c.lower_wick for c in candles)
    recovery = max(c.recovery_ratio for c in candles)
    swept_lower_bb = any(c.low < c.bb_lower and c.close > c.bb_lower for c in candles)
    touched_lower_bb = any(c.low <= c.bb_lower * 1.025 for c in candles)
    reclaim_ema9 = m15.close > m15.ema9 or p1.close > p1.ema9
    reclaim_ema21 = m15.close > m15.ema21 or p1.close > p1.ema21

    last3_vol = df15["volume"].tail(3).mean()
    prev20_vol = df15["volume"].iloc[-24:-4].mean()
    vol_ratio = last3_vol / prev20_vol if prev20_vol > 0 else 0
    usdt_vol = df15["volume"].tail(3).sum() * price
    avg_usdt_vol = df15["vol_avg"].tail(3).sum() * price if df15["vol_avg"].tail(3).sum() > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    rsi_turn = m15.rsi > p1.rsi or p1.rsi > p2.rsi
    macd_turn = m15.macd > p1.macd or h1.macd > h1_prev.macd
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-5]
    green_reclaim = m15.close > m15.open or p1.close > p1.open

    gains = recent_price_gains(df15, price)
    price_gain_15m = gains["price_gain_15m"]
    price_gain_30m = gains["price_gain_30m"]

    # Coktan kacmis pump degil, dipten hizli geri alis ariyoruz.
    if dist_from_low > 14:
        return False, None
    if m15.rsi > 68:
        return False, None
    if price_gain_15m > 9 or price_gain_30m > 16:
        return False, None

    score = 0
    reasons = []
    if drop_from_high >= 18:
        score += 4; reasons.append("Once sert dusus/supurme")
    elif drop_from_high >= 10:
        score += 2; reasons.append("Dususten sonra toparlanma")
    if dist_from_low <= 6:
        score += 4; reasons.append("Dip bolgesinden hizli donus")
    elif dist_from_low <= 10:
        score += 2; reasons.append("Dibe yakin toparlanma")
    if lower_wick >= 0.45:
        score += 4; reasons.append("Likidasyon alt fitili")
    elif lower_wick >= 0.30:
        score += 2; reasons.append("Alt fitil tepki")
    if recovery >= 0.70:
        score += 4; reasons.append("Mum guclu geri aldi")
    elif recovery >= 0.55:
        score += 2; reasons.append("Mum toparladi")
    if swept_lower_bb:
        score += 4; reasons.append("BB disi supurme ve geri alis")
    elif touched_lower_bb:
        score += 2; reasons.append("Alt BB bolgesi")
    if vol_ratio >= 2.0:
        score += 4; reasons.append("Tepkide hacim guclu")
    elif vol_ratio >= 1.20:
        score += 2; reasons.append("Tepkide hacim artisi")
    if money_impact >= 1.8:
        score += 4; reasons.append("Para etkisi guclu")
    elif money_impact >= 1.05:
        score += 2; reasons.append("Para etkisi basladi")
    if volume_power >= 4.0:
        score += 4; reasons.append("Hacim gucu guclu")
    elif volume_power >= 1.5:
        score += 2; reasons.append("Hacim gucu erken")
    if reclaim_ema9:
        score += 2; reasons.append("EMA9 geri alindi")
    if reclaim_ema21:
        score += 1; reasons.append("EMA21 geri alma")
    if rsi_turn:
        score += 2; reasons.append("RSI dipten donuyor")
    if macd_turn:
        score += 2; reasons.append("MACD toparlaniyor")
    if obv_turn:
        score += 3; reasons.append("OBV tepki veriyor")
    if green_reclaim:
        score += 1; reasons.append("Yesil geri alis")
    if rs >= 50:
        score += 1; reasons.append("RS yeterli")

    valid = (
        score >= 16
        and dist_from_low <= 12
        and recovery >= 0.55
        and lower_wick >= 0.25
        and vol_ratio >= 1.15
        and money_impact >= 1.05
        and volume_power >= 1.25
        and 30 <= m15.rsi <= 68
        and (swept_lower_bb or touched_lower_bb or drop_from_high >= 10 or lower_wick >= 0.35)
        and (rsi_turn or macd_turn or obv_turn or reclaim_ema9 or green_reclaim)
    )

    return valid, {
        "module": "FAST_LIQUIDITY_SWEEP",
        "score": score,
        "priority": 35,
        "price": price,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "dist_from_low": dist_from_low,
        "drop_from_high": drop_from_high,
        "lower_wick": lower_wick,
        "recovery_ratio": recovery,
        "sweep": swept_lower_bb,
        "touched_lower_bb": touched_lower_bb,
        "reclaim_ema9": reclaim_ema9,
        "reclaim_ema21": reclaim_ema21,
        "obv_up": obv_turn,
        "macd_turn": macd_turn,
        "rsi_turn": rsi_turn,
        "green_reclaim": green_reclaim,
        "price_gain_15m": price_gain_15m,
        "price_gain_30m": price_gain_30m,
        "fomo_exempt": True,
        "reasons": reasons,
    }


def update_money_state(symbol, d, stage):
    if not d:
        return

    now = time.time()
    old = money_state.get(symbol)

    if not old:
        money_state[symbol] = {
            "time": now,
            "last_time": now,
            "first_stage": stage,
            "last_stage": stage,
            "first_price": d["price"],
            "last_price": d["price"],
            "first_money_impact": d.get("money_impact", 0),
            "last_money_impact": d.get("money_impact", 0),
            "first_volume_power": d.get("volume_power", 0),
            "last_volume_power": d.get("volume_power", 0),
            "first_score": d.get("score", 0),
            "last_score": d.get("score", 0)
        }
        return

    old["last_time"] = now
    old["last_stage"] = stage
    old["last_price"] = d["price"]
    old["last_money_impact"] = d.get("money_impact", 0)
    old["last_volume_power"] = d.get("volume_power", 0)
    old["last_score"] = d.get("score", 0)


def cleanup_money_state():
    now = time.time()
    expired = []

    for symbol, s in money_state.items():
        if now - s["time"] > MONEY_STATE_EXPIRE_SECONDS:
            expired.append(symbol)

    for symbol in expired:
        money_state.pop(symbol, None)
        print("MONEY STATE SILINDI:", symbol, flush=True)



def pre_rocket_squeeze_signal(symbol, rs):
    """
    V16 PRE_ROCKET_SQUEEZE:
    STO / BEL / LUMIA tipi coinlerde ana kanal tam yerinde görüyor ama Elite olmuyordu.
    Bu radar, fiyat çok kaçmadan gelen yatay sıkışma kırılımı + para/hacim + OBV/MACD
    birleşimini AL adayı yapar. ROCKET sonrası değil, ROCKET öncesi yakalamaya çalışır.
    """
    df15 = fetch_df(symbol, "15m", 160)
    df1h = fetch_df(symbol, "1h", 120)
    if df15 is None or df1h is None or len(df15) < 80:
        return False, None

    m15 = df15.iloc[-1]
    p1 = df15.iloc[-2]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    price = m15.close

    box_high_prev = df15["high"].iloc[-34:-2].max()
    box_low_prev = df15["low"].iloc[-34:-2].min()
    box_range_pct = ((box_high_prev - box_low_prev) / price) * 100 if price > 0 else 999

    bb_now = m15.bb_width
    bb_prev_min = df15["bb_width"].iloc[-34:-4].min()
    bb_was_squeezed = bb_prev_min <= 0.085 or box_range_pct <= 8.5
    bb_expanding = bb_now > df15["bb_width"].iloc[-4]

    range_break = price > box_high_prev * 1.002
    upper_break = price > m15.bb_upper or p1.close > p1.bb_upper
    ma_reclaim = price > m15.ema21 and price > m15.ema9
    ema_structure = price > m15.ema21 and m15.ema9 >= m15.ema21 * 0.995

    last2_vol = df15["volume"].tail(2).mean()
    prev20_vol = df15["volume"].iloc[-24:-4].mean()
    vol_ratio = last2_vol / prev20_vol if prev20_vol > 0 else 0
    usdt_vol = df15["volume"].tail(2).sum() * price
    avg_usdt_vol = df15["vol_avg"].tail(2).sum() * price if df15["vol_avg"].tail(2).sum() > 0 else 0
    money_impact = usdt_vol / avg_usdt_vol if avg_usdt_vol > 0 else 0
    volume_power = money_impact * vol_ratio

    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-12]
    macd_turn = m15.macd > df15["macd"].iloc[-4] or h1.macd > h1_prev.macd
    breakout_strength = ((price - box_high_prev) / box_high_prev) * 100 if box_high_prev > 0 else 0

    gains = recent_price_gains(df15, price)
    price_gain_15m = gains["price_gain_15m"]
    price_gain_30m = gains["price_gain_30m"]

    low_24h = df15["low"].tail(96).min()
    dist_from_low = ((price - low_24h) / low_24h) * 100 if low_24h > 0 else 999

    score = 0
    reasons = []
    if bb_was_squeezed:
        score += 5; reasons.append("Yatay sikisma")
    if bb_expanding:
        score += 3; reasons.append("Bollinger aciliyor")
    if range_break:
        score += 5; reasons.append("Yatay kutu kirilimi")
    if upper_break:
        score += 2; reasons.append("Ust Bollinger temasi")
    if ma_reclaim:
        score += 4; reasons.append("EMA ustune cikti")
    if vol_ratio >= 3.0:
        score += 5; reasons.append("Kirilim hacmi guclu")
    elif vol_ratio >= 2.2:
        score += 3; reasons.append("Hacim artiyor")
    if money_impact >= 2.5:
        score += 5; reasons.append("Para etkisi guclu")
    elif money_impact >= 2.0:
        score += 3; reasons.append("Para etkisi var")
    if volume_power >= 8.0:
        score += 5; reasons.append("Hacim gucu yuksek")
    elif volume_power >= 6.0:
        score += 3; reasons.append("Hacim gucu var")
    if obv_up:
        score += 4; reasons.append("OBV alici baskisi")
    if macd_turn:
        score += 3; reasons.append("MACD toparlaniyor")
    if ema_structure:
        score += 2; reasons.append("EMA yapi yukari")
    if 48 <= m15.rsi <= PRE_ROCKET_MAX_RSI:
        score += 1; reasons.append("RSI kirilim bolgesi")
    if rs >= 60:
        score += 2; reasons.append("RS yeterli")

    valid = (
        score >= 23
        and bb_was_squeezed
        and (range_break or upper_break)
        and ma_reclaim
        and vol_ratio >= PRE_ROCKET_MIN_VOL_RATIO
        and money_impact >= PRE_ROCKET_MIN_MONEY
        and volume_power >= PRE_ROCKET_MIN_POWER
        and 45 <= m15.rsi <= PRE_ROCKET_MAX_RSI
        and price_gain_15m <= PRE_ROCKET_MAX_15M_GAIN
        and price_gain_30m <= PRE_ROCKET_MAX_30M_GAIN
        and dist_from_low <= 30
        and (obv_up or macd_turn)
    )

    return valid, {
        "module": "PRE_ROCKET_SQUEEZE",
        "score": score,
        "priority": 48,
        "price": price,
        "rs": rs,
        "vol_ratio": vol_ratio,
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "bb_width": bb_now,
        "bb_expanding": bb_expanding,
        "range_break": range_break,
        "upper_break": upper_break,
        "box_range_pct": box_range_pct,
        "breakout_strength": breakout_strength,
        "price_gain_15m": price_gain_15m,
        "price_gain_30m": price_gain_30m,
        "dist_from_low": dist_from_low,
        "obv_up": obv_up,
        "macd_turn": macd_turn,
        "ema_structure": ema_structure,
        "fomo_exempt": True,
        "pre_rocket_squeeze": True,
        "reasons": reasons,
    }

def money_continue_signal(symbol, d):
    """
    MONEY ACCELERATION:
    Ilk radar datasindan sonra para/hacim buyuyor ama fiyat henuz kacmamis ise calisir.
    BTW tipi 0.080 gec FOMO sinyalini degil, 0.072-0.075 erken onayi hedefler.
    """
    if symbol not in money_state or not d:
        return False, None

    s = money_state[symbol]
    age = time.time() - s["time"]

    if age < 4 * 60:
        return False, None

    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0

    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01

    money_now = d.get("money_impact", 0)
    power_now = d.get("volume_power", 0)
    rsi_now = d.get("rsi", 0)

    if rsi_now > 72:
        return False, None

    money_growth = money_now / first_money
    power_growth = power_now / first_power
    score_growth = d.get("score", 0) - s.get("first_score", 0)

    cont_score = 0
    reasons = []

    if 0.6 <= price_gain <= 5.0:
        cont_score += 2; reasons.append("Ilk sinyalden sonra kontrollu yukselis")
    if money_now >= 1.45:
        cont_score += 2; reasons.append("Para etkisi gucleniyor")
    if power_now >= 2.8:
        cont_score += 2; reasons.append("Hacim gucu gucleniyor")
    if money_growth >= 1.12:
        cont_score += 2; reasons.append("Para etkisi ilk sinyale gore buyudu")
    if power_growth >= 1.15:
        cont_score += 2; reasons.append("Hacim gucu ilk sinyale gore buyudu")
    if score_growth >= 1:
        cont_score += 1; reasons.append("Radar skoru iyilesti")
    if d.get("bb_expanding", False):
        cont_score += 1; reasons.append("Bollinger aciliyor")

    valid = (
        cont_score >= 7
        and 0.6 <= price_gain <= 5.0
        and money_now >= 1.45
        and power_now >= 2.8
        and rsi_now <= 72
        and (
            money_growth >= 1.10
            or power_growth >= 1.12
            or score_growth >= 2
        )
    )

    if not valid:
        return False, None

    out = dict(d)
    out["module"] = "MONEY_ACCEL"
    out["score"] = cont_score
    out["priority"] = 34
    out["continue_score"] = cont_score
    out["continue_reasons"] = reasons
    out["first_price"] = first_price
    out["price_gain_from_first"] = price_gain
    out["first_money_impact"] = s["first_money_impact"]
    out["money_growth"] = money_growth
    out["first_volume_power"] = s["first_volume_power"]
    out["power_growth"] = power_growth
    out["age_min"] = age / 60
    levels = build_entry_levels(out)
    out.update(levels)
    return True, out

def momentum_continue_signal(symbol, d):
    if symbol not in money_state or not d:
        return False, None

    s = money_state[symbol]
    age = time.time() - s["time"]

    if age < 8 * 60:
        return False, None

    first_price = s["first_price"]
    price_gain = ((d["price"] - first_price) / first_price) * 100 if first_price > 0 else 0

    first_money = s["first_money_impact"] if s["first_money_impact"] > 0 else 0.01
    first_power = s["first_volume_power"] if s["first_volume_power"] > 0 else 0.01

    money_now = d.get("money_impact", 0)
    power_now = d.get("volume_power", 0)

    if d.get("rsi", 0) > 80:
        return False, None

    money_growth = money_now / first_money
    power_growth = power_now / first_power

    mom_score = 0
    reasons = []

    if price_gain >= 1.7:
        mom_score += 3
        reasons.append("Ilk sinyalden sonra fiyat guclendi")
    if money_now >= 1.5:
        mom_score += 2
        reasons.append("Para etkisi yuksek")
    if power_now >= 3.0:
        mom_score += 2
        reasons.append("Hacim gucu yuksek")
    if money_growth >= 1.15:
        mom_score += 2
        reasons.append("Para etkisi buyuyor")
    if power_growth >= 1.20:
        mom_score += 2
        reasons.append("Hacim gucu buyuyor")
    if 52 <= d.get("rsi", 0) <= 82:
        mom_score += 1
        reasons.append("RSI momentum bolgesinde")
    if d.get("bb_expanding", False):
        mom_score += 1
        reasons.append("Bollinger aciliyor")

    valid = (
        mom_score >= 8
        and price_gain >= 1.5
        and money_now >= 1.55
        and power_now >= 3.2
        and (
            money_growth >= 1.12
            or power_growth >= 1.18
        )
    )

    if not valid:
        return False, None

    out = dict(d)
    out["module"] = "MOMENTUM"
    out["score"] = mom_score
    out["priority"] = 35
    out["momentum_score"] = mom_score
    out["momentum_reasons"] = reasons
    out["first_price"] = first_price
    out["price_gain_from_first"] = price_gain
    out["first_money_impact"] = s["first_money_impact"]
    out["money_growth"] = money_growth
    out["first_volume_power"] = s["first_volume_power"]
    out["power_growth"] = power_growth
    out["age_min"] = age / 60
    return True, out

def format_early(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: EARLY RADAR
Coin: {symbol}

Bu islem sinyali degildir.
Coin uyaniyor olabilir.

RS Skoru:
{d['rs']:.1f}/100

Radar Skoru:
{d['score']}/17

Fiyat:
{d['price']:.8f}

1H Hacim Artisi:
{d['vol_ratio_1h']:.2f}x

15m Hacim Artisi:
{d['vol_ratio_15m']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol_1h'])} USDT

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

Para Etkisi:
{d.get('money_impact', 0):.2f}x

Hacim Gucu:
{d.get('volume_power', 0):.2f}

1H RSI:
{d['rsi']:.2f}

24s Dipten Uzaklik:
%{d['dist_from_low']:.2f}

Bollinger:
{"Aciliyor" if d['bb_expanding'] else "Henuz zayif"}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Takibe al.
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
""".strip()


def format_money_continue(symbol, d, funding, btc_status):
    return f"""
BINANCE PARA DEVAM EDIYOR
{BOT_NAME}

Coin: {symbol}

Ilk para girisinden sonra para devam ediyor.

Skor:
{d['continue_score']}/11

Ilk Fiyat:
{d['first_price']:.8f}

Simdiki Fiyat:
{d['price']:.8f}

Ilk Sinyalden Sonra:
%{d['price_gain_from_first']:.2f}

Sure:
{d['age_min']:.1f} dk

RS Skoru:
{d['rs']:.1f}/100

Radar Skoru:
{d['score']}/17

1H Hacim Artisi:
{d['vol_ratio_1h']:.2f}x

15m Hacim Artisi:
{d['vol_ratio_15m']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol_1h'])} USDT

15m USDT Hacim:
{int(d['usdt_vol_15m'])} USDT

Para Etkisi:
{d.get('money_impact', 0):.2f}x

Ilk Para Etkisi:
{d['first_money_impact']:.2f}x

Para Buyume:
{d['money_growth']:.2f}x

Hacim Gucu:
{d.get('volume_power', 0):.2f}

Ilk Hacim Gucu:
{d['first_volume_power']:.2f}

Hacim Gucu Buyume:
{d['power_growth']:.2f}x

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['continue_reasons'])}

Karar:
Ayni coine para girmeye devam ediyor.
Bu ilk EARLY sinyalden daha onemli takip sinyalidir.
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
""".strip()


def format_safe(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: SAFE LONG
Coin: {symbol}
Yon: LONG

RS Skoru:
{d['rs']:.1f}/100

Guven:
{d['confidence']}/100

Giris:
{d['entry']:.8f}

Stop:
{d['stop']:.8f}

TP1:
{d['tp1']:.8f}

TP2:
{d['tp2']:.8f}

TP3:
{d['tp3']:.8f}

Risk:
%{d['risk_pct']:.2f}

1m Hacim:
{int(d['usdt_vol'])} USDT

Hacim Artisi:
{d['vol_ratio']:.2f}x

3m Degisim:
%{d['change_3m']:.2f}

15m RSI:
{d['rsi15']:.2f}

15m Trend:
{"YUKARI" if d['trend_up'] else "ZAYIF"}

15m MACD:
{"YUKARI" if d['macd_bull'] else "ZAYIF"}

5m Breakout:
{"GUCLU" if d['strong_breakout'] else "ZAYIF"}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Karar:
EARLY RADAR sonrasi onayli giris bolgesi.
Stop sart, FOMO yok.
""".strip()


def format_dip(symbol, d, funding, btc_status):
    return f"""
{BOT_NAME}

Mod: BIG DIP RADAR
Coin: {symbol}

Bu direkt long degildir.
Dipten balina tepkisi olabilir.

RS Skoru:
{d['rs']:.1f}/100

Dip Skoru:
{d['score']}/14

Fiyat:
{d['price']:.8f}

1H Hacim Artisi:
{d['vol_ratio']:.2f}x

1H USDT Hacim:
{int(d['usdt_vol'])} USDT

1H RSI:
{d['rsi']:.2f}

Alt Fitil:
%{d['lower_wick'] * 100:.1f}

BTC:
{btc_status}

Funding:
{funding['rate']:.6f}
{funding['status']}

Sebep:
{", ".join(d['reasons'])}

Karar:
Dip radar.
Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir.
""".strip()


def format_signal(symbol, d, funding, btc_status, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")

    if module == "SAFE":
        title = "SAFE LONG"
        body = f"""
Guven: {d['confidence']}/100
Giris: {d['entry']:.8f}
Stop: {d['stop']:.8f}
TP1: {d['tp1']:.8f}
TP2: {d['tp2']:.8f}
TP3: {d['tp3']:.8f}
Risk: %{d['risk_pct']:.2f}

3m Degisim: %{d['change_3m']:.2f}
15m RSI: {d['rsi15']:.2f}
15m Trend: {"YUKARI" if d['trend_up'] else "ZAYIF"}
15m MACD: {"YUKARI" if d['macd_bull'] else "ZAYIF"}
5m Breakout: {"GUCLU" if d['strong_breakout'] else "ZAYIF"}
"""
        decision = "Onayli long adayi. Stop sart, FOMO yok."

    elif module == "MOMENTUM":
        title = "MOMENTUM CONTINUE"
        body = f"""
Ilk Fiyat: {d['first_price']:.8f}
Simdiki Fiyat: {d['price']:.8f}
Ilk Sinyalden Sonra: %{d['price_gain_from_first']:.2f}
Sure: {d['age_min']:.1f} dk
Para Buyume: {d['money_growth']:.2f}x
Hacim Gucu Buyume: {d['power_growth']:.2f}x
"""
        decision = "Para devam etti ve momentum guclendi. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    elif module in ("MONEY", "MONEY_ACCEL"):
        title = "MONEY ACCELERATION" if module == "MONEY_ACCEL" else "MONEY CONTINUE"
        body = f"""
Ilk Fiyat: {d['first_price']:.8f}
Simdiki Fiyat: {d['price']:.8f}
Ilk Sinyalden Sonra: %{d['price_gain_from_first']:.2f}
Sure: {d['age_min']:.1f} dk
Ilk Para Etkisi: {d['first_money_impact']:.2f}x
Para Buyume: {d['money_growth']:.2f}x
Ilk Hacim Gucu: {d['first_volume_power']:.2f}
Hacim Gucu Buyume: {d['power_growth']:.2f}x
"""
        decision = "Ayni coine para girmeye devam ediyor."

    elif module == "DIP":
        title = "BIG DIP RADAR"
        body = f"""
Dip Skoru: {d['score']}/18
Alt Fitil: %{d['lower_wick'] * 100:.1f}
24s Dipten Uzaklik: %{d.get('dist_from_low', 0):.2f}
"""
        decision = "Dip radar. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    elif module == "SWEEP":
        title = "LIQUIDITY SWEEP WATCH"
        body = f"""
Sweep Skoru: {d['score']}/21
15m Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Alt Fitil: %{d.get('lower_wick', 0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio', 0) * 100:.1f}
OBV Donus: {"VAR" if d.get("obv_up") else "YOK"}
MACD Toparlanma: {"VAR" if d.get("macd_turn") else "YOK"}
"""
        decision = "15m alt Bollinger igne + bant icine donus. Direkt long degil; 5m/15m retest takip."

    elif module == "TREND_BUILDUP":
        title = "SESSIZ TREND BUILDUP"
        body = f"""
6s Yukselis: %{d.get('price_change_6h', 0):.2f}
12s Yukselis: %{d.get('price_change_12h', 0):.2f}
24s Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Higher Low: {d.get('higher_low_count', 0)}
Higher High: {d.get('higher_high_count', 0)}
EMA21 Ustu Mum: {d.get('close_above_ema21_count', 0)}/12
OBV Birikim: {"VAR" if d.get("obv_up") else "YOK"}
MACD Toparlanma: {"VAR" if d.get("macd_turn") else "YOK"}
"""
        decision = "Sessiz trend radari. Ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    elif module == "HISTORY_BUILDUP":
        title = "HISTORY BUILDUP"
        body = f"""
Radar Hafiza Puani: {d.get('history_points', 0)}
Radar Hafiza Modulleri: {d.get('history_text', 'YOK')}
Hafiza Suresi: {d.get('history_age_min', 0):.1f} dk
Ilk Hafiza Fiyati: {d.get('history_first_price', 0):.8f}
Hafizadan Sonra: %{d.get('history_price_gain', 0):.2f}
Max Para Etkisi: {d.get('history_money_max', 0):.2f}x
Max Hacim Gucu: {d.get('history_power_max', 0):.2f}
Money Memory Bonus: {"VAR" if d.get("money_memory_bonus") else "YOK"}
Para Hafiza 60dk: {int(d.get('money_mem_60m', 0))} USDT
Para Hafiza 30dk: {int(d.get('money_mem_30m', 0))} USDT
Para Hafiza 15dk: {int(d.get('money_mem_15m', 0))} USDT
Para Dalga Sayisi: {d.get('money_wave_count', 0)}
Toplam Market Etki 60dk: %{d.get('money_market_60m', 0):.3f}
Fast Money Hafiza: {"VAR" if d.get("fast_money_bonus") else "YOK"}
Ana Kanal Tekrar 60dk: {d.get('main_signal_count_60m', 0)}
Ana Kanal Tekrar 120dk: {d.get('main_signal_count_120m', 0)}
Memory Re-Entry: {"VAR" if d.get("memory_reentry") else "YOK"}
Second Wave: {"VAR" if d.get("second_wave_bonus") else "YOK"}
"""
        decision = "Radar hafizasi ve para hafizasi guclendi. AL icin Elite kapisi beklenir."

    else:
        title = "EARLY RADAR"
        body = f"""
Radar Skoru: {d['score']}/18
1H Hacim Artisi: {d['vol_ratio_1h']:.2f}x
15m Hacim Artisi: {d['vol_ratio_15m']:.2f}x
1H USDT Hacim: {int(d['usdt_vol_1h'])} USDT
15m USDT Hacim: {int(d['usdt_vol_15m'])} USDT
24s Dipten Uzaklik: %{d['dist_from_low']:.2f}
Bollinger: {"Aciliyor" if d['bb_expanding'] else "Henuz zayif"}
"""
        decision = "Takibe al. Bu ana kanal izleme mesajidir. AL icin ELITE AL ONAY beklenir."

    reasons = d.get("reasons") or d.get("continue_reasons") or d.get("momentum_reasons") or []
    support_text = ", ".join(support_modules) if support_modules else "YOK"

    return f"""
{BOT_NAME}

Mod: {title}
Coin: {symbol}

RS Skoru: {d.get('rs', 0):.1f}/100
Skor: {d.get('score', 0)}
Fiyat: {d.get('price', 0):.8f}

Hacim Artisi: {d.get('vol_ratio', d.get('vol_ratio_1h', 0)):.2f}x
USDT Hacim: {int(d.get('usdt_vol', d.get('usdt_vol_1h', 0)))} USDT
Para Etkisi: {d.get('money_impact', 0):.2f}x
Hacim Gucu: {d.get('volume_power', 0):.2f}
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20
RSI: {d.get('rsi', d.get('rsi15', 0)):.2f}

{body}

BTC: {btc_status}
Funding: {funding['rate']:.6f}
{funding['status']}

Ek Gecen Radarlar:
{support_text}

Sebep:
{", ".join(reasons)}

Karar:
Radar Manager tum filtreleri taradi. En guclu sonuc bu mesajdir.
{decision}
""".strip()



def early_counter_key(symbol):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{symbol}_{today}"


def can_send_early_today(symbol):
    key = early_counter_key(symbol)
    return early_daily_counter.get(key, 0) < EARLY_MAX_PER_SYMBOL_PER_DAY


def mark_early_sent_today(symbol):
    key = early_counter_key(symbol)
    early_daily_counter[key] = early_daily_counter.get(key, 0) + 1


def cleanup_early_daily_counter():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    old_keys = [k for k in early_daily_counter if not k.endswith("_" + today)]
    for k in old_keys:
        early_daily_counter.pop(k, None)


def select_best_signal(signals):
    if not signals:
        return None

    return sorted(
        signals,
        key=lambda x: (x.get("priority", 0), x.get("score", 0)),
        reverse=True
    )[0]



sent_elite = {}

ELITE_MIN_SCORE = 88
ELITE_COOLDOWN = 6 * 60 * 60
ELITE_DAILY_LIMIT = 25
elite_daily_counter = {}


def radar_combo_score(best, support_modules=None):
    support_modules = support_modules or []
    modules = [best.get("module", "UNKNOWN")] + support_modules
    weights = {
        "SAFE": 3,
        "MONEY_ACCEL": 3,
        "MONEY": 2,
        "SWEEP": 3,
        "FAST_LIQUIDITY_SWEEP": 4,
        "DIP": 2,
        "EARLY": 1,
        "MOMENTUM": 0,
        "TREND_BUILDUP": 2,
        "HISTORY_BUILDUP": 3,
        "PRE_ROCKET_SQUEEZE": 4,
    }
    return sum(weights.get(m, 0) for m in modules), len(set(modules))


def late_rise_pullback_risk(d, support_modules=None):
    """
    V21 GEC YUKSELIS KORUMASI:
    SYN tipi sinyallerde bot trendi dogru gorur ama AL sinyali tepeden geri cekilme
    baslarken gelebilir. Bu fonksiyon, yukselis coktan olmus + tek radar + zayif
    anlik para durumunda Elite AL kapisini kapatir.
    """
    support_modules = support_modules or []
    if not d:
        return False, "OK"

    module = d.get("module", "UNKNOWN")
    if module not in ("TREND_BUILDUP", "MOMENTUM", "HISTORY_BUILDUP", "MONEY_ACCEL"):
        return False, "OK"

    combo_score, radar_count = radar_combo_score(d, support_modules)
    rise_6h = float(d.get("price_change_6h", 0) or 0)
    rise_12h = float(d.get("price_change_12h", 0) or 0)
    dist_from_low = float(d.get("dist_from_low", 0) or 0)
    pullback_from_high = float(d.get("pullback_from_high", 0) or 0)

    effective_money = max(float(d.get("money_impact", 0) or 0), float(d.get("effective_money_impact", 0) or 0))
    effective_power = max(float(d.get("volume_power", 0) or 0), float(d.get("effective_volume_power", 0) or 0))
    effective_market = max(float(d.get("market_impact_pct", 0) or 0), float(d.get("effective_market_impact_pct", 0) or 0))

    strong_exception = (
        radar_count >= 2
        and (
            bool(d.get("memory_reentry"))
            or bool(d.get("money_memory_bonus"))
            or bool(d.get("main_repeat_buildup"))
            or bool(d.get("repeat_force"))
            or bool(d.get("history_force"))
        )
        and (effective_money >= 2.4 or effective_power >= 6.0 or effective_market >= 3.0)
    )

    if strong_exception:
        return False, "OK_STRONG_MEMORY"

    # Sert blok: hem 6s yukselis hem dip mesafesi asiri ise, coin artik erken AL degildir.
    if rise_6h >= LATE_RISE_HARD_6H and dist_from_low >= LATE_RISE_HARD_DIST:
        return True, "GEC_YUKSELIS_HARD_BLOCK"

    # Tek radar TREND/MOMENTUM, son 6 saatte fazla gitmisse Elite yerine izleme kalsin.
    if radar_count <= 1 and rise_6h >= LATE_RISE_MAX_6H_FOR_SINGLE_RADAR:
        return True, "GEC_YUKSELIS_TEK_RADAR"

    # Dipten cok uzak + radar destegi az ise yeni AL icin gec kalmis olabilir.
    if radar_count <= 1 and dist_from_low >= LATE_RISE_MAX_DIST_FROM_LOW:
        return True, "DIPTEN_COK_UZAK_TEK_RADAR"

    # Tepe sonrasi geri cekilme baslamis, ama sistem hala trend devam saniyorsa blokla.
    if pullback_from_high >= LATE_RISE_PULLBACK_FROM_HIGH_BLOCK and rise_6h >= 10 and radar_count <= 1:
        return True, "TEPEDEN_GERI_CEKILME"

    # 12s yukselis de cok yuksekse ve para kalitesi orta ise Elite yerine Gold/Hazirlik kalsin.
    if rise_12h >= 18 and effective_money < 2.2 and effective_power < 5.0 and radar_count <= 1:
        return True, "12S_GEC_TREND"

    return False, "OK"


def elite_score_signal(d, support_modules=None):
    """
    V8 Elite puanlama + OI destegi:
    Amaç her sinyali 100 yapmak değil; SPX/BIO gibi saldırı sinyali ile
    LUMIA/EDEN tipi sınır sinyali ayırmak.
    """
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")

    score = 0
    rs = d.get("rs", 0)
    money_impact = max(d.get("money_impact", 0), d.get("effective_money_impact", 0))
    volume_power = max(d.get("volume_power", 0), d.get("effective_volume_power", 0))
    price_gain = d.get("price_gain_from_first", 0)
    money_growth = d.get("money_growth", 1)
    power_growth = d.get("power_growth", 1)
    rsi_value = d.get("rsi", d.get("rsi15", 0))
    combo_score, radar_count = radar_combo_score(d, support_modules)
    market_impact_pct = max(d.get("market_impact_pct", 0), d.get("effective_market_impact_pct", 0))

    memory_reentry_ok = bool(d.get("memory_reentry"))
    second_wave_ok = bool(d.get("second_wave_bonus"))
    repeat_force_ok = bool(d.get("repeat_force"))
    history_force_ok = bool(d.get("history_force"))
    main_repeat_ok = bool(d.get("main_repeat_buildup"))
    money_memory_ok = bool(d.get("money_memory_bonus"))
    fomo_exception = (memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok or main_repeat_ok or money_memory_ok) and d.get("money_gain_from_first", 0) <= 12
    momentum_reload_ok = (
        module == "MOMENTUM"
        and ("MONEY_ACCEL" in support_modules or "MONEY" in support_modules or second_wave_ok or memory_reentry_ok or repeat_force_ok)
        and money_impact >= RELOAD_MIN_MONEY
        and volume_power >= RELOAD_MIN_POWER
        and market_impact_pct >= RELOAD_MIN_MARKET
        and rsi_value <= 72
    )

    # OI destegi: para/hacim long tarafindan mi geliyor ayirmaya calisir.
    if d.get("oi_strong_long_supported"):
        score += 12
    elif d.get("oi_long_supported"):
        score += 7
    elif d.get("oi_short_cover"):
        score -= 10
    elif d.get("oi_weak"):
        score -= 5

    # V13 Delta / Taker Flow destegi:
    # AIO tipi "OI long destekli ama Net Delta satici baskin" sinyallerini daha sert cezalandirir.
    if d.get("strong_buyer_dominant"):
        score += 14
    elif d.get("buyer_dominant"):
        score += 8
    elif d.get("strong_seller_dominant"):
        score -= 30
    elif d.get("seller_dominant"):
        score -= 18

    # Net delta negatifse para var ama anlik emir akisi satici tarafta olabilir.
    # Bu durumda Elite skoru yapay olarak 100'e sisirilmesin.
    if d.get("net_delta_15m", 0) < 0:
        score -= 6
    if d.get("delta_ratio_15m", 0) <= -8:
        score -= 6

    # V12 Fast Money Bonus: ani para + hacim + market etki birlikteyse ekstra kalite puani.
    if d.get("fast_money_bonus"):
        score += 3

    # Market etkisi: yüzdelik değer doğrudan puanlanır.
    if market_impact_pct >= 10:
        score += 18
    elif market_impact_pct >= 3:
        score += 15
    elif market_impact_pct >= 1:
        score += 11
    elif market_impact_pct >= 0.35:
        score += 7
    elif market_impact_pct >= 0.10:
        score += 4

    # RS iyi ama tek başına karar verdirmez.
    if rs >= 85:
        score += 10
    elif rs >= 75:
        score += 7
    elif rs >= 65:
        score += 4

    # Anlık para kalitesi.
    if money_impact >= 10:
        score += 22
    elif money_impact >= 5:
        score += 19
    elif money_impact >= 2.5:
        score += 16
    elif money_impact >= 2.0:
        score += 13
    elif money_impact >= 1.7:
        score += 9
    elif money_impact >= 1.45:
        score += 5

    if volume_power >= 100:
        score += 24
    elif volume_power >= 50:
        score += 21
    elif volume_power >= 15:
        score += 18
    elif volume_power >= 8:
        score += 15
    elif volume_power >= 5:
        score += 12
    elif volume_power >= 3.5:
        score += 8
    elif volume_power >= 2.8:
        score += 4

    # Mod katsayısı: SAFE en güçlü; MONEY_ACCEL tek başına 100 yapmasın.
    if module == "SAFE":
        score += 22
    elif module == "MONEY_ACCEL":
        score += 14
    elif module == "FAST_LIQUIDITY_SWEEP":
        score += 20
    elif module == "SWEEP":
        score += 17
    elif module == "DIP":
        score += 11
    elif module == "MONEY":
        score += 7
    elif module == "TREND_BUILDUP":
        score += 15
    elif module == "HISTORY_BUILDUP":
        score += 17
    elif module == "PRE_ROCKET_SQUEEZE":
        score += 22
    elif module == "MOMENTUM":
        # V18: BLESS tipi Momentum + MoneyAccel reload yapisi artik cezalandirilmaz.
        score += 8 if momentum_reload_ok else -12
    elif module == "EARLY":
        score += 4

    # Destek radarlar.
    if "SAFE" in support_modules:
        score += 12
    if "MONEY_ACCEL" in support_modules or "MONEY" in support_modules:
        score += 8
    if "EARLY" in support_modules:
        score += 4
    if "FAST_LIQUIDITY_SWEEP" in support_modules:
        score += 10
    if "SWEEP" in support_modules:
        score += 8
    if "DIP" in support_modules:
        score += 5
    if "MOMENTUM" in support_modules:
        score -= 3
    if "TREND_BUILDUP" in support_modules:
        score += 7
    if "HISTORY_BUILDUP" in support_modules:
        score += 8
    if "PRE_ROCKET_SQUEEZE" in support_modules:
        score += 12

    if d.get("pre_rocket_squeeze"):
        score += PRE_ROCKET_ELITE_BONUS

    if combo_score >= 7:
        score += 12
    elif combo_score >= 5:
        score += 9
    elif combo_score >= 4:
        score += 5

    # Fiyat henüz kaçmadıysa bonus, kaçtıysa ceza.
    if 0.4 <= price_gain <= 3.5:
        score += 9
    elif 3.5 < price_gain <= 5.0:
        score += 4
    elif price_gain > 6:
        score -= 20

    # Büyüme var ama mutlak kalite yoksa tek başına yeterli olmasın.
    if money_growth >= 3.0:
        score += 7
    elif money_growth >= 1.35:
        score += 5
    elif money_growth >= 1.15:
        score += 3

    if power_growth >= 5.0:
        score += 7
    elif power_growth >= 1.5:
        score += 5
    elif power_growth >= 1.2:
        score += 3

    # Para hafızası / radar hafızası: yavaş yükselenleri korur.
    if d.get("money_memory_bonus"):
        score += 10
    if d.get("money_wave_count", 0) >= 5:
        score += 7
    elif d.get("money_wave_count", 0) >= 3:
        score += 4
    if d.get("money_mem_60m", 0) >= 1_000_000:
        score += 8
    elif d.get("money_mem_60m", 0) >= 500_000:
        score += 6
    elif d.get("money_mem_60m", 0) >= 250_000:
        score += 3
    if d.get("history_points", 0) >= 40:
        score += 10
    elif d.get("history_points", 0) >= 25:
        score += 7
    elif d.get("history_points", 0) >= 18:
        score += 4

    # V15: Ana kanal tekrar hafizasi + Memory Re-Entry + Second Wave.
    if d.get("main_signal_bonus", 0) > 0:
        score += int(d.get("main_signal_bonus", 0))
    if d.get("memory_reentry"):
        score += 12
    if d.get("second_wave_bonus"):
        score += 12
    if d.get("main_repeat_buildup"):
        score += 8
    if d.get("repeat_force") or d.get("history_force"):
        score += V17_RELOAD_ELITE_BONUS

    # V18: BLESS / COHR terfi katmani.
    if momentum_reload_ok:
        score += V18_MOMENTUM_RELOAD_BONUS
    if module == "HISTORY_BUILDUP" and (money_memory_ok or memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok):
        score += V18_HISTORY_MEMORY_BONUS
    if main_repeat_ok or d.get("main_signal_count_120m", 0) >= 5:
        score += V18_MAIN_REPEAT_BONUS

    # V15: Zayif para etkili Elite'ler sismasin. Hafiza varsa ceza daha yumusak kalir.
    if money_impact < 1.8 and volume_power < 3.0 and market_impact_pct < 0.10:
        score -= 14 if not (d.get("money_memory_bonus") or d.get("memory_reentry")) else 6
    elif money_impact < 1.5 and volume_power < 2.5:
        score -= 8

    # RSI: sağlıklı bölge bonus, aşırı bölge ceza.
    if 45 <= rsi_value <= 66:
        score += 8
    elif 35 <= rsi_value < 45:
        score += 3
    elif 66 < rsi_value <= 70:
        score += 2
    elif rsi_value >= 76:
        score -= 20
    elif rsi_value >= 72:
        score -= 10

    # MONEY_ACCEL için ekstra denge: mutlak para yoksa büyüme puanı fazla şişirmesin.
    if module == "MONEY_ACCEL":
        if money_impact < 2.0 and volume_power < 4.0 and market_impact_pct < 1.0:
            score -= 14
        if money_impact < 1.8 and volume_power < 3.5:
            score -= 10

    # V9: HISTORY_BUILDUP tek dalga para ile 100/100 olmasın.
    # MAGMA gibi gidenler Elite kalabilir; fakat GOLD/100 kalitesi için para dalgası ve hafıza şartı aranır.
    if module == "HISTORY_BUILDUP":
        strong_history_memory = money_memory_ok or memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok
        if not d.get("money_memory_bonus") and not strong_history_memory:
            score -= 10
        if d.get("money_wave_count", 0) < 3 and not strong_history_memory:
            score -= 10
        if d.get("money_wave_count", 0) <= 1 and not strong_history_memory:
            score -= 8
        if d.get("history_points", 0) < 20 and not strong_history_memory:
            score -= 6

    # V9: OI karar ağırlığı artırıldı.
    if d.get("oi_strong_long_supported"):
        score += 3
    elif d.get("oi_long_supported"):
        score += 2
    elif d.get("oi_short_cover"):
        score -= 5
    elif d.get("oi_weak"):
        score -= 3

    # V19 Destek/Direnc puani:
    # Dirence cok yakin sinyal 100/100'e sismesin; kirilim veya destek ustu ise odullendir.
    score += int(d.get("sr_bonus", 0) or 0)
    score += int(d.get("sr_penalty", 0) or 0)

    late_risk, late_reason = late_rise_pullback_risk(d, support_modules)
    if late_risk:
        score -= LATE_RISE_SCORE_PENALTY
        d["late_rise_block_reason"] = late_reason

    if is_fomo_block(d) and not fomo_exception:
        score -= 30

    return max(0, min(100, int(round(score))))


def is_elite_al_candidate(best, support_modules=None):
    support_modules = support_modules or []
    module = best.get("module", "UNKNOWN")
    combo_score, radar_count = radar_combo_score(best, support_modules)

    money_memory_ok = bool(best.get("money_memory_bonus"))
    history_ok = best.get("history_points", 0) >= 16
    memory_reentry_ok = bool(best.get("memory_reentry"))
    second_wave_ok = bool(best.get("second_wave_bonus"))
    main_repeat_ok = bool(best.get("main_repeat_buildup"))
    repeat_force_ok = bool(best.get("repeat_force"))
    history_force_ok = bool(best.get("history_force"))
    effective_money = max(best.get("money_impact", 0), best.get("effective_money_impact", 0))
    effective_power = max(best.get("volume_power", 0), best.get("effective_volume_power", 0))
    effective_market = max(best.get("market_impact_pct", 0), best.get("effective_market_impact_pct", 0))

    fomo_exception = (memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok) and best.get("money_gain_from_first", 0) <= 12
    if is_fomo_block(best) and not fomo_exception:
        return False, "FOMO_BLOCK"

    # V21: SYN tipi gec trend / tepeden geri cekilme korumasi.
    late_risk, late_reason = late_rise_pullback_risk(best, support_modules)
    if late_risk:
        return False, late_reason

    # V19 Destek/Direnc kapisi:
    # Fiyat dirence cok yakin ve henuz kirmamissa Elite AL yerine izleme kalsin.
    # Cok guclu para/market etkisi varsa tamamen bloklama, skor cezasina birak.
    sr_close = (
        best.get("sr_ok")
        and not best.get("resistance_broken")
        and 0 <= best.get("resistance_distance_pct", 999) <= SR_TOO_CLOSE_BLOCK_PCT
    )
    sr_strong_exception = (
        effective_market >= SR_STRONG_EXCEPTION_MARKET
        or effective_power >= SR_STRONG_EXCEPTION_POWER
        or effective_money >= SR_STRONG_EXCEPTION_MONEY
        or best.get("support_near")
    )
    if sr_close and not sr_strong_exception and module not in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        return False, "DIRENC_COK_YAKIN"

    # V17: MOMENTUM tek basina AL degildi; fakat UB gibi para/hacim buyumesi asiri guclu ise
    # Reload/Second Wave olarak Elite kapisina girebilir.
    if module == "MOMENTUM":
        momentum_reload = (
            (effective_money >= RELOAD_MIN_MONEY and effective_power >= RELOAD_MIN_POWER and effective_market >= RELOAD_MIN_MARKET)
            or memory_reentry_ok
            or second_wave_ok
            or repeat_force_ok
        )
        if not momentum_reload:
            return False, "MOMENTUM_AL_DEGIL"

    if effective_money < 1.45 or effective_power < 2.8:
        if not (money_memory_ok or history_ok or memory_reentry_ok or second_wave_ok or main_repeat_ok or repeat_force_ok or history_force_ok or module == "TREND_BUILDUP"):
            return False, "PARA_ZAYIF"

    if not market_impact_ok(best):
        market_memory_exception = (
            money_memory_ok or memory_reentry_ok or second_wave_ok or main_repeat_ok or repeat_force_ok or history_force_ok
        ) and (best.get("money_market_60m", 0) >= 0.25 or effective_market >= 0.25 or best.get("money_mem_60m", 0) >= 250_000)
        if not market_memory_exception:
            return False, "MARKET_ETKI_ZAYIF"

    rsi_value = best.get("rsi", best.get("rsi15", 0))
    if rsi_value > 72 and not (module == "PRE_ROCKET_SQUEEZE" and rsi_value <= PRE_ROCKET_MAX_RSI):
        return False, "RSI_YUKSEK"

    # OI kontrolu: Veri varsa ve hareket short kapama gibi duruyorsa,
    # sadece cok guclu para/SAFE yapisi gecsin.
    if best.get("oi_short_cover"):
        strong_exception = (
            module == "SAFE"
            or best.get("money_impact", 0) >= 8
            or best.get("volume_power", 0) >= 50
            or best.get("market_impact_pct", 0) >= 10
        )
        if not strong_exception:
            return False, "OI_SHORT_KAPAMA_RISKI"

    # V13 Delta kontrolu:
    # AIO orneginde gordugumuz gibi market etki cok yuksek olsa bile Net Delta satici baskinsa
    # bu para fiyatı yukari tasimayabilir. Bu yuzden market impact tek basina istisna degildir.
    if best.get("strong_seller_dominant"):
        if module not in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
            return False, "GUCLU_SATICI_DELTA_BASKIN"

    if best.get("seller_dominant") and best.get("net_delta_15m", 0) < 0:
        delta_exception = (
            module in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP")
            or (
                best.get("volume_power", 0) >= 60
                and best.get("money_impact", 0) >= 6
                and best.get("oi_strong_long_supported")
                and best.get("net_delta_1h", 0) >= 0
            )
        )
        if not delta_exception:
            return False, "SATICI_DELTA_BASKIN"

    # Binance karar botu: en az guclu bir ana radar veya 2 destek ister.
    if module == "SAFE" and combo_score >= 3:
        return True, "SAFE_ONAY"

    # V6 MONEY_ACCEL kalite kapisi:
    # SPX gibi canavar para patlamasini kacirmasin,
    # LUMIA gibi sadece buyume orani yuksek ama mutlak para zayif olanlari elesin.
    if module == "MONEY_ACCEL" and combo_score >= 3:
        monster_money = (
            effective_money >= 8.0
            or effective_power >= 50.0
            or effective_market >= 10.0
        )
        normal_money_quality = (
            effective_money >= 2.5
            or effective_power >= 5.0
            or (
                effective_market >= 1.0
                and effective_money >= 1.8
                and effective_power >= 3.5
            )
        )
        supported_money_quality = (
            (radar_count >= 2 or money_memory_ok or history_ok or repeat_force_ok)
            and effective_money >= 1.8
            and effective_power >= 3.5
            and effective_market >= 0.7
        )
        if monster_money or normal_money_quality or supported_money_quality:
            return True, "MONEY_ACCEL_ONAY"
        return False, "MONEY_ACCEL_PARA_KALITESI_ZAYIF"

    if module == "SWEEP" and combo_score >= 4 and best.get("lower_wick", 0) >= 0.45:
        return True, "SWEEP_ONAY"

    # V14: BSB tipi hızlı likidite süpürme. Tek destekle bile güçlü toparlanma varsa Elite'e yaklaşsın.
    if module == "FAST_LIQUIDITY_SWEEP":
        strong_fast_sweep = (
            best.get("recovery_ratio", 0) >= 0.65
            and best.get("lower_wick", 0) >= 0.30
            and best.get("volume_power", 0) >= 1.6
            and best.get("money_impact", 0) >= 1.05
            and best.get("dist_from_low", 999) <= 10
        )
        if strong_fast_sweep and (combo_score >= 4 or best.get("market_impact_pct", 0) >= 0.05):
            return True, "FAST_LIQUIDITY_SWEEP_ONAY"

    if module == "DIP" and combo_score >= 4 and best.get("lower_wick", 0) >= 0.50:
        return True, "DIP_ONAY"

    if module == "TREND_BUILDUP" and (
        radar_count >= 2
        or money_memory_ok
        or (best.get("higher_low_count", 0) >= 3 and best.get("obv_up") and best.get("macd_turn"))
    ):
        return True, "SESSIZ_TREND_ONAY"

    if module == "HISTORY_BUILDUP" and (
        history_ok
        and best.get("history_age_min", 0) >= 25
        and best.get("history_price_gain", 0) <= 10
        and (radar_count >= 2 or money_memory_ok or memory_reentry_ok or second_wave_ok or main_repeat_ok or repeat_force_ok or history_force_ok)
    ):
        return True, "HISTORY_BUILDUP_ONAY"

    if memory_reentry_ok and (radar_count >= 2 or money_memory_ok or history_ok):
        return True, "MEMORY_REENTRY_ONAY"

    if second_wave_ok and (best.get("money_impact", 0) >= 1.6 or best.get("volume_power", 0) >= 3.0):
        return True, "SECOND_WAVE_ONAY"

    if main_repeat_ok and (effective_money >= 1.7 or effective_market >= 0.10 or best.get("money_mem_60m", 0) >= 500_000):
        return True, "ANA_KANAL_TEKRAR_ONAY"

    if module == "MOMENTUM" and (
        effective_money >= RELOAD_MIN_MONEY
        and effective_power >= RELOAD_MIN_POWER
        and effective_market >= RELOAD_MIN_MARKET
        and (best.get("money_growth", 1) >= 3 or best.get("power_growth", 1) >= 8 or best.get("money_mem_60m", 0) >= 750_000)
    ):
        return True, "MOMENTUM_RELOAD_ONAY"

    if (repeat_force_ok or history_force_ok) and (money_memory_ok or best.get("money_mem_60m", 0) >= 750_000):
        return True, "REPEAT_MONEY_FORCE_ONAY"

    return False, "RADAR_KOMBINASYON_YETERSIZ"



def gold_trend_guard(symbol, d):
    """
    V10 GOLD DUSUS KORUMASI:
    TRUST tipi tepe sonrasi satis baslamis coinler Gold olmasin.
    Elite normal kalabilir; sadece Gold etiketi iptal edilir.
    """
    if not symbol or not d:
        return True

    try:
        df15 = fetch_df(symbol, "15m", 80)
        if df15 is None or len(df15) < 5:
            return True

        last = df15.iloc[-1]
        prev = df15.iloc[-2]

        price = float(d.get("price", last.close) or last.close)
        ema9 = float(last.ema9)
        macd_hist = float(last.macd - last.macd_signal)
        macd_hist_prev = float(prev.macd - prev.macd_signal)
        rsi_now = float(last.rsi)
        rsi_prev = float(prev.rsi)
        obv_now = float(last.obv)
        obv_prev = float(prev.obv)

        macd_turn_down = macd_hist < macd_hist_prev
        rsi_drop_fast = (rsi_prev - rsi_now) >= 4.0
        obv_down = obv_now < obv_prev

        # GOLD icin anlik yon hala yukari olmali.
        if price < ema9:
            return False
        if macd_turn_down:
            return False
        if rsi_now < rsi_prev or rsi_drop_fast:
            return False
        if obv_down:
            return False

        return True
    except Exception as e:
        print("GOLD trend guard hata:", symbol, e, flush=True)
        return True


def is_elite_gold_signal(d, elite_score=0, support_modules=None, symbol=None):
    """
    V13 ELITE GOLD etiketi:
    V9 Gold filtresine ek olarak anlik dusus/geri cekilme korumasi eklendi.
    TRUST tipi tepe sonrasi satis yiyen coinler Gold olmaz.
    """
    support_modules = support_modules or []
    combo_score, radar_count = radar_combo_score(d, support_modules)
    module = d.get("module", "UNKNOWN")

    money_memory_bonus = bool(d.get("money_memory_bonus"))
    history_points = d.get("history_points", 0)
    waves = d.get("money_wave_count", 0)
    market_score = d.get("market_impact_score", 0)
    market_pct = d.get("market_impact_pct", 0)
    money_impact = d.get("money_impact", 0)
    volume_power = d.get("volume_power", 0)
    rsi_value = d.get("rsi", d.get("rsi15", 0))

    oi_long = bool(d.get("oi_long_supported") or d.get("oi_strong_long_supported"))
    oi_strong = bool(d.get("oi_strong_long_supported"))
    oi_bad = bool(d.get("oi_short_cover") or d.get("oi_weak"))
    delta_good = bool(d.get("buyer_dominant") or d.get("strong_buyer_dominant"))
    delta_bad = bool(d.get("seller_dominant") or d.get("strong_seller_dominant"))

    if is_fomo_block(d) or oi_bad or delta_bad or not (42 <= rsi_value <= 70):
        return False

    # 1) Birikimli GOLD: VELVET/HIGH/MAGMA tarzı radar+para hafızası.
    buildup_gold = (
        money_memory_bonus
        and history_points >= 20
        and waves >= 3
        and market_score >= 10
        and (oi_long or oi_strong)
        and (delta_good or d.get("net_delta_15m", 0) >= 0)
        and radar_count >= 2
        and elite_score >= 92
    )

    # 2) Agresif para GOLD: SPX/BIO tarzı anlık para saldırısı.
    attack_gold = (
        elite_score >= 95
        and (
            money_impact >= 5.0
            or volume_power >= 20.0
            or market_pct >= 3.0
        )
        and (oi_long or oi_strong or volume_power >= 50.0)
        and (delta_good or volume_power >= 50.0)
        and radar_count >= 2
        and module in ("SAFE", "MONEY_ACCEL", "HISTORY_BUILDUP", "TREND_BUILDUP", "FAST_LIQUIDITY_SWEEP", "PRE_ROCKET_SQUEEZE")
    )

    elite_gold = bool(buildup_gold or attack_gold)

    if elite_gold and not gold_trend_guard(symbol, d):
        return False

    return elite_gold

def format_elite_signal(symbol, d, elite_score, support_modules=None):
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    support_text = ", ".join(support_modules) if support_modules else "YOK"
    combo_score, radar_count = radar_combo_score(d, support_modules)
    levels = build_entry_levels(d)
    elite_gold = is_elite_gold_signal(d, elite_score, support_modules, symbol)
    title = "🔥 BINANCE ELITE GOLD AL ONAY" if elite_gold else "BINANCE ELITE AL ONAY"
    gold_note = "🔥 ELITE GOLD: VAR" if elite_gold else "ELITE GOLD: YOK"

    extra = ""
    if module in ("MONEY_ACCEL", "MONEY", "MOMENTUM"):
        extra = f"""
Ilk Fiyat: {d.get('first_price', 0):.8f}
Simdiki Fiyat: {d.get('price', 0):.8f}
Ilk Sinyalden Sonra: %{d.get('price_gain_from_first', 0):.2f}
Para Buyume: {d.get('money_growth', 1):.2f}x
Hacim Gucu Buyume: {d.get('power_growth', 1):.2f}x
Sure: {d.get('age_min', 0):.1f} dk
"""
    elif module in ("SWEEP", "FAST_LIQUIDITY_SWEEP"):
        extra = f"""
15m Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Alt Fitil: %{d.get('lower_wick', 0) * 100:.1f}
Mum Toparlanma: %{d.get('recovery_ratio', 0) * 100:.1f}
"""
    elif module == "PRE_ROCKET_SQUEEZE":
        extra = f"""
PRE-ROCKET SQUEEZE: VAR
BB Width: {d.get('bb_width', 0):.4f}
Yatay Kirilim: {"VAR" if d.get("range_break") else "YOK"}
Ust Bant Temasi: {"VAR" if d.get("upper_break") else "YOK"}
OBV Giris: {"VAR" if d.get("obv_up") else "YOK"}
MACD Donus: {"VAR" if d.get("macd_turn") else "YOK"}
"""
    elif module == "TREND_BUILDUP":
        extra = f"""
6s Yukselis: %{d.get('price_change_6h', 0):.2f}
12s Yukselis: %{d.get('price_change_12h', 0):.2f}
24s Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Higher Low: {d.get('higher_low_count', 0)}
Higher High: {d.get('higher_high_count', 0)}
EMA21 Ustu Mum: {d.get('close_above_ema21_count', 0)}/12
OBV Birikim: {"VAR" if d.get("obv_up") else "YOK"}
MACD Toparlanma: {"VAR" if d.get("macd_turn") else "YOK"}
"""
    elif module == "HISTORY_BUILDUP":
        extra = f"""
Radar Hafiza Puani: {d.get('history_points', 0)}
Radar Hafiza Modulleri: {d.get('history_text', 'YOK')}
Hafiza Suresi: {d.get('history_age_min', 0):.1f} dk
Ilk Hafiza Fiyati: {d.get('history_first_price', 0):.8f}
Hafizadan Sonra: %{d.get('history_price_gain', 0):.2f}
Max Para Etkisi: {d.get('history_money_max', 0):.2f}x
Max Hacim Gucu: {d.get('history_power_max', 0):.2f}
Money Memory Bonus: {"VAR" if d.get("money_memory_bonus") else "YOK"}
Para Hafiza 60dk: {int(d.get('money_mem_60m', 0))} USDT
Para Hafiza 30dk: {int(d.get('money_mem_30m', 0))} USDT
Para Hafiza 15dk: {int(d.get('money_mem_15m', 0))} USDT
Para Dalga Sayisi: {d.get('money_wave_count', 0)}
Toplam Market Etki 60dk: %{d.get('money_market_60m', 0):.3f}
Fast Money Hafiza: {"VAR" if d.get("fast_money_bonus") else "YOK"}
Ana Kanal Tekrar 60dk: {d.get('main_signal_count_60m', 0)}
Ana Kanal Tekrar 120dk: {d.get('main_signal_count_120m', 0)}
Memory Re-Entry: {"VAR" if d.get("memory_reentry") else "YOK"}
Second Wave: {"VAR" if d.get("second_wave_bonus") else "YOK"}
"""

    return f"""
{title}

Coin: {symbol}
Mod: {module}
Karar: AL
{gold_note}
Elite Giris Skoru: {elite_score}/100

Giris: {levels['entry']:.8f}
Stop: {levels['stop']:.8f}
TP1: {levels['tp1']:.8f}
TP2: {levels['tp2']:.8f}
TP3: {levels['tp3']:.8f}
Risk: %{levels['risk_pct']:.2f}
TP Sistemi: {levels.get('tp_system', 'RISK_KATLI')}
TP Referans: {levels.get('tp_reference', 'Stop mesafesi')}

Fiyat: {d.get('price', 0):.8f}
RS Skoru: {d.get('rs', 0):.1f}/100
Radar Skoru: {d.get('score', 0)}
Radar Sayisi: {radar_count}
Radar Kombinasyon Puani: {combo_score}

24s Hacim: {int(d.get('daily_quote_volume', 0))} USDT
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20

Para Etkisi: {d.get('money_impact', 0):.2f}x
Hacim Gucu: {d.get('volume_power', 0):.2f}
Market Etki: %{d.get('market_impact_pct', 0):.4f}
Market Etki Skoru: {d.get('market_impact_score', 0)}/20
RSI: {d.get('rsi', d.get('rsi15', 0)):.2f}
FOMO 15m: %{d.get('price_gain_15m', 0):.2f}
FOMO 30m: %{d.get('price_gain_30m', 0):.2f}
Gec Yukselis Kontrol: {d.get('late_rise_block_reason', 'OK')}

Destek: {d.get('support_level', 0):.8f}
Direnc: {d.get('resistance_level', 0):.8f}
Destek Mesafesi: %{d.get('support_distance_pct', 0):.2f}
Direnc Mesafesi: %{d.get('resistance_distance_pct', 0):.2f}
Direnc Durumu: {d.get('sr_status', 'SR VERI YOK')}
SR Puan Etkisi: {int(d.get('sr_bonus', 0) or 0) + int(d.get('sr_penalty', 0) or 0)}

OI 15m: %{d.get('oi_15m_pct', 0):.2f}
OI 1h: %{d.get('oi_1h_pct', 0):.2f}
OI Yorum: {d.get('oi_status', 'OI VERI YOK')}

Long Akisi 15m: {int(d.get('long_flow_15m', 0))} USDT
Short Akisi 15m: {int(d.get('short_flow_15m', 0))} USDT
Net Delta 15m: {int(d.get('net_delta_15m', 0))} USDT
Delta Orani 15m: %{d.get('delta_ratio_15m', 0):.2f}
Delta Yorum: {d.get('delta_status', 'DELTA VERI YOK')}
Fast Money Bonus: {"VAR" if d.get("fast_money_bonus") else "YOK"}
Ana Kanal Tekrar 60dk: {d.get('main_signal_count_60m', 0)}
Ana Kanal Tekrar 120dk: {d.get('main_signal_count_120m', 0)}
Memory Re-Entry: {"VAR" if d.get("memory_reentry") else "YOK"}
Second Wave: {"VAR" if d.get("second_wave_bonus") else "YOK"}

Ek Gecen Radarlar:
{support_text}

{extra}

Not:
Bu mesaj Binance karar botunda AL kapisindan gecen sinyal icin atilir.
Momentum tek basina AL degildir. FOMO / gec giris / yuksek RSI elendi.
""".strip()



def elite_day_key():
    return datetime.utcnow().strftime("%Y-%m-%d")

def cleanup_elite_daily_counter():
    today = elite_day_key()
    for k in list(elite_daily_counter.keys()):
        if not k.startswith(today + "_"):
            elite_daily_counter.pop(k, None)

def can_send_elite_today():
    cleanup_elite_daily_counter()
    today = elite_day_key()
    sent_count = sum(v for k, v in elite_daily_counter.items() if k.startswith(today + "_"))
    return sent_count < ELITE_DAILY_LIMIT

def mark_elite_sent_today(symbol):
    cleanup_elite_daily_counter()
    key = elite_day_key() + "_" + symbol
    elite_daily_counter[key] = elite_daily_counter.get(key, 0) + 1

def send_elite_signal(symbol, best, support):
    if not ELITE_CHAT_ID:
        return False

    # V19: Elite karari verilmeden once destek/direnc baglamini ekle.
    best = attach_support_resistance_context(symbol, best)

    ok, reason = is_elite_al_candidate(best, support)
    if not ok:
        print("ELITE BLOCK:", symbol, best.get("module"), reason, flush=True)
        return False

    elite_score = elite_score_signal(best, support)
    if elite_score < ELITE_MIN_SCORE:
        print("ELITE SCORE LOW:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
        return False

    if not can_send_elite_today():
        print("ELITE DAILY LIMIT:", ELITE_DAILY_LIMIT, flush=True)
        return False

    # V15: Normal Elite ayni coin icin sakin kalsin;
    # fakat Memory Re-Entry / Second Wave ayri ve daha kisa cooldown ile yeniden uyarabilsin.
    if best.get("memory_reentry") or best.get("second_wave_bonus") or best.get("main_repeat_buildup"):
        key = symbol + "_ELITE_REENTRY"
        cooldown = ELITE_REENTRY_COOLDOWN
    else:
        key = symbol + "_ELITE_AL"
        cooldown = ELITE_COOLDOWN
    if not can_send(sent_elite, key, cooldown):
        return False

    elite_gold = is_elite_gold_signal(best, elite_score, support, symbol)
    send_telegram(format_elite_signal(symbol, best, elite_score, support), ELITE_CHAT_ID)
    mark_elite_sent_today(symbol)
    print("ELITE GOLD SEND:" if elite_gold else "ELITE AL SEND:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
    return True
def send_selected_signal(symbol, signals, funding, btc_status):
    if not signals:
        return False

    record_main_signal_memory(symbol, signals)
    main_mem = main_signal_memory_summary(symbol)
    for _sig in signals:
        if _sig:
            _sig.update(main_mem)
            _sig.update(money_memory_summary(symbol))
            apply_reentry_second_wave_flags(_sig)

    best = select_best_signal(signals)
    support = [s["module"] for s in signals if s["module"] != best["module"]]

    cooldown_map = {
        "SAFE": (sent_safe, COOLDOWN_SAFE),
        "MOMENTUM": (sent_momentum_continue, COOLDOWN_MOMENTUM_CONTINUE),
        "MONEY": (sent_money_continue, COOLDOWN_MONEY_CONTINUE),
        "MONEY_ACCEL": (sent_money_continue, COOLDOWN_MONEY_CONTINUE),
        "DIP": (sent_dip, COOLDOWN_DIP),
        "SWEEP": (sent_sweep_watch, COOLDOWN_SWEEP_WATCH),
        "FAST_LIQUIDITY_SWEEP": (sent_fast_liquidity_sweep, COOLDOWN_FAST_LIQUIDITY_SWEEP),
        "EARLY": (sent_early, COOLDOWN_EARLY),
        "TREND_BUILDUP": (sent_trend_buildup, COOLDOWN_TREND_BUILDUP),
        "HISTORY_BUILDUP": (sent_history_buildup, COOLDOWN_HISTORY_BUILDUP),
        "PRE_ROCKET_SQUEEZE": (sent_pre_rocket_squeeze, COOLDOWN_PRE_ROCKET_SQUEEZE),
    }

    cache, cooldown = cooldown_map.get(best["module"], (sent_early, COOLDOWN_EARLY))
    key = symbol + "_" + best["module"]

    if best["module"] == "EARLY" and not can_send_early_today(symbol):
        print("EARLY DAILY LIMIT:", symbol, "Limit:", EARLY_MAX_PER_SYMBOL_PER_DAY, flush=True)
        return False

    if can_send(cache, key, cooldown):
        send_telegram(format_signal(symbol, best, funding, btc_status, support))

        if best["module"] == "EARLY":
            mark_early_sent_today(symbol)

        send_elite_signal(symbol, best, support)
        print("SEND:", symbol, best["module"], "Score:", best.get("score"), "Support:", support, flush=True)
        return True

    print("COOLDOWN:", symbol, best["module"], "Support:", support, flush=True)
    return False


def analyze(item, btc_ok, btc_status):
    symbol = item["symbol"]
    rs = item["rs_score"]
    funding = get_funding(symbol)

    try:
        signals = []
        oi_context = None

        early_ok, early_data = early_radar(symbol, rs)
        if early_data:
            early_data = attach_market_impact(early_data, item)
            update_money_state(symbol, early_data, "RADAR_DATA")
            update_money_memory(symbol, early_data)

        money_ok, money_data = money_continue_signal(symbol, early_data)
        if money_data:
            money_data = attach_market_impact(money_data, item)
            update_money_memory(symbol, money_data)

        momentum_ok, momentum_data = momentum_continue_signal(symbol, early_data)
        if momentum_data:
            momentum_data = attach_market_impact(momentum_data, item)
            update_money_memory(symbol, momentum_data)

        safe_ok, safe_data = safe_long(symbol, rs, btc_ok, funding)
        if safe_data:
            safe_data = attach_market_impact(safe_data, item)
            update_money_memory(symbol, safe_data)

        dip_ok, dip_data = big_dip_radar(symbol, rs)
        if dip_data:
            dip_data = attach_market_impact(dip_data, item)
            update_money_memory(symbol, dip_data)

        sweep_ok, sweep_data = liquidity_sweep_watch(symbol, rs)
        if sweep_data:
            sweep_data = attach_market_impact(sweep_data, item)
            update_money_memory(symbol, sweep_data)

        fast_sweep_ok, fast_sweep_data = fast_liquidity_sweep_signal(symbol, rs)
        if fast_sweep_data:
            fast_sweep_data = attach_market_impact(fast_sweep_data, item)
            update_money_memory(symbol, fast_sweep_data)

        pre_rocket_ok, pre_rocket_data = pre_rocket_squeeze_signal(symbol, rs)
        if pre_rocket_data:
            pre_rocket_data = attach_market_impact(pre_rocket_data, item)
            update_money_memory(symbol, pre_rocket_data)

        trend_ok, trend_data = trend_buildup_signal(symbol, rs)
        if trend_data:
            trend_data = attach_market_impact(trend_data, item)
            update_money_memory(symbol, trend_data)

        valid_for_history = []
        for ok_flag, data in [
            (early_ok, early_data),
            (money_ok, money_data),
            (momentum_ok, momentum_data),
            (safe_ok, safe_data),
            (dip_ok, dip_data),
            (sweep_ok, sweep_data),
            (fast_sweep_ok, fast_sweep_data),
            (pre_rocket_ok, pre_rocket_data),
            (trend_ok, trend_data),
        ]:
            if ok_flag and data:
                valid_for_history.append(data)

        record_radar_history(symbol, valid_for_history)
        history_ok, history_data = build_history_signal(symbol, rs, valid_for_history)
        if history_data:
            history_data = attach_market_impact(history_data, item)
            history_data.update(money_memory_summary(symbol))

        # V8: OI yorumunu tum aday sinyallere ekle.
        oi_ref = history_data or safe_data or money_data or trend_data or early_data or momentum_data or sweep_data or dip_data
        oi_price_gain = 0.0
        if oi_ref:
            oi_price_gain = oi_ref.get("price_gain_from_first", oi_ref.get("price_gain_15m", 0.0))
        oi_context = get_oi_context(symbol, oi_price_gain)
        taker_context = get_taker_flow_context(symbol)
        for _sig in [early_data, money_data, momentum_data, safe_data, dip_data, sweep_data, fast_sweep_data, pre_rocket_data, trend_data, history_data]:
            attach_oi_context(_sig, oi_context)
            attach_taker_flow_context(_sig, taker_context)

        if early_ok:
            signals.append(early_data)
        if money_ok:
            signals.append(money_data)
        if momentum_ok:
            signals.append(momentum_data)
        if safe_ok:
            signals.append(safe_data)
        if dip_ok:
            signals.append(dip_data)
        if sweep_ok:
            signals.append(sweep_data)
        if fast_sweep_ok:
            signals.append(fast_sweep_data)
        if pre_rocket_ok:
            signals.append(pre_rocket_data)
        if trend_ok:
            signals.append(trend_data)
        if history_ok:
            signals.append(history_data)

        if signals:
            sent = send_selected_signal(symbol, signals, funding, btc_status)
            if sent:
                return

        else:
            print(
                symbol,
                "RS:", round(rs, 1),
                "Funding:", funding["status"],
                "Early:", early_ok,
                "Money:", money_ok,
                "Momentum:", momentum_ok,
                "Safe:", safe_ok,
                "Dip:", dip_ok,
                "Sweep:", sweep_ok,
                "PreRocket:", pre_rocket_ok,
                "Trend:", trend_ok,
                "History:", history_ok,
                "MoneyState:", "VAR" if symbol in money_state else "YOK",
                "IC FILTRE",
                flush=True
            )

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)

def run_bot():
    send_telegram(f"{BOT_NAME} BASLADI. Radar Manager aktif.")
    print(BOT_NAME, "BASLADI", flush=True)

    while True:
        try:
            print("Tarama basladi:", datetime.now(), flush=True)

            btc_ok, btc_status = btc_filter()
            print("BTC:", btc_status, flush=True)

            cleanup_money_state()
            cleanup_radar_history()
            cleanup_money_memory()
            cleanup_main_signal_memory()

            universe = build_universe()
            print("Taranacak coin:", len(universe), "MoneyState:", len(money_state), flush=True)

            for item in universe:
                analyze(item, btc_ok, btc_status)
                time.sleep(0.20)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"Binance bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE FUTURES V16 Bot Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
