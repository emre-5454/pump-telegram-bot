import os
import time
import threading
import requests
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8920800668:AAHRaIYDqHiX5qLFkzfV_tCTNiKlYWR7P0w"
CHAT_ID = "6977265844"

BOT_NAME = "MEXC PRO | IGNE + DIP + MOMENTUM BOT"

MAX_SYMBOLS = 180
SLEEP_SECONDS = 60
MAX_SIGNALS_PER_CYCLE = 8

COOLDOWN_NEEDLE = 60 * 60
COOLDOWN_DIP = 90 * 60
COOLDOWN_MOMENTUM = 120 * 60
COOLDOWN_SHORT = 180 * 60

sent = {}

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {"defaultType": "swap", "adjustForTimeDifference": True}
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
    df["ema100"] = close.ewm(span=100, adjust=False).mean()
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

    candle_range = (high - low).replace(0, np.nan)
    df["body_ratio"] = (close - df["open"]).abs() / candle_range
    df["upper_wick"] = (high - pd.concat([df["open"], close], axis=1).max(axis=1)) / candle_range
    df["lower_wick"] = (pd.concat([df["open"], close], axis=1).min(axis=1) - low) / candle_range
    df["recovery_ratio"] = (close - low) / candle_range

    df["obv"] = np.where(
        close > close.shift(1),
        volume,
        np.where(close < close.shift(1), -volume, 0)
    ).cumsum()

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
            time.sleep(1)
    return None


def get_funding(symbol):
    try:
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate") or 0
        if -0.001 <= rate <= 0.0015:
            return rate, "NORMAL", True
        if rate < -0.001:
            return rate, "SHORT BASKI", True
        return rate, "LONG KALABALIK", False
    except Exception:
        return 0, "VERI YOK", True


def btc_status():
    df = fetch_df("BTC/USDT:USDT", "15m", 120)
    if df is None:
        return True, "BTC VERI YOK", 0
    last = df.iloc[-1]
    btc_change_15m = ((last.close - last.open) / last.open) * 100 if last.open > 0 else 0
    ok = last.close > last.ema21 and last.rsi >= 42 and last.macd >= last.macd_signal
    return ok, "BTC DESTEKLI" if ok else "BTC ZAYIF", btc_change_15m


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
            if qv < 800_000 or last <= 0 or high <= 0 or low <= 0:
                continue
            volatility = ((high - low) / last) * 100
            dist_low = ((last - low) / low) * 100
            if volatility < 1:
                continue
            rows.append({
                "symbol": s, "qv": qv, "pct": pct, "last": last,
                "high": high, "low": low, "volatility": volatility,
                "dist_low": dist_low
            })
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


def analyze_market(symbol, rs, dist_low, btc_text, btc_change, funding_rate, funding_text, funding_ok):
    df5 = fetch_df(symbol, "5m", 140)
    df15 = fetch_df(symbol, "15m", 180)
    df1h = fetch_df(symbol, "1h", 180)
    if df5 is None or df15 is None or df1h is None:
        return None

    m5 = df5.iloc[-1]
    m15 = df15.iloc[-1]
    m15_prev = df15.iloc[-2]

    vol_ratio_5 = m5.volume / m5.vol_avg if m5.vol_avg > 0 else 0
    vol_ratio_15 = m15.volume / m15.vol_avg if m15.vol_avg > 0 else 0
    vol_ratio = max(vol_ratio_5, vol_ratio_15)
    usdt_vol = max(m5.volume * m5.close, m15.volume * m15.close)

    dip_price = min(m5.low, m15.low)
    price = m5.close
    bounce = ((price - dip_price) / dip_price) * 100 if dip_price > 0 else 0
    lower_wick = max(m5.lower_wick, m15.lower_wick)
    recovery = max(m5.recovery_ratio, m15.recovery_ratio)

    coin_change_15m = ((m15.close - m15.open) / m15.open) * 100 if m15.open > 0 else 0
    relative_strength = coin_change_15m - btc_change

    recent_high = df15["high"].iloc[-24:-1].max()
    recent_low = df15["low"].iloc[-24:-1].min()
    breakout = m15.close > recent_high * 1.002
    breakdown = m15.close < recent_low * 0.998

    obv_turn = df5["obv"].iloc[-1] > df5["obv"].iloc[-3] or df15["obv"].iloc[-1] > df15["obv"].iloc[-3]
    obv_up = df15["obv"].iloc[-1] > df15["obv"].iloc[-6]
    obv_mean = df15["obv"].rolling(20).mean().iloc[-1]
    obv_strong = df15["obv"].iloc[-1] > obv_mean

    rsi_turn = m15.rsi >= m15_prev.rsi
    macd_turn = m15.macd_hist > m15_prev.macd_hist
    macd_up = m15.macd > m15.macd_signal and m15.macd_hist > m15_prev.macd_hist

    ema_reclaim = m5.close > m5.ema9 or m15.close > m15.ema21
    trend_up = m15.ema9 >= m15.ema21 or m15.close > m15.ema50
    trend_down = m15.close < m15.ema21 and m15.ema9 < m15.ema21
    green_body = m5.close > m5.open and m5.body_ratio >= 0.35
    red_body = m15.close < m15.open and m15.body_ratio >= 0.42
    wick_ok = m5.upper_wick <= 0.55

    return {
        "symbol": symbol, "price": price, "rs": rs, "dist_low": dist_low,
        "dip_price": dip_price, "bounce": bounce, "lower_wick": lower_wick,
        "recovery": recovery, "vol_ratio": vol_ratio, "usdt_vol": usdt_vol,
        "coin_change_15m": coin_change_15m, "btc_change_15m": btc_change,
        "relative_strength": relative_strength, "funding_rate": funding_rate,
        "funding_text": funding_text, "btc": btc_text, "rsi_15m": m15.rsi,
        "obv_turn": obv_turn, "obv_up": obv_up, "obv_strong": obv_strong,
        "rsi_turn": rsi_turn, "macd_turn": macd_turn, "macd_up": macd_up,
        "ema_reclaim": ema_reclaim, "trend_up": trend_up, "trend_down": trend_down,
        "green_body": green_body, "red_body": red_body, "wick_ok": wick_ok,
        "breakout": breakout, "breakdown": breakdown, "funding_ok": funding_ok
    }


