import os, time, threading, requests, ccxt
import pandas as pd
import numpy as np
from flask import Flask
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"
BOT_NAME = "BINANCE FUTURES EARLY DIP + PARA GIRISI BOT"

MAX_SYMBOLS = 160
SLEEP_SECONDS = 45

COOLDOWN_EARLY_DIP = 90 * 60
COOLDOWN_FLOW = 90 * 60
COOLDOWN_GOLD = 120 * 60
COOLDOWN_SHORT = 180 * 60

sent = {}

exchange = ccxt.binanceusdm({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {"defaultType": "future", "adjustForTimeDifference": True}
})


def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text, flush=True)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20
        )
    except Exception as e:
        print("Telegram hata:", e, flush=True)


def can_send(key, cooldown):
    now = time.time()
    if key in sent and now - sent[key] < cooldown:
        return False
    sent[key] = now
    return True


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    df["vol_avg"] = volume.rolling(20).mean()
    df["rsi"] = rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    basis = close.rolling(20).mean()
    dev = close.rolling(20).std()
    df["bb_mid"] = basis
    df["bb_upper"] = basis + dev * 2
    df["bb_lower"] = basis - dev * 2
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / basis.replace(0, np.nan)

    candle_range = high - low
    df["body_ratio"] = (close - df["open"]).abs() / candle_range.replace(0, np.nan)
    df["upper_wick"] = (high - pd.concat([df["open"], close], axis=1).max(axis=1)) / candle_range.replace(0, np.nan)
    df["lower_wick"] = (pd.concat([df["open"], close], axis=1).min(axis=1) - low) / candle_range.replace(0, np.nan)
    df["recovery_ratio"] = (close - low) / candle_range.replace(0, np.nan)

    df["obv"] = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0)).cumsum()
    return df.dropna().copy()


def fetch_df(symbol, timeframe, limit=200):
    for _ in range(3):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data or len(data) < 80:
                return None
            df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
            return add_indicators(df)
        except Exception as e:
            print("Veri hata:", symbol, timeframe, e, flush=True)
            time.sleep(1.5)
    return None


def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0
        if -0.001 <= rate <= 0.0015:
            return rate, "NORMAL", True
        if rate > 0.0015:
            return rate, "LONG KALABALIK", False
        return rate, "SHORT BASKI", True
    except Exception:
        return 0, "VERI YOK", True


def btc_status():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERI YOK"
    last = df.iloc[-1]
    ok = last.close > last.ema21 and last.rsi >= 42 and last.macd >= last.macd_signal
    return ok, "BTC DESTEKLI" if ok else "BTC ZAYIF"


def build_universe():
    try:
        markets = exchange.load_markets()
        symbols = [s for s in markets if s.endswith("/USDT:USDT") and markets[s].get("active", True)]
        tickers = exchange.fetch_tickers(symbols)
        rows = []
        for s in symbols:
            t = tickers.get(s, {})
            qv = t.get("quoteVolume") or 0
            pct = t.get("percentage") or 0
            last = t.get("last") or 0
            high = t.get("high") or 0
            low = t.get("low") or 0
            if qv < 1_000_000 or last <= 0 or high <= 0 or low <= 0:
                continue
            volatility = ((high - low) / last) * 100
            dist_low = ((last - low) / low) * 100
            if volatility < 1:
                continue
            rows.append({"symbol": s, "qv": qv, "pct": pct, "last": last, "high": high, "low": low, "volatility": volatility, "dist_low": dist_low})
        if not rows:
            return []
        df = pd.DataFrame(rows)
        df["pct_rank"] = df["pct"].rank(pct=True) * 100
        df["vol_rank"] = df["qv"].rank(pct=True) * 100
        df["volatility_rank"] = df["volatility"].rank(pct=True) * 100
        df["rs_score"] = df["pct_rank"] * 0.30 + df["vol_rank"] * 0.45 + df["volatility_rank"] * 0.25
        df = df.sort_values(["rs_score", "qv"], ascending=False).head(MAX_SYMBOLS)
        return df.to_dict("records")
    except Exception as e:
        print("Universe hata:", e, flush=True)
        return []