def needle_radar(m):
    score, reasons = 0, []
    if m["lower_wick"] >= 0.45:
        score += 4; reasons.append("Buyuk alt igne")
    if m["recovery"] >= 0.35:
        score += 3; reasons.append("Igneden toparlanma")
    if m["vol_ratio"] >= 2.0:
        score += 3; reasons.append("Igne hacimli")
    if m["usdt_vol"] >= 30000:
        score += 2; reasons.append("USDT hacim yeterli")
    if m["dist_low"] <= 12:
        score += 2; reasons.append("24s dibe yakin")
    if m["bounce"] >= 0.5:
        score += 1; reasons.append("Dipten ilk tepki")
    if m["funding_ok"]:
        score += 1; reasons.append("Funding uygun")
    valid = score >= 10 and m["lower_wick"] >= 0.45 and m["vol_ratio"] >= 2.0 and m["usdt_vol"] >= 30000 and m["recovery"] >= 0.35 and m["dist_low"] <= 12
    return valid, score, reasons


def dip_radar(m):
    score, reasons = 0, []
    if m["dist_low"] <= 10:
        score += 3; reasons.append("24s dibe yakin")
    if m["bounce"] >= 1.2:
        score += 2; reasons.append("Dipten tepki basladi")
    if m["vol_ratio"] >= 1.8:
        score += 3; reasons.append("Hacim artiyor")
    if m["usdt_vol"] >= 50000:
        score += 2; reasons.append("USDT hacim guclu")
    if m["obv_turn"]:
        score += 3; reasons.append("OBV donuyor")
    if m["rsi_turn"]:
        score += 2; reasons.append("RSI donuyor")
    if m["macd_turn"]:
        score += 2; reasons.append("MACD toparlaniyor")
    if m["green_body"]:
        score += 1; reasons.append("Yesil tepki mumu")
    if m["relative_strength"] >= 1.2:
        score += 2; reasons.append("BTCden guclu")
   valid = score >= 15 and m["dist_low"] <= 10 and m["vol_ratio"] >= 1.8 and m["usdt_vol"] >= 50000 and m["bounce"] >= 1.2 and m["obv_turn"] and m["coin_change_15m"] >= 0.3 and m["relative_strength"] >= 0.3
    return valid, score, reasons


def momentum_long(m):
    score, reasons = 0, []
    if m["coin_change_15m"] >= 2.5:
        score += 3; reasons.append("15m momentum guclu")
    if m["relative_strength"] >= 1.5:
        score += 4; reasons.append("BTCden net guclu")
    if m["vol_ratio"] >= 2.2:
        score += 3; reasons.append("Hacim guclu")
    if m["usdt_vol"] >= 150000:
        score += 3; reasons.append("USDT para girisi guclu")
    if m["obv_up"]:
        score += 3; reasons.append("OBV para girisi")
    if m["obv_strong"]:
        score += 2; reasons.append("OBV ortalama ustu")
    if m["macd_up"]:
        score += 2; reasons.append("MACD guclu")
    if m["ema_reclaim"]:
        score += 1; reasons.append("EMA geri alindi")
    if m["trend_up"]:
        score += 1; reasons.append("Trend yukari")
    if m["breakout"]:
        score += 2; reasons.append("Yeni tepe kirilimi")
    if m["wick_ok"]:
        score += 1; reasons.append("Ust fitil saglikli")
    valid = score >= 15 and m["coin_change_15m"] >= 2.5 and m["relative_strength"] >= 1.5 and m["vol_ratio"] >= 2.2 and m["usdt_vol"] >= 150000 and m["obv_up"] and m["macd_up"] and m["ema_reclaim"] and m["wick_ok"]
    return valid, score, reasons


def momentum_short(m):
    if m["dist_low"] <= 8:
        return False, 0, []
    score, reasons = 0, []
    if m["breakdown"]:
        score += 4; reasons.append("Destek kirilimi")
    if m["vol_ratio"] >= 3.5:
        score += 3; reasons.append("Satis hacmi guclu")
    if m["usdt_vol"] >= 150000:
        score += 2; reasons.append("USDT satis hacmi")
    if m["trend_down"]:
        score += 2; reasons.append("Trend asagi")
    if not m["obv_up"]:
        score += 2; reasons.append("OBV zayif")
    if m["red_body"]:
        score += 2; reasons.append("Guclu kirmizi mum")
    if m["relative_strength"] <= -1:
        score += 2; reasons.append("BTCden zayif")
    valid = score >= 13 and m["breakdown"] and m["vol_ratio"] >= 3.5 and m["usdt_vol"] >= 150000 and m["trend_down"] and m["red_body"]
    return valid, score, reasons


def make_msg(title, m, score, reasons, decision):
    return f"""
{title}
{BOT_NAME}

Coin: {m['symbol']}
Skor: {score}
RS: {m['rs']:.1f}/100
Fiyat: {m['price']:.8f}
24s Dipten Uzaklik: %{m['dist_low']:.2f}

Igne Dibi: {m['dip_price']:.8f}
Dipten Tepki: %{m['bounce']:.2f}
Alt Fitil: %{m['lower_wick'] * 100:.1f}
Toparlanma: %{m['recovery'] * 100:.1f}

Coin 15m: %{m['coin_change_15m']:.2f}
BTC 15m: %{m['btc_change_15m']:.2f}
BTCye Gore Guc: %{m['relative_strength']:.2f}

Hacim Artisi: {m['vol_ratio']:.2f}x
USDT Hacim: {int(m['usdt_vol'])} USDT
BTC: {m['btc']}
Funding: {m['funding_rate']:.6f} / {m['funding_text']}

Sebep:
{', '.join(reasons)}

Karar:
{decision}
""".strip()


def collect_candidates(item, btc_text, btc_change):
    symbol = item["symbol"]
    rs = item["rs_score"]
    dist_low = item["dist_low"]
    funding_rate, funding_text, funding_ok = get_funding(symbol)
    m = analyze_market(symbol, rs, dist_low, btc_text, btc_change, funding_rate, funding_text, funding_ok)
    if not m:
        return []
    checks = [
        ("NEEDLE", "ğŸš¨ IGNE RADARI", COOLDOWN_NEEDLE, needle_radar, "Likidasyon ignesi olabilir. Takibe al; direkt long degil."),
        ("DIP", "ğŸ”¥ DIP RADAR", COOLDOWN_DIP, dip_radar, "Dipten donus adayi. 5m/15m kapanis takip."),
        ("MOMENTUM", "ğŸš€ MOMENTUM LONG", COOLDOWN_MOMENTUM, momentum_long, "Para girisi guclu. Retest veya devam mumu takip."),
        ("SHORT", "ğŸ”» MOMENTUM SHORT", COOLDOWN_SHORT, momentum_short, "Short adayi. Kirilim sonrasi retest takip.")
    ]
    candidates = []
    for tag, title, cooldown, func, decision in checks:
        ok, score, reasons = func(m)
        key = symbol + "_" + tag
        if ok and can_send(key, cooldown):
            priority = score
            if tag == "MOMENTUM":
                priority += 20
            if tag == "NEEDLE":
                priority += 5
            candidates.append({"tag": tag, "title": title, "priority": priority, "score": score, "m": m, "reasons": reasons, "decision": decision})
    if not candidates:
        print(symbol, "RS:", round(rs, 1), "DistLow:", round(dist_low, 2), "IC FILTRE", flush=True)
    return candidates


def run_bot():
    send_telegram(f"BOT BASLADI: {BOT_NAME}")
    print(BOT_NAME, "basladi", flush=True)
    while True:
        try:
            print("Tarama basladi:", datetime.now(), flush=True)
            btc_ok, btc_text, btc_change = btc_status()
            print("BTC:", btc_text, "BTC15:", round(btc_change, 2), flush=True)
            universe = build_universe()
            print("Taranacak coin:", len(universe), flush=True)
            all_candidates = []
            for item in universe:
                try:
                    all_candidates.extend(collect_candidates(item, btc_text, btc_change))
                except Exception as e:
                    print("Coin analiz hata:", item.get("symbol"), e, flush=True)
                time.sleep(0.20)
            all_candidates = sorted(all_candidates, key=lambda x: x["priority"], reverse=True)
            selected = all_candidates[:MAX_SIGNALS_PER_CYCLE]
            print("Aday:", len(all_candidates), "Gonderilecek:", len(selected), flush=True)
            for c in selected:
                send_telegram(make_msg(c["title"], c["m"], c["score"], c["reasons"], c["decision"]))
                print("SIGNAL", c["tag"], c["m"]["symbol"], c["score"], flush=True)
                time.sleep(1)
            print("Tur bitti. Bekleme:", SLEEP_SECONDS, flush=True)
            time.sleep(SLEEP_SECONDS)
        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_telegram(f"MEXC bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "MEXC PRO IGNE DIP MOMENTUM BOT AKTIF", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