def early_dip_radar(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df5 is None or df15 is None or df1h is None:
        return False, None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]

    vol_ratio_5 = m5.volume / m5.vol_avg if m5.vol_avg > 0 else 0
    vol_ratio_15 = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    vol_ratio = max(vol_ratio_5, vol_ratio_15)
    usdt_vol = max(m5.volume * m5.close, m15.volume * m15.close)

    dip_price = min(m5.low, m15.low)
    price = m5.close
    bounce = ((price - dip_price) / dip_price) * 100 if dip_price > 0 else 0
    lower_wick = max(m5.lower_wick, m15.lower_wick)
    recovery = max(m5.recovery_ratio, m15.recovery_ratio)

    recent_low_5 = df5["low"].iloc[-36:-1].min()
    recent_low_15 = df15["low"].iloc[-32:-1].min()
    swept_low = m5.low <= recent_low_5 * 1.004 or m15.low <= recent_low_15 * 1.004

    obv_turn = df5["obv"].iloc[-1] > df5["obv"].iloc[-3] or df15["obv"].iloc[-1] > df15["obv"].iloc[-3]
    macd_turn = df5["macd_hist"].iloc[-1] > df5["macd_hist"].iloc[-2] or df15["macd_hist"].iloc[-1] > df15["macd_hist"].iloc[-2]
    rsi_turn = h1.rsi >= h1_prev.rsi or m15.rsi >= df15.iloc[-2].rsi
    green_reaction = m5.close > m5.open or m15.close > m15.open
    near_low = dist_low <= 12

    score = 0
    reasons = []
    if near_low:
        score += 3; reasons.append("24s dibe yakin")
    if lower_wick >= 0.35:
        score += 3; reasons.append("Alt igne var")
    if recovery >= 0.45:
        score += 3; reasons.append("Igneden toparlaniyor")
    if vol_ratio >= 1.7:
        score += 3; reasons.append("Hacim erken artiyor")
    if usdt_vol >= 75000:
        score += 2; reasons.append("USDT hacim yeterli")
    if swept_low:
        score += 2; reasons.append("Likidite supurmesi")
    if bounce >= 1.5:
        score += 2; reasons.append("Dipten tepki basladi")
    if obv_turn:
        score += 3; reasons.append("OBV donuyor")
    if macd_turn:
        score += 1; reasons.append("MACD toparlaniyor")
    if rsi_turn:
        score += 1; reasons.append("RSI donuyor")
    if green_reaction:
        score += 1; reasons.append("Yesil tepki mumu")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = (
    score >= 11
    and dist_low <= 8
    and vol_ratio >= 1.7
    and usdt_vol >= 15000
    and bounce >= 0.8
    and (obv_turn or rsi_turn)
    and recovery >= 0.35
)
    return valid, {"score": score, "price": price, "rs": rs, "dist_low": dist_low, "dip_price": dip_price, "bounce": bounce, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "lower_wick": lower_wick, "recovery": recovery, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def money_flow_radar(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df5 is None or df15 is None or df1h is None:
        return False, None
    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    macd_turn = m15.macd_hist > m15_prev.macd_hist
    macd_ok = m15.macd >= m15.macd_signal or macd_turn
    ema_ok = m15.close > m15.ema21
    trend_ok = m15.ema9 >= m15.ema21 or m15.close > m15.ema50
    body_ok = m5.body_ratio >= 0.30
    wick_ok = m5.upper_wick <= 0.55
    rsi_ok = 42 <= h1.rsi <= 82

    score = 0
    reasons = []
    if rs >= 60:
        score += 2; reasons.append("RS guclu")
    if vol_ratio >= 2.0:
        score += 3; reasons.append("15m hacim guclu")
    if usdt_vol >= 300000:
        score += 2; reasons.append("USDT hacim guclu")
    if obv_up:
        score += 3; reasons.append("OBV para girisi")
    if macd_ok:
        score += 2; reasons.append("MACD gucleniyor")
    if ema_ok:
        score += 2; reasons.append("EMA21 ustu")
    if trend_ok:
        score += 1; reasons.append("Trend toparlaniyor")
    if body_ok:
        score += 1; reasons.append("Mum govdesi uygun")
    if wick_ok:
        score += 1; reasons.append("Ust fitil saglikli")
    if rsi_ok:
        score += 1; reasons.append("RSI uygun")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = score >= 15 and rs >= 60 and vol_ratio >= 2.0 and usdt_vol >= 300000 and obv_up and macd_ok and ema_ok and rsi_ok
    return valid, {"score": score, "price": m15.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "body": m5.body_ratio, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def gold_long(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df1m = fetch_df(symbol, "1m", 100)
    df5 = fetch_df(symbol, "5m", 120)
    df15 = fetch_df(symbol, "15m", 150)
    if df1m is None or df5 is None or df15 is None:
        return False, None
    m1 = df1m.iloc[-1]
    prev3 = df1m.iloc[-4]
    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]

    vol_ratio = m1.volume / m1.vol_avg if m1.vol_avg > 0 else 0
    usdt_vol = m1.volume * m1.close
    change_3m = ((m1.close - prev3.open) / prev3.open) * 100
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    macd_up = m15.macd > m15.macd_signal and m15.macd_hist > m15_prev.macd_hist
    trend_up = m15.ema9 > m15.ema21 and m15.close > m15.ema21
    body_ok = m5.body_ratio >= 0.40
    wick_ok = m5.upper_wick <= 0.45
    rsi_ok = 48 <= m15.rsi <= 86

    score = 0
    reasons = []
    if rs >= 72:
        score += 2; reasons.append("RS cok guclu")
    if vol_ratio >= 3:
        score += 3; reasons.append("1m hacim patladi")
    if usdt_vol >= 300000:
        score += 2; reasons.append("USDT hacim guclu")
    if change_3m >= 0.35:
        score += 2; reasons.append("3m momentum var")
    if obv_up:
        score += 3; reasons.append("OBV para girisi")
    if macd_up:
        score += 2; reasons.append("MACD pozitif")
    if trend_up:
        score += 2; reasons.append("Trend yukari")
    if body_ok:
        score += 1; reasons.append("5m govde guclu")
    if wick_ok:
        score += 1; reasons.append("Ust fitil saglikli")
    if rsi_ok:
        score += 1; reasons.append("RSI uygun")
    if funding_ok:
        score += 1; reasons.append("Funding uygun")

    valid = score >= 16 and rs >= 72 and vol_ratio >= 3 and usdt_vol >= 300000 and change_3m >= 0.35 and obv_up and macd_up and trend_up and body_ok and wick_ok
    return valid, {"score": score, "price": m1.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "change_3m": change_3m, "rsi": m15.rsi, "body": m5.body_ratio, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def safe_short(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok):
    df15 = fetch_df(symbol, "15m", 150)
    df1h = fetch_df(symbol, "1h", 150)
    if df15 is None or df1h is None:
        return False, None
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]
    h1 = df1h.iloc[-1]

    if dist_low <= 5:
        return False, None
    if m15.close <= m15.bb_lower * 1.03:
        return False, None
    if m15.lower_wick >= 0.35:
        return False, None
    if m15.close > m15.ema21:
        return False, None
    if m15.close > m15.open:
        return False, None
    if h1.rsi > 60:
        return False, None
    if df15["obv"].iloc[-1] > df15["obv"].iloc[-3]:
        return False, None

    support = df15["low"].iloc[-30:-1].min()
    breakdown = m15.close < support
    vol_ratio = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    usdt_vol = m15.volume * m15.close
    trend_down = m15.close < m15.ema21 and m15.ema9 < m15.ema21
    macd_down = m15.macd < m15.macd_signal and m15.macd_hist < m15_prev.macd_hist
    obv_down = df15["obv"].iloc[-1] < df15["obv"].iloc[-6]
    red_body = m15.close < m15.open and m15.body_ratio >= 0.42

    score = 0
    reasons = []
    if breakdown:
        score += 4; reasons.append("Destek kirilimi")
    if vol_ratio >= 4:
        score += 3; reasons.append("Satis hacmi guclu")
    if usdt_vol >= 300000:
        score += 2; reasons.append("USDT hacim guclu")
    if trend_down:
        score += 2; reasons.append("Trend asagi")
    if macd_down:
        score += 2; reasons.append("MACD asagi")
    if obv_down:
        score += 2; reasons.append("OBV para cikisi")
    if red_body:
        score += 2; reasons.append("Guclu kirmizi mum")
    if not btc_ok:
        score += 1; reasons.append("BTC zayif")

    valid = (
    score >= 17
    and breakdown
    and dist_low >= 8
    and vol_ratio >= 4
    and usdt_vol >= 300000
    and trend_down
    and macd_down
    and obv_down
    and red_body
)
    return valid, {"score": score, "price": m15.close, "rs": rs, "dist_low": dist_low, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol, "rsi": h1.rsi, "body": m15.body_ratio, "reasons": reasons, "btc": btc_text, "funding_rate": funding_rate, "funding_text": funding_text}


def make_msg(title, symbol, d, decision):
    extra = ""
    if "dip_price" in d:
        extra = f"""
Igne Dibi: {d['dip_price']:.8f}
Dipten Tepki: %{d['bounce']:.2f}
Alt Fitil: %{d['lower_wick'] * 100:.1f}
Toparlanma: %{d['recovery'] * 100:.1f}
"""
    return f"""
{title}
{BOT_NAME}

Coin: {symbol}
Skor: {d['score']}
RS: {d['rs']:.1f}/100
Fiyat: {d['price']:.8f}
24s Dipten Uzaklik: %{d['dist_low']:.2f}
{extra}
Hacim Artisi: {d['vol_ratio']:.2f}x
USDT Hacim: {int(d['usdt_vol'])} USDT
BTC: {d['btc']}
Funding: {d['funding_rate']:.6f} / {d['funding_text']}

Sebep:
{", ".join(d['reasons'])}

Karar:
{decision}
""".strip()


def analyze(item, btc_ok, btc_text):
    symbol = item["symbol"]
    rs = item["rs_score"]
    dist_low = item["dist_low"]
    funding_rate, funding_text, funding_ok = get_funding(symbol)

    try:
        checks = [
            ("EARLY_DIP", COOLDOWN_EARLY_DIP, early_dip_radar, "EARLY DIP RADAR", "Erken dip alarmi. Direkt long degil; 5m/15m kapanis takip."),
            ("FLOW", COOLDOWN_FLOW, money_flow_radar, "PARA GIRISI RADAR", "Para girisi var. Kirilim ve retest takip."),
            ("GOLD", COOLDOWN_GOLD, gold_long, "GOLD LONG", "Guclu long adayi. FOMO degil; retest bekle."),
            ("SHORT", COOLDOWN_SHORT, safe_short, "SAFE SHORT", "Short adayi. Kirilim sonrasi retest bekle.")
        ]

        any_signal = False
        for tag, cooldown, func, title, decision in checks:
            ok, data = func(symbol, rs, dist_low, btc_ok, btc_text, funding_rate, funding_text, funding_ok)
            if ok and can_send(symbol + "_" + tag, cooldown):
                send_telegram(make_msg(title, symbol, data, decision))
                print(tag, symbol, data["score"], flush=True)
                any_signal = True

        if not any_signal:
            print(symbol, "RS:", round(rs, 1), "DistLow:", round(dist_low, 2), "Funding:", funding_text, "IC FILTRE", flush=True)
    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)


def run_bot():
    send_telegram(f"BOT BASLADI: {BOT_NAME}")
    print(BOT_NAME, "basladi", flush=True)

    while True:
        try:
            print("Tarama basladi:", datetime.now(), flush=True)
            btc_ok, btc_text = btc_status()
            print("BTC:", btc_text, flush=True)
            universe = build_universe()
            print("Taranacak coin:", len(universe), flush=True)
            for item in universe:
                analyze(item, btc_ok, btc_text)
                time.sleep(0.25)
            print("Tur bitti. Bekleme:", SLEEP_SECONDS, flush=True)
            time.sleep(SLEEP_SECONDS)
        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"BINANCE bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE EARLY DIP BOT AKTIF", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
