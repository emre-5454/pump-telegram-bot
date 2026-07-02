# Binance Futures SAFE ENTRY DECISION BOT V15
# Binance MEXC kopyasi degil: Money Acceleration + Safe Entry + Elite AL + FOMO Block mantigi.
# Ortam degiskenleri: TELEGRAM_TOKEN, CHAT_ID, BINANCE_ELITE_PREP_CHAT_ID, BINANCE_ELITE_GOLD_CHAT_ID

from flask import Flask
import threading
import time
import os
import json
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = "8937020446:AAEmdROw4hfDYArdz4eJ47oGHAT_9u4HhIM"
CHAT_ID = "7553607277"

# Kanal yapisi:
# CHAT_ID                  -> Ana kanal / normal radarlar
# BINANCE_ELITE_PREP_CHAT_ID -> Hazirlik / izleme sinyalleri
# BINANCE_ELITE_GOLD_CHAT_ID -> Elite Gold sinyalleri
# Eski BINANCE_ELITE_GOLD_CHAT_ID kaldirildi; AL/Gold sinyalleri BINANCE_ELITE_GOLD_CHAT_ID kanalina gider.
BINANCE_ELITE_PREP_CHAT_ID = os.getenv("BINANCE_ELITE_PREP_CHAT_ID") or "-1004422691643"
BINANCE_ELITE_GOLD_CHAT_ID = os.getenv("BINANCE_ELITE_GOLD_CHAT_ID") or "-1004376713697"

# V52 AYRI RAPOR / LOG KANALLARI:
# Performance Center: Gunluk/haftalik/aylik rapor, radar saglik, full tracking, kacan firsatlar.
# Log Kanali: Bot basladi, restart, genel hata, kritik exception.
BINANCE_PERFORMANCE_CHAT_ID = os.getenv("BINANCE_PERFORMANCE_CHAT_ID") or BINANCE_ELITE_GOLD_CHAT_ID
BINANCE_LOG_CHAT_ID = os.getenv("BINANCE_LOG_CHAT_ID") or CHAT_ID

BOT_NAME = "BINANCE SAFE ENTRY DECISION BOT V56.3"

MAX_SYMBOLS = int(os.getenv("BINANCE_MAX_SYMBOLS", "160"))
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", "120"))

# V56.3 BINANCE API RATE LIMIT GUARD STABLE
# Recursion hatasi duzeltildi: safe_fetch_ohlcv artik kendi kendini degil exchange.fetch_ohlcv cagırır.
# V56.2 BINANCE API RATE LIMIT GUARD
# Binance 418 / too many requests durumunda bot ayni coini zorlamaz, kisa sure cache kullanir.
BINANCE_API_GUARD_ENABLED = os.getenv("BINANCE_API_GUARD_ENABLED", "1") == "1"
BINANCE_OHLCV_CACHE_SECONDS = int(os.getenv("BINANCE_OHLCV_CACHE_SECONDS", "90"))
BINANCE_TICKER_CACHE_SECONDS = int(os.getenv("BINANCE_TICKER_CACHE_SECONDS", "60"))
BINANCE_418_DEFAULT_COOLDOWN = int(os.getenv("BINANCE_418_DEFAULT_COOLDOWN", "900"))
BINANCE_API_BAN_UNTIL = 0.0
BINANCE_API_LAST_WARN_TS = 0.0
BINANCE_OHLCV_CACHE = {}
BINANCE_TICKER_CACHE = {}

# V43 BINANCE ANA KANAL GEVSETME:
# Binance tarafinda ana radara az sinyal dustugu icin sadece ana radar/adayi gevsetildi.
# Elite Hazirlik ve Gold kapilari yine kendi sert kalite filtrelerinden gecmeye devam eder.
BINANCE_MAIN_RELAX_ENABLED = os.getenv("BINANCE_MAIN_RELAX_ENABLED", "1") == "1"
BINANCE_UNIVERSE_MIN_QV = float(os.getenv("BINANCE_UNIVERSE_MIN_QV", "2000000"))
BINANCE_UNIVERSE_MIN_VOLATILITY = float(os.getenv("BINANCE_UNIVERSE_MIN_VOLATILITY", "1.10"))

# V40 PROFESYONEL GOLD + PIE RADAR IQ:
# Gold mesajinda para akisi, orderflow, CVD, OI ve gecmis performans ozeti birlikte gosterilir.
#
# V38 KANAL NETLESTIRME:
# Elite Gold artik Elite AL kanalina degil, ayri BINANCE_ELITE_GOLD_CHAT_ID kanalina gider.
#
# V37 PERFORMANCE INTELLIGENCE ENGINE (PIE):
# Bot attigi Elite sinyalleri dosyaya kaydeder, sonraki turlarda TP/Stop durumunu izler.
PIE_ENABLED = os.getenv("PIE_ENABLED", "1") == "1"
PIE_DATA_FILE = os.getenv("PIE_DATA_FILE", "/tmp/binance_pie_signals.json")
PIE_MAX_TRACK_HOURS = float(os.getenv("PIE_MAX_TRACK_HOURS", "48"))
PIE_UPDATE_COOLDOWN_SECONDS = 10 * 60

# V49/V39 PIE RAPOR + RED ACIKLAMA KATMANI:
# Günlük performans raporu ve "neden sinyal gelmedi?" sorusuna log cevabı verir.
PIE_DAILY_REPORT_ENABLED = os.getenv("PIE_DAILY_REPORT_ENABLED", "1") == "1"
PIE_DAILY_REPORT_HOUR_UTC = int(os.getenv("PIE_DAILY_REPORT_HOUR_UTC", "6"))  # Turkiye sabah 09:00
PIE_DAILY_REPORT_STATE_FILE = os.getenv("PIE_DAILY_REPORT_STATE_FILE", PIE_DATA_FILE + ".daily_state")
EXPLAIN_REJECTS = os.getenv("EXPLAIN_REJECTS", "1") == "1"
EXPLAIN_REJECT_MIN_RS = float(os.getenv("EXPLAIN_REJECT_MIN_RS", "50"))
EXPLAIN_REJECT_MAX_LINES = int(os.getenv("EXPLAIN_REJECT_MAX_LINES", "6"))

# V58/V52 PERFORMANS MERKEZI:
# Tek full tracking dosyasindan 24s / 7g / 30g rapor uretir.
# Varsayilan saat: Turkiye 09:00 = UTC 06:00. Haftalik: Pazartesi. Aylik: Ayin 1'i.
PERFORMANCE_CENTER_ENABLED = os.getenv("PERFORMANCE_CENTER_ENABLED", "1") == "1"
# Kanal temiz kalsin: kayit yoksa bos rapor Telegram'a gitmesin.
PERFORMANCE_SEND_EMPTY_REPORTS = os.getenv("PERFORMANCE_SEND_EMPTY_REPORTS", "0") == "1"
PERFORMANCE_WEEKLY_REPORT_ENABLED = os.getenv("PERFORMANCE_WEEKLY_REPORT_ENABLED", "1") == "1"
PERFORMANCE_MONTHLY_REPORT_ENABLED = os.getenv("PERFORMANCE_MONTHLY_REPORT_ENABLED", "1") == "1"
PERFORMANCE_REPORT_HOUR_UTC = int(os.getenv("PERFORMANCE_REPORT_HOUR_UTC", str(PIE_DAILY_REPORT_HOUR_UTC)))
PERFORMANCE_WEEKLY_DAY_UTC = int(os.getenv("PERFORMANCE_WEEKLY_DAY_UTC", "0"))  # 0=Pazartesi
PERFORMANCE_MONTHLY_DAY_UTC = int(os.getenv("PERFORMANCE_MONTHLY_DAY_UTC", "1"))


# V48 SANAL TP TAKIP + V47 RADAR SAGLIK RAPORU:
# Sadece gelen sinyalleri degil, her turda hangi radar denendi/gecmedi onu da kaydeder.
# Boylece 0 sinyal veren radarlarin cok siki mi yoksa piyasa kosuluna uygun degil mi oldugu gorulur.
RADAR_HEALTH_ENABLED = os.getenv("RADAR_HEALTH_ENABLED", "1") == "1"
RADAR_HEALTH_FILE = os.getenv("RADAR_HEALTH_FILE", PIE_DATA_FILE + ".radar_health")
RADAR_HEALTH_WARN_ZERO_ATTEMPTS = int(os.getenv("RADAR_HEALTH_WARN_ZERO_ATTEMPTS", "80"))
RADAR_HEALTH_WARN_LOW_PASS_PCT = float(os.getenv("RADAR_HEALTH_WARN_LOW_PASS_PCT", "0.20"))


# V46 FULL TRACKING / ANA KANAL + HAZIRLIK + GOLD KAYIT SISTEMI
FULL_TRACKING_ENABLED = os.getenv("FULL_TRACKING_ENABLED", "1") == "1"
FULL_TRACKING_DATA_FILE = os.getenv("FULL_TRACKING_DATA_FILE", "/tmp/binance_full_tracking.json")
PERFORMANCE_DAILY_STATE_FILE = os.getenv("PERFORMANCE_DAILY_STATE_FILE", FULL_TRACKING_DATA_FILE + ".daily_state")
PERFORMANCE_WEEKLY_STATE_FILE = os.getenv("PERFORMANCE_WEEKLY_STATE_FILE", FULL_TRACKING_DATA_FILE + ".weekly_state")
PERFORMANCE_MONTHLY_STATE_FILE = os.getenv("PERFORMANCE_MONTHLY_STATE_FILE", FULL_TRACKING_DATA_FILE + ".monthly_state")
FULL_TRACKING_MAX_RECORDS = int(os.getenv("FULL_TRACKING_MAX_RECORDS", "1500"))
FULL_TRACKING_UPDATE_COOLDOWN_SECONDS = int(os.getenv("FULL_TRACKING_UPDATE_COOLDOWN_SECONDS", "600"))
FULL_TRACKING_MISSED_GAIN_PCT = float(os.getenv("FULL_TRACKING_MISSED_GAIN_PCT", "10"))
FULL_TRACKING_VIRTUAL_TP_ENABLED = os.getenv("FULL_TRACKING_VIRTUAL_TP_ENABLED", "1") == "1"
FULL_TRACKING_VTP1_PCT = float(os.getenv("FULL_TRACKING_VTP1_PCT", "3"))
FULL_TRACKING_VTP2_PCT = float(os.getenv("FULL_TRACKING_VTP2_PCT", "6"))
FULL_TRACKING_VTP3_PCT = float(os.getenv("FULL_TRACKING_VTP3_PCT", "10"))
FULL_TRACKING_VSTOP_PCT = float(os.getenv("FULL_TRACKING_VSTOP_PCT", "3"))





def binance_api_guard_now():
    return time.time()


def binance_api_guard_is_418(err):
    s = str(err)
    return ("418" in s) or ("Way too many requests" in s) or ("banned until" in s)


def binance_api_guard_extract_until(err):
    """Binance mesajindaki banned until timestamp'ini yakalamaya calisir."""
    import re
    s = str(err)
    m = re.search(r"banned until\s+(\d+)", s)
    if not m:
        return binance_api_guard_now() + BINANCE_418_DEFAULT_COOLDOWN
    raw = float(m.group(1))
    # Binance bazen milisaniye epoch dondurur.
    if raw > 10_000_000_000:
        raw = raw / 1000.0
    if raw < binance_api_guard_now():
        raw = binance_api_guard_now() + BINANCE_418_DEFAULT_COOLDOWN
    return raw


def binance_api_guard_set_ban(err):
    global BINANCE_API_BAN_UNTIL, BINANCE_API_LAST_WARN_TS
    if not BINANCE_API_GUARD_ENABLED:
        return
    until_ts = binance_api_guard_extract_until(err)
    BINANCE_API_BAN_UNTIL = max(float(BINANCE_API_BAN_UNTIL or 0), until_ts)
    now_ts = binance_api_guard_now()
    # Log spam olmasin diye 60 sn'de bir yaz.
    if now_ts - float(BINANCE_API_LAST_WARN_TS or 0) > 60:
        kalan = int(max(0, BINANCE_API_BAN_UNTIL - now_ts))
        print(f"BINANCE API GUARD: 418/rate limit yakalandi. {kalan} sn fetch azaltildi.", flush=True)
        BINANCE_API_LAST_WARN_TS = now_ts


def binance_api_guard_active():
    return BINANCE_API_GUARD_ENABLED and binance_api_guard_now() < float(BINANCE_API_BAN_UNTIL or 0)


def safe_fetch_ticker(symbol):
    """Ticker icin cache + 418 guard."""
    now_ts = binance_api_guard_now()
    cached = BINANCE_TICKER_CACHE.get(symbol)
    if cached and now_ts - cached[0] <= BINANCE_TICKER_CACHE_SECONDS:
        return cached[1]
    if binance_api_guard_active():
        return cached[1] if cached else None
    try:
        t = exchange.fetch_ticker(symbol)
        BINANCE_TICKER_CACHE[symbol] = (now_ts, t)
        return t
    except Exception as e:
        if binance_api_guard_is_418(e):
            binance_api_guard_set_ban(e)
            return cached[1] if cached else None
        raise


def safe_fetch_ohlcv(symbol, timeframe, limit=120):
    """OHLCV icin cache + 418 guard."""
    now_ts = binance_api_guard_now()
    key = (symbol, timeframe, int(limit))
    cached = BINANCE_OHLCV_CACHE.get(key)
    if cached and now_ts - cached[0] <= BINANCE_OHLCV_CACHE_SECONDS:
        return cached[1]
    if binance_api_guard_active():
        return cached[1] if cached else None
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        BINANCE_OHLCV_CACHE[key] = (now_ts, data)
        return data
    except Exception as e:
        if binance_api_guard_is_418(e):
            binance_api_guard_set_ban(e)
            return cached[1] if cached else None
        raise

def radar_health_today_key():
    return datetime.utcnow().strftime("%Y-%m-%d")


def radar_health_empty(today=None):
    return {"date": today or radar_health_today_key(), "radars": {}, "updated_ts": time.time()}


def radar_health_load():
    if not RADAR_HEALTH_ENABLED:
        return radar_health_empty()
    today = radar_health_today_key()
    try:
        if os.path.exists(RADAR_HEALTH_FILE):
            with open(RADAR_HEALTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("date") == today:
                data.setdefault("radars", {})
                return data
    except Exception as e:
        print("Radar health load hata:", e, flush=True)
    return radar_health_empty(today)


def radar_health_has_today_data():
    if not RADAR_HEALTH_ENABLED:
        return False
    try:
        data = radar_health_load()
        radars = data.get("radars", {}) if isinstance(data, dict) else {}
        if not radars:
            return False
        for st in radars.values():
            if int(st.get("checked", 0) or 0) > 0 or int(st.get("passed", 0) or 0) > 0:
                return True
        return False
    except Exception:
        return False


def radar_health_save(data):
    if not RADAR_HEALTH_ENABLED:
        return
    try:
        data["updated_ts"] = time.time()
        tmp = RADAR_HEALTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RADAR_HEALTH_FILE)
    except Exception as e:
        print("Radar health save hata:", e, flush=True)


def radar_health_record(flags):
    """
    flags = {"RadarName": True/False}
    Her analyze cagrisi bir denemedir. True ise radar o coinde gecti demektir.
    """
    if not RADAR_HEALTH_ENABLED or not flags:
        return
    data = radar_health_load()
    radars = data.setdefault("radars", {})
    for name, ok in flags.items():
        if not name:
            continue
        st = radars.setdefault(str(name), {"attempts": 0, "passed": 0})
        st["attempts"] = int(st.get("attempts", 0)) + 1
        if bool(ok):
            st["passed"] = int(st.get("passed", 0)) + 1
    radar_health_save(data)


def radar_health_report_text(market_name="BOT"):
    if not RADAR_HEALTH_ENABLED:
        return ""
    data = radar_health_load()
    radars = data.get("radars", {}) or {}
    if not radars:
        return "\n\n📡 RADAR SAGLIK RAPORU\nBugun radar deneme kaydi yok."

    lines = ["", "📡 RADAR SAGLIK RAPORU"]
    items = sorted(radars.items(), key=lambda kv: (kv[1].get("passed", 0), kv[0]))
    zero_list = []
    for name, st in items:
        attempts = int(st.get("attempts", 0) or 0)
        passed = int(st.get("passed", 0) or 0)
        pct = (passed / attempts * 100) if attempts else 0
        if attempts >= RADAR_HEALTH_WARN_ZERO_ATTEMPTS and passed == 0:
            durum = "0 sinyal / cok siki olabilir"
            zero_list.append(name)
        elif attempts >= RADAR_HEALTH_WARN_ZERO_ATTEMPTS and pct <= RADAR_HEALTH_WARN_LOW_PASS_PCT:
            durum = "cok az geciyor"
        elif passed > 0:
            durum = "aktif"
        else:
            durum = "veri birikiyor"
        lines.append(f"{name}: Deneme {attempts} | Gecen {passed} | %{pct:.2f} | {durum}")

    if zero_list:
        lines.append("")
        lines.append("0 sinyal veren radarlar: " + ", ".join(zero_list[:8]))
        lines.append("Not: Bu her zaman hata degildir; piyasa o radara uygun olmayabilir veya esik fazla siki olabilir.")
    return "\n" + "\n".join(lines)


def pie_combo_key(rec):
    mods = [str(rec.get("module", "UNKNOWN"))]
    mods += [str(x) for x in rec.get("support_modules", []) if x]
    mods = sorted(set(mods))
    return " + ".join(mods) if mods else "UNKNOWN"


def pie_is_success(rec):
    return bool(rec.get("tp1_hit") or rec.get("status") in ("TP1", "TP2", "TP3"))


def pie_is_stop(rec):
    return bool(rec.get("stop_hit") or rec.get("status") == "STOP")


def pie_daily_report_text(records, market_name="BOT"):
    now_ts = time.time()
    day_ago = now_ts - 24 * 60 * 60
    recent = [r for r in records if float(r.get("created_ts", 0) or 0) >= day_ago]
    if not recent:
        return f"📊 {market_name} GUNLUK PERFORMANS\n\nSon 24 saatte kayitli Elite sinyali yok." + radar_health_report_text(market_name)

    total = len(recent)
    tp1 = sum(1 for r in recent if r.get("tp1_hit") or r.get("status") in ("TP1", "TP2", "TP3"))
    tp2 = sum(1 for r in recent if r.get("tp2_hit") or r.get("status") in ("TP2", "TP3"))
    tp3 = sum(1 for r in recent if r.get("tp3_hit") or r.get("status") == "TP3")
    stop = sum(1 for r in recent if pie_is_stop(r))
    open_count = sum(1 for r in recent if r.get("status") in ("OPEN", "TP1", "TP2"))
    success = (tp1 / total * 100) if total else 0

    by_module = {}
    by_combo = {}
    for r in recent:
        module = r.get("module", "UNKNOWN")
        by_module.setdefault(module, {"n": 0, "tp1": 0, "stop": 0})
        by_module[module]["n"] += 1
        by_module[module]["tp1"] += 1 if pie_is_success(r) else 0
        by_module[module]["stop"] += 1 if pie_is_stop(r) else 0

        combo = pie_combo_key(r)
        by_combo.setdefault(combo, {"n": 0, "tp1": 0, "stop": 0})
        by_combo[combo]["n"] += 1
        by_combo[combo]["tp1"] += 1 if pie_is_success(r) else 0
        by_combo[combo]["stop"] += 1 if pie_is_stop(r) else 0

    def best_item(d):
        if not d:
            return "YOK"
        items = sorted(
            d.items(),
            key=lambda kv: ((kv[1]["tp1"] / kv[1]["n"]) if kv[1]["n"] else 0, kv[1]["n"]),
            reverse=True
        )
        name, st = items[0]
        rate = st["tp1"] / st["n"] * 100 if st["n"] else 0
        return f"{name} ({st['tp1']}/{st['n']} TP1, %{rate:.0f})"

    def weak_item(d):
        if not d:
            return "YOK"
        items = sorted(
            d.items(),
            key=lambda kv: ((kv[1]["tp1"] / kv[1]["n"]) if kv[1]["n"] else 0, -kv[1]["stop"])
        )
        name, st = items[0]
        rate = st["tp1"] / st["n"] * 100 if st["n"] else 0
        return f"{name} ({st['tp1']}/{st['n']} TP1, Stop {st['stop']}, %{rate:.0f})"

    avg_max = sum(float(r.get("max_gain_pct", 0) or 0) for r in recent) / total
    avg_dd = sum(float(r.get("max_dd_pct", 0) or 0) for r in recent) / total

    return f"""
📊 {market_name} GUNLUK PERFORMANS RAPORU

Son 24s Elite: {total}
TP1: {tp1}
TP2: {tp2}
TP3: {tp3}
Stop: {stop}
Acik: {open_count}

Basari: %{success:.1f}
Ort. Max: %{avg_max:.2f}
Ort. DD: %{avg_dd:.2f}

En iyi mod:
{best_item(by_module)}

En zayif mod:
{weak_item(by_module)}

En iyi kombinasyon:
{best_item(by_combo)}

Not:
Bu rapor PIE kayitlarina gore uretilir. Veri arttikca Radar IQ daha guvenilir olur.
""".strip() + radar_health_report_text(market_name)


def pie_daily_report_if_due(chat_id=None, market_name="BOT"):
    if not PIE_ENABLED or not PIE_DAILY_REPORT_ENABLED:
        return
    now = datetime.utcnow()
    if now.hour < PIE_DAILY_REPORT_HOUR_UTC:
        return
    today_key = now.strftime("%Y-%m-%d")
    try:
        if os.path.exists(PIE_DAILY_REPORT_STATE_FILE):
            with open(PIE_DAILY_REPORT_STATE_FILE, "r", encoding="utf-8") as f:
                if f.read().strip() == today_key:
                    return
    except Exception:
        pass

    records = pie_load_records()
    ft_update_open_records()

    has_pie = any(float(r.get("created_ts", 0) or 0) >= time.time() - 24 * 60 * 60 for r in records)
    has_full = ft_has_recent_records(1)
    has_radar = radar_health_has_today_data()

    # Kanal temiz kalsin: hic veri yoksa Telegram'a bos rapor atma, sadece state isaretle.
    if not PERFORMANCE_SEND_EMPTY_REPORTS and not (has_pie or has_full or has_radar):
        print(f"{market_name} daily report atlandi: kayit yok", flush=True)
        try:
            performance_center_reports_if_due(chat_id, market_name)
        except Exception as e:
            print("Performance center report hata:", e, flush=True)
        try:
            with open(PIE_DAILY_REPORT_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(today_key)
        except Exception as e:
            print("PIE daily state hata:", e, flush=True)
        return

    report_text = pie_daily_report_text(records, market_name)
    try:
        report_text += "\n\n" + ft_daily_report_text(market_name)
    except Exception as e:
        print("FULL TRACK daily report hata:", e, flush=True)
    send_telegram(report_text, chat_id)
    try:
        performance_center_reports_if_due(chat_id, market_name)
    except Exception as e:
        print("Performance center report hata:", e, flush=True)
    try:
        with open(PIE_DAILY_REPORT_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(today_key)
    except Exception as e:
        print("PIE daily state hata:", e, flush=True)



def pie_signal_history_text(d, support_modules=None, market_name="BOT"):
    """
    V50/V40 RADAR IQ:
    Mevcut Gold/Elite sinyaline benzeyen gecmis PIE kayitlarini ozetler.
    Veri azsa net karar vermez; sadece veri birikiyor mesajı verir.
    """
    if not PIE_ENABLED:
        return "📚 PIE ANALIZI\nPIE kapali."

    support_modules = support_modules or []
    current_mods = set([str(d.get("module", "UNKNOWN"))] + [str(x) for x in support_modules if x])
    records = pie_load_records()
    closed = [r for r in records if r.get("status") not in ("OPEN", "TP1", "TP2")]
    if not closed:
        return "📚 PIE ANALIZI\nHenuz kapanmis yeterli sinyal yok. Veri toplanıyor."

    # Once ayni mod + en az 1 ortak radar, yoksa sadece ayni mod uzerinden bak.
    similar = []
    module_only = []
    for r in closed:
        r_mods = set([str(r.get("module", "UNKNOWN"))] + [str(x) for x in r.get("support_modules", []) if x])
        if r.get("module") == d.get("module"):
            module_only.append(r)
        if r_mods & current_mods and r.get("module") == d.get("module"):
            similar.append(r)

    sample = similar if len(similar) >= 5 else module_only
    if len(sample) < 5:
        return f"📚 PIE ANALIZI\nBenzer veri az: {len(sample)} kayit. Istatistik icin veri birikiyor."

    n = len(sample)
    tp1 = sum(1 for r in sample if r.get("tp1_hit") or r.get("status") in ("TP1", "TP2", "TP3"))
    tp2 = sum(1 for r in sample if r.get("tp2_hit") or r.get("status") in ("TP2", "TP3"))
    tp3 = sum(1 for r in sample if r.get("tp3_hit") or r.get("status") == "TP3")
    stop = sum(1 for r in sample if pie_is_stop(r))
    avg_max = sum(float(r.get("max_gain_pct", 0) or 0) for r in sample) / n
    avg_dd = sum(float(r.get("max_dd_pct", 0) or 0) for r in sample) / n
    combo = " + ".join(sorted(current_mods))
    return f"""📚 PIE ANALIZI / RADAR IQ
Radar: {combo}
Benzer Kayit: {n}
TP1: %{(tp1/n*100):.1f} | TP2: %{(tp2/n*100):.1f} | TP3: %{(tp3/n*100):.1f}
Stop: %{(stop/n*100):.1f}
Ort. Max: %{avg_max:.2f} | Ort. DD: %{avg_dd:.2f}""".strip()

def explain_reject_summary(symbol, rs, funding_status, flags, money_state_present=False, extra=None):
    if not EXPLAIN_REJECTS:
        return
    try:
        if float(rs or 0) < EXPLAIN_REJECT_MIN_RS and not money_state_present:
            return
    except Exception:
        pass

    true_flags = [k for k, v in flags.items() if bool(v)]
    false_flags = [k for k, v in flags.items() if not bool(v)]
    main_reason = "Radar kosullari henuz olusmadi"
    if float(rs or 0) < EXPLAIN_REJECT_MIN_RS:
        main_reason = f"RS dusuk ({float(rs or 0):.1f} < {EXPLAIN_REJECT_MIN_RS:.0f})"
    elif money_state_present and not true_flags:
        main_reason = "Para hafizasi var ama onay radarlari eksik"
    elif true_flags:
        main_reason = "Aday izleri var ama Elite/Hazirlik kapisi tamamlanmadi"

    shown_false = ", ".join(false_flags[:EXPLAIN_REJECT_MAX_LINES])
    shown_true = ", ".join(true_flags[:EXPLAIN_REJECT_MAX_LINES]) if true_flags else "YOK"
    msg = (
        f"RED OZET: {symbol} | RS {float(rs or 0):.1f} | Funding {funding_status} | "
        f"Aktif: {shown_true} | Eksik: {shown_false} | Sebep: {main_reason}"
    )
    if extra:
        msg += " | " + str(extra)
    print(msg, flush=True)




def ft_now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def ft_load_records():
    if not FULL_TRACKING_ENABLED:
        return []
    try:
        if not os.path.exists(FULL_TRACKING_DATA_FILE):
            return []
        with open(FULL_TRACKING_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print("FULL TRACK load hata:", e, flush=True)
        return []



def ft_has_recent_records(hours=24):
    """Full Tracking kayitlarinda son X saat icinde veri var mi?
    Bos rapor spamini engellemek icin kullanilir.
    """
    if not FULL_TRACKING_ENABLED:
        return False
    try:
        records = ft_load_records()
        if not records:
            return False
        now_ts = time.time()
        limit_ts = now_ts - float(hours) * 3600
        for r in records:
            ts = float(r.get("created_ts", 0) or r.get("last_update_ts", 0) or 0)
            if ts >= limit_ts:
                return True
        return False
    except Exception as e:
        print("FULL TRACK recent kontrol hata:", e, flush=True)
        return False

def ft_save_records(records):
    if not FULL_TRACKING_ENABLED:
        return
    try:
        tmp = FULL_TRACKING_DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records[-FULL_TRACKING_MAX_RECORDS:], f, ensure_ascii=False, indent=2)
        os.replace(tmp, FULL_TRACKING_DATA_FILE)
    except Exception as e:
        print("FULL TRACK save hata:", e, flush=True)

def ft_float(x, default=0.0):
    try:
        return float(x if x is not None else default)
    except Exception:
        return float(default)

def ft_apply_virtual_tp(rec):
    """Ana kanal / hazirlik / gold olmayan erken sinyaller icin sanal TP takibi."""
    if not FULL_TRACKING_ENABLED or not FULL_TRACKING_VIRTUAL_TP_ENABLED or not rec:
        return rec
    first = ft_float(rec.get("first_price"), 0)
    max_price = ft_float(rec.get("max_price"), first)
    min_price = ft_float(rec.get("min_price"), first)
    if first <= 0:
        return rec

    rec.setdefault("virtual_tp_system", "PCT_BASED")
    rec.setdefault("virtual_tp1_pct", FULL_TRACKING_VTP1_PCT)
    rec.setdefault("virtual_tp2_pct", FULL_TRACKING_VTP2_PCT)
    rec.setdefault("virtual_tp3_pct", FULL_TRACKING_VTP3_PCT)
    rec.setdefault("virtual_stop_pct", FULL_TRACKING_VSTOP_PCT)

    gain = ((max_price - first) / first * 100) if first else 0
    dd = ((min_price - first) / first * 100) if first else 0
    rec["virtual_tp1_hit"] = bool(rec.get("virtual_tp1_hit") or gain >= FULL_TRACKING_VTP1_PCT)
    rec["virtual_tp2_hit"] = bool(rec.get("virtual_tp2_hit") or gain >= FULL_TRACKING_VTP2_PCT)
    rec["virtual_tp3_hit"] = bool(rec.get("virtual_tp3_hit") or gain >= FULL_TRACKING_VTP3_PCT)
    rec["virtual_stop_hit"] = bool(rec.get("virtual_stop_hit") or dd <= -FULL_TRACKING_VSTOP_PCT)
    return rec



# ==========================================================
# GOLD RED ANALYZER (VGR)
# Gold olamayan ama ana kanalda/hazirlikta yakalanan coinlerin
# neden Gold kapisindan gecemedigini kaydeder ve rapora yazar.
# ==========================================================
GOLD_RED_ANALYZER_ENABLED = os.getenv("GOLD_RED_ANALYZER_ENABLED", "1") == "1"
GOLD_RED_REQUIRED_SCORE = int(os.getenv("GOLD_RED_REQUIRED_SCORE", "90"))
GOLD_RED_NEAR_SCORE_GAP = int(os.getenv("GOLD_RED_NEAR_SCORE_GAP", "8"))


def gra_float(x, default=0.0):
    try:
        return float(x if x is not None else default)
    except Exception:
        return float(default)


def gold_red_analyze(d, support_modules=None, extra=None, required_score=None):
    """Gold olmayan adaylar icin eksik filtreleri okunabilir hale getirir."""
    if not GOLD_RED_ANALYZER_ENABLED or not d:
        return None
    support_modules = support_modules or []
    extra = extra or {}
    required = int(required_score or GOLD_RED_REQUIRED_SCORE)

    score_candidates = [
        extra.get("elite_score"), d.get("elite_score"), d.get("elite_candidate_score"),
        d.get("elite_confidence_score"), d.get("score")
    ]
    gold_score = 0
    for val in score_candidates:
        try:
            if val is not None:
                gold_score = int(float(val)); break
        except Exception:
            pass
    missing_points = max(0, required - gold_score)

    reasons = []
    passed = []
    module = str(d.get("module", "UNKNOWN"))

    radar_count = 1 + len(support_modules or [])
    if radar_count >= 3:
        passed.append(f"Radar {radar_count}")
    else:
        reasons.append({"reason": "Radar sayisi az", "penalty": 4, "value": str(radar_count)})

    rs_val = gra_float(d.get("rs", d.get("rs_score", 0)))
    if rs_val >= 80:
        passed.append("RS guclu")
    elif rs_val > 0 and rs_val < 65:
        reasons.append({"reason": "RS zayif", "penalty": 4, "value": f"{rs_val:.1f}"})

    money = max(gra_float(d.get("money_impact")), gra_float(d.get("effective_money_impact")), gra_float(d.get("history_money_max")))
    if money >= 2.0:
        passed.append("Para etkisi guclu")
    elif money > 0:
        reasons.append({"reason": "Para etkisi sinirda", "penalty": 3, "value": f"{money:.2f}x"})

    power = max(gra_float(d.get("volume_power")), gra_float(d.get("effective_volume_power")), gra_float(d.get("history_power_max")))
    if power >= 5.0:
        passed.append("Hacim gucu iyi")
    elif power > 0:
        reasons.append({"reason": "Hacim gucu zayif", "penalty": 3, "value": f"{power:.2f}"})

    market = max(gra_float(d.get("market_impact_pct")), gra_float(d.get("effective_market_impact_pct")), gra_float(d.get("history_market_max")))
    if market >= 1.0:
        passed.append("Market etki guclu")
    elif market > 0 and market < 0.25:
        reasons.append({"reason": "Market etki dusuk", "penalty": 3, "value": f"%{market:.2f}"})

    rsi_val = gra_float(d.get("rsi", d.get("rsi15", 0)))
    if rsi_val >= 78:
        reasons.append({"reason": "RSI/FOMO riski", "penalty": 4, "value": f"{rsi_val:.1f}"})
    elif 45 <= rsi_val <= 74:
        passed.append("RSI uygun")

    oi_status = str(d.get("oi_status", d.get("oi_label", ""))).upper()
    if d.get("oi_weak") or "ZAYIF" in oi_status:
        reasons.append({"reason": "OI zayif", "penalty": 4, "value": oi_status or "ZAYIF"})
    elif d.get("oi_long_supported") or d.get("oi_strong_long_supported") or "GUCLU" in oi_status:
        passed.append("OI destekli")

    if d.get("seller_dominant") or d.get("strong_seller_dominant") or gra_float(d.get("net_delta_15m")) < 0:
        reasons.append({"reason": "Delta satici", "penalty": 4, "value": str(d.get("net_delta_15m", ""))})
    elif d.get("buyer_dominant") or d.get("strong_buyer_dominant"):
        passed.append("Delta alici")

    order_flow = int(gra_float(d.get("order_flow_score"), 50))
    if order_flow <= 40:
        reasons.append({"reason": "Order Flow zayif", "penalty": 3, "value": f"{order_flow}/100"})
    elif order_flow >= 60:
        passed.append("Order Flow iyi")

    orderbook = int(gra_float(d.get("orderbook_score"), 50))
    if orderbook <= 38:
        reasons.append({"reason": "Order Book zayif", "penalty": 3, "value": f"{orderbook}/100"})
    elif orderbook >= 60:
        passed.append("Order Book iyi")

    htf = int(gra_float(d.get("htf_trend_score"), 50))
    if htf < 45:
        reasons.append({"reason": "HTF trend zayif", "penalty": 4, "value": f"{htf}/100"})
    elif htf >= 65:
        passed.append("HTF trend guclu")

    resistance = gra_float(d.get("sr_resistance_distance_pct"), 999)
    if 0 <= resistance <= 0.8:
        reasons.append({"reason": "Direnc cok yakin", "penalty": 5, "value": f"%{resistance:.2f}"})
    elif 0.8 < resistance <= 1.5:
        reasons.append({"reason": "Direnc yakin", "penalty": 3, "value": f"%{resistance:.2f}"})
    elif resistance < 999:
        passed.append("Direnc mesafesi uygun")

    funding_status = str(extra.get("funding_status") or d.get("funding_status") or d.get("funding_label") or "").upper()
    if "LONG KALABALIK" in funding_status:
        reasons.append({"reason": "Funding long kalabalik", "penalty": 3, "value": funding_status})
    elif funding_status:
        passed.append("Funding normal")

    btc_status = str(extra.get("btc_status") or d.get("btc_status") or "").upper()
    if "ZAYIF" in btc_status:
        reasons.append({"reason": "BTC zayif", "penalty": 3, "value": btc_status})
    elif "DESTEK" in btc_status:
        passed.append("BTC destekli")

    if d.get("live_guard_ok") is False:
        reasons.append({"reason": "Live Guard red", "penalty": int(gra_float(d.get("live_penalty"), 6) or 6), "value": str(d.get("live_guard_reason", ""))})
    if d.get("gtu_block"):
        reasons.append({"reason": "Grafik-teknik uyumsuz", "penalty": int(gra_float(d.get("gtu_penalty"), 6) or 6), "value": str(d.get("gtu_reasons", ""))[:60]})
    if d.get("fatigue_block"):
        reasons.append({"reason": "Yorgunluk/tepe riski", "penalty": 5, "value": "fatigue"})

    main_repeat = int(gra_float(d.get("main_signal_count_120m", d.get("main_signal_count_60m", 0))))
    if main_repeat >= 3:
        passed.append(f"Ana tekrar {main_repeat}")

    uniq = []
    seen = set()
    for r in sorted(reasons, key=lambda x: int(x.get("penalty", 0)), reverse=True):
        key = r.get("reason")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    closeness = "UZAK"
    if missing_points <= 2:
        closeness = "COK_YAKIN"
    elif missing_points <= GOLD_RED_NEAR_SCORE_GAP:
        closeness = "YAKIN"

    return {
        "module": module,
        "gold_score": gold_score,
        "required_score": required,
        "missing_points": missing_points,
        "closeness": closeness,
        "reasons": uniq[:6],
        "passed": passed[:8],
        "radar_count": radar_count,
    }


def gra_reason_line(analysis):
    if not analysis:
        return "Sebep: veri yok"
    reasons = analysis.get("reasons") or []
    if not reasons:
        return "Sebep: Gold skoru/esik veya kapı şartı eksik"
    return "Sebep: " + ", ".join([f"{r.get('reason')}(-{r.get('penalty')})" for r in reasons[:3]])


def gra_stats_from_records(records):
    stats = {}
    near = 0
    for r in records:
        if r.get("gold_sent"):
            continue
        a = r.get("gold_red_analysis") or {}
        if a.get("closeness") in ("COK_YAKIN", "YAKIN"):
            near += 1
        for reason in a.get("reasons", []) or []:
            name = reason.get("reason", "BILINMIYOR")
            st = stats.setdefault(name, {"n": 0, "tp3": 0})
            st["n"] += 1
            if r.get("virtual_tp3_hit"):
                st["tp3"] += 1
    return stats, near


def gra_stats_text(records):
    stats, near = gra_stats_from_records(records)
    if not stats:
        return "🧠 GOLD RED ANALYZER\nHenüz Gold red nedeni için yeterli kayıt yok."
    rows = sorted(stats.items(), key=lambda kv: (kv[1]["n"], kv[1]["tp3"]), reverse=True)[:8]
    lines = ["🧠 GOLD RED ANALYZER", f"Gold'a yakin kalan aday: {near}", "", "En cok eleyen sebepler:"]
    for name, st in rows:
        lines.append(f"{name}: {st['n']} | TP3 yapan: {st['tp3']}")
    best = None
    for name, st in rows:
        rate = (st['tp3'] / st['n']) if st['n'] else 0
        if st['n'] >= 3 and rate >= 0.40:
            best = (name, st, rate); break
    if best:
        name, st, rate = best
        lines += ["", "🤖 AI NOTU", f"{name} filtresi {st['n']} adayi elemis; bunlarin {st['tp3']} tanesi TP3 yapmis. Bu filtre veri arttikca incelenebilir."]
    return "\n".join(lines)


def gra_missed_details_text(records, limit=8):
    rows = sorted(
        [r for r in records if r.get("missed_after_main") and not r.get("gold_sent")],
        key=lambda r: ft_float(r.get("max_gain_pct"), 0),
        reverse=True
    )[:limit]
    if not rows:
        return "🧠 GOLD RED DETAY\nGold olmadan kaçan detay kaydı yok."
    lines = ["🧠 GOLD RED DETAY"]
    for r in rows:
        a = r.get("gold_red_analysis") or {}
        lines.append(
            "{} +{:.2f}% | Skor:{}/{} | Eksik:{} | {}".format(
                r.get("symbol", "?"),
                ft_float(r.get("max_gain_pct"), 0),
                a.get("gold_score", 0),
                a.get("required_score", GOLD_RED_REQUIRED_SCORE),
                a.get("missing_points", 0),
                gra_reason_line(a)
            )
        )
    return "\n".join(lines)

def ft_record_stage(symbol, d, stage, support_modules=None, extra=None):
    if not FULL_TRACKING_ENABLED or not d:
        return
    support_modules = support_modules or []
    extra = extra or {}
    records = ft_load_records()
    now_ts = time.time()
    price = ft_float(d.get("entry", d.get("price", 0)))
    module = str(d.get("module", "UNKNOWN"))
    rec = None
    for r in reversed(records):
        if r.get("symbol") == symbol and now_ts - ft_float(r.get("created_ts"), 0) <= 24*60*60:
            rec = r
            break
    if rec is None:
        rec = {
            "id": "BINANCE_FULL_{}_{}".format(symbol, int(now_ts)),
            "market": "BINANCE",
            "symbol": symbol,
            "created_at": ft_now_iso(),
            "created_ts": now_ts,
            "first_stage": stage,
            "first_price": price,
            "last_stage": stage,
            "last_price": price,
            "max_price": price,
            "min_price": price,
            "max_gain_pct": 0.0,
            "max_dd_pct": 0.0,
            "main_count": 0,
            "prep_count": 0,
            "gold_count": 0,
            "stages": [],
            "modules": [],
            "support_modules": [],
            "gold_sent": False,
            "missed_after_main": False,
            "virtual_tp1_hit": False,
            "virtual_tp2_hit": False,
            "virtual_tp3_hit": False,
            "virtual_stop_hit": False,
            "last_update_ts": 0,
        }
        records.append(rec)
    rec["last_stage"] = stage
    rec["last_price"] = price or rec.get("last_price", 0)
    if price > 0:
        rec["max_price"] = max(ft_float(rec.get("max_price"), price), price)
        rec["min_price"] = min(ft_float(rec.get("min_price"), price), price)
        first = ft_float(rec.get("first_price"), price)
        rec["max_gain_pct"] = ((ft_float(rec.get("max_price"), price) - first) / first * 100) if first else 0
        rec["max_dd_pct"] = ((ft_float(rec.get("min_price"), price) - first) / first * 100) if first else 0
    if stage == "MAIN":
        rec["main_count"] = int(rec.get("main_count", 0) or 0) + 1
    elif stage == "PREP":
        rec["prep_count"] = int(rec.get("prep_count", 0) or 0) + 1
    elif stage == "GOLD":
        rec["gold_count"] = int(rec.get("gold_count", 0) or 0) + 1
        rec["gold_sent"] = True
    if module and module not in rec.get("modules", []):
        rec.setdefault("modules", []).append(module)
    for s in support_modules:
        if s and s not in rec.get("support_modules", []):
            rec.setdefault("support_modules", []).append(str(s))
    stage_row = {
        "stage": stage,
        "time": ft_now_iso(),
        "ts": now_ts,
        "module": module,
        "price": price,
        "score": int(d.get("score", d.get("elite_score", 0)) or 0),
        "rs": ft_float(d.get("rs", d.get("rs_score", 0))),
        "money_impact": ft_float(d.get("money_impact", d.get("effective_money_impact", 0))),
        "volume_power": ft_float(d.get("volume_power", d.get("effective_volume_power", 0))),
        "support_modules": list(support_modules),
    }
    stage_row.update(extra)
    if stage != "GOLD":
        gra = gold_red_analyze(d, support_modules, extra)
        if gra:
            rec["gold_red_analysis"] = gra
            stage_row["gold_red_analysis"] = gra
    else:
        rec["gold_sent"] = True
        rec["gold_red_analysis"] = None
    rec.setdefault("stages", []).append(stage_row)
    if rec.get("main_count", 0) > 0 and not rec.get("gold_sent") and ft_float(rec.get("max_gain_pct"), 0) >= FULL_TRACKING_MISSED_GAIN_PCT:
        rec["missed_after_main"] = True
    ft_apply_virtual_tp(rec)
    ft_save_records(records)
    print("FULL TRACK RECORD:", symbol, stage, module, "Main:", rec.get("main_count"), "Prep:", rec.get("prep_count"), "Gold:", rec.get("gold_count"), flush=True)

def ft_update_open_records():
    if not FULL_TRACKING_ENABLED:
        return
    records = ft_load_records()
    if not records:
        return
    changed = False
    now_ts = time.time()
    for rec in records:
        if now_ts - ft_float(rec.get("created_ts"), 0) > 48*60*60:
            continue
        if now_ts - ft_float(rec.get("last_update_ts"), 0) < FULL_TRACKING_UPDATE_COOLDOWN_SECONDS:
            continue
        symbol = rec.get("symbol")
        first = ft_float(rec.get("first_price"), 0)
        if not symbol or first <= 0:
            continue
        try:
            ticker = safe_fetch_ticker(symbol)
            if not ticker:
                continue
            price = ft_float(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
            if price <= 0:
                continue
            rec["last_price"] = price
            rec["last_update_ts"] = now_ts
            rec["max_price"] = max(ft_float(rec.get("max_price"), first), price)
            rec["min_price"] = min(ft_float(rec.get("min_price"), first), price)
            rec["max_gain_pct"] = ((ft_float(rec.get("max_price"), first) - first) / first * 100) if first else 0
            rec["max_dd_pct"] = ((ft_float(rec.get("min_price"), first) - first) / first * 100) if first else 0
            if rec.get("main_count", 0) > 0 and not rec.get("gold_sent") and ft_float(rec.get("max_gain_pct"), 0) >= FULL_TRACKING_MISSED_GAIN_PCT:
                rec["missed_after_main"] = True
            ft_apply_virtual_tp(rec)
            changed = True
        except Exception as e:
            print("FULL TRACK update hata:", symbol, e, flush=True)
    if changed:
        ft_save_records(records)

def ft_daily_report_text(market_name="BINANCE"):
    if not FULL_TRACKING_ENABLED:
        return "📊 FULL TRACKING kapali."
    records = ft_load_records()
    now_ts = time.time()
    recent = [r for r in records if now_ts - ft_float(r.get("created_ts"), 0) <= 24*60*60]
    if not recent:
        return "📊 {} FULL TRACKING\n\nSon 24 saatte ana/hazirlik/gold kaydi yok.".format(market_name)
    main = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0)
    prep = sum(1 for r in recent if int(r.get("prep_count", 0) or 0) > 0)
    gold = sum(1 for r in recent if int(r.get("gold_count", 0) or 0) > 0)
    main_10 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and ft_float(r.get("max_gain_pct"), 0) >= FULL_TRACKING_MISSED_GAIN_PCT)
    missed = sum(1 for r in recent if r.get("missed_after_main") and not r.get("gold_sent"))
    vtp1 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp1_hit"))
    vtp2 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp2_hit"))
    vtp3 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp3_hit"))
    vstop = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_stop_hit"))
    vtp3_no_gold = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp3_hit") and not r.get("gold_sent"))
    avg_max = sum(ft_float(r.get("max_gain_pct"), 0) for r in recent) / len(recent)
    by_module = {}
    for r in recent:
        mod = (r.get("modules") or ["UNKNOWN"])[0]
        by_module.setdefault(mod, {"n": 0, "m10": 0})
        by_module[mod]["n"] += 1
        if ft_float(r.get("max_gain_pct"), 0) >= FULL_TRACKING_MISSED_GAIN_PCT:
            by_module[mod]["m10"] += 1
    best_mod = "YOK"
    if by_module:
        name, st = sorted(by_module.items(), key=lambda kv: ((kv[1]["m10"] / kv[1]["n"]) if kv[1]["n"] else 0, kv[1]["n"]), reverse=True)[0]
        best_mod = "{} ({}/{} %{:.0f})".format(name, st["m10"], st["n"], (st["m10"] / st["n"] * 100 if st["n"] else 0))
    missed_rows = sorted(
        [r for r in recent if r.get("missed_after_main") and not r.get("gold_sent")],
        key=lambda r: ft_float(r.get("max_gain_pct"), 0),
        reverse=True
    )[:8]
    missed_text = "\n".join(
        "{} +{:.2f}% | Ana:{} | Mod:{}".format(
            r.get("symbol", "?"),
            ft_float(r.get("max_gain_pct"), 0),
            int(r.get("main_count", 0) or 0),
            (r.get("modules") or ["UNKNOWN"])[0]
        )
        for r in missed_rows
    ) if missed_rows else "YOK"

    vtp3_rows = sorted(
        [r for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp3_hit") and not r.get("gold_sent")],
        key=lambda r: ft_float(r.get("max_gain_pct"), 0),
        reverse=True
    )[:8]
    vtp3_text = "\n".join(
        "{} +{:.2f}% | Ana:{} | Mod:{}".format(
            r.get("symbol", "?"),
            ft_float(r.get("max_gain_pct"), 0),
            int(r.get("main_count", 0) or 0),
            (r.get("modules") or ["UNKNOWN"])[0]
        )
        for r in vtp3_rows
    ) if vtp3_rows else "YOK"

    stopped_rows = sorted(
        [r for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_stop_hit") and not r.get("virtual_tp1_hit")],
        key=lambda r: ft_float(r.get("max_dd_pct"), 0)
    )[:6]
    stopped_text = "\n".join(
        "{} {:.2f}% | Ana:{} | Mod:{}".format(
            r.get("symbol", "?"),
            ft_float(r.get("max_dd_pct"), 0),
            int(r.get("main_count", 0) or 0),
            (r.get("modules") or ["UNKNOWN"])[0]
        )
        for r in stopped_rows
    ) if stopped_rows else "YOK"

    return """
📊 {} FULL LIFE TRACKING RAPORU

Ana Kanal Kaydi: {}
Elite Hazirlik: {}
Elite Gold: {}
Ana Kanal %{:.0f}+ Giden: {}
Gold Olmadan Kacan: {}

🎯 Sanal TP Takibi
Sanal TP1 (+{:.0f}%): {}
Sanal TP2 (+{:.0f}%): {}
Sanal TP3 (+{:.0f}%): {}
Sanal Stop (-{:.0f}%): {}
Gold Olmadan Sanal TP3: {}

📈 Gold Olmadan Ana Kanal TP3 Yapanlar
{}

⚠️ Gold Olmadan Kacan Firsatlar
{}

🔻 Ana Kanaldan Stop Olanlar
{}

{}

{}

Ort. Max Hareket: %{:.2f}
En iyi erken mod: {}

Not:
Bu rapor gideni, gitmeyeni ve Gold'a donusmeyen erken firsatlari coin bazli gosterir.
""".format(market_name, main, prep, gold, FULL_TRACKING_MISSED_GAIN_PCT, main_10, missed, FULL_TRACKING_VTP1_PCT, vtp1, FULL_TRACKING_VTP2_PCT, vtp2, FULL_TRACKING_VTP3_PCT, vtp3, FULL_TRACKING_VSTOP_PCT, vstop, vtp3_no_gold, vtp3_text, missed_text, stopped_text, gra_missed_details_text(recent), gra_stats_text(recent), avg_max, best_mod).strip()


def ft_period_report_text(days=7, label="HAFTALIK", market_name="BOT"):
    """V58: Gunluk/haftalik/aylik performans merkezi raporu."""
    if not FULL_TRACKING_ENABLED:
        return "📊 FULL TRACKING kapali."
    records = ft_load_records()
    now_ts = time.time()
    window = float(days) * 24 * 60 * 60
    recent = [r for r in records if now_ts - ft_float(r.get("created_ts"), 0) <= window]
    if not recent:
        return "📊 {} {} RAPORU\n\nSon {} gunde kayit yok.".format(market_name, label, days)

    main = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0)
    prep = sum(1 for r in recent if int(r.get("prep_count", 0) or 0) > 0)
    gold = sum(1 for r in recent if int(r.get("gold_count", 0) or 0) > 0)
    missed = sum(1 for r in recent if r.get("missed_after_main") and not r.get("gold_sent"))
    vtp1 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp1_hit"))
    vtp2 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp2_hit"))
    vtp3 = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp3_hit"))
    vstop = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_stop_hit"))
    vtp3_no_gold = sum(1 for r in recent if int(r.get("main_count", 0) or 0) > 0 and r.get("virtual_tp3_hit") and not r.get("gold_sent"))

    def top_modules(records, limit=5):
        stats = {}
        for r in records:
            mods = r.get("modules") or ["UNKNOWN"]
            for m in mods:
                st = stats.setdefault(str(m), {"n": 0, "tp3": 0, "missed": 0, "max": 0.0})
                st["n"] += 1
                st["tp3"] += 1 if r.get("virtual_tp3_hit") else 0
                st["missed"] += 1 if r.get("missed_after_main") and not r.get("gold_sent") else 0
                st["max"] += ft_float(r.get("max_gain_pct"), 0)
        rows = []
        for name, st in stats.items():
            rate = st["tp3"] / st["n"] * 100 if st["n"] else 0
            avg = st["max"] / st["n"] if st["n"] else 0
            rows.append((rate, st["n"], name, avg, st["missed"]))
        rows.sort(reverse=True)
        return "\n".join(["{} | {} kayit | TP3 %{:.0f} | Ort Max %{:.2f} | Kacan {}".format(name, n, rate, avg, missed) for rate, n, name, avg, missed in rows[:limit]]) or "YOK"

    top_missed_rows = sorted(
        [r for r in recent if r.get("missed_after_main") and not r.get("gold_sent")],
        key=lambda r: ft_float(r.get("max_gain_pct"), 0),
        reverse=True
    )[:8]
    missed_text = "\n".join([
        "{} +{:.2f}% | Ana:{} | Mod:{}".format(
            r.get("symbol", "?"), ft_float(r.get("max_gain_pct"), 0), int(r.get("main_count", 0) or 0), (r.get("modules") or ["UNKNOWN"])[0]
        ) for r in top_missed_rows
    ]) if top_missed_rows else "YOK"

    avg_max = sum(ft_float(r.get("max_gain_pct"), 0) for r in recent) / len(recent)
    gold_rate = gold / main * 100 if main else 0
    prep_rate = prep / main * 100 if main else 0
    tp3_rate = vtp3 / main * 100 if main else 0

    return """
📊 {} {} PERFORMANS MERKEZI

Kapsam: Son {} gun
Ana Kanal: {}
Elite Hazirlik: {} (%{:.1f})
Elite Gold: {} (%{:.1f})

🎯 Ana Kanal Sanal TP
TP1: {}
TP2: {}
TP3: {} (%{:.1f})
Stop: {}
Gold olmadan TP3: {}
Gold olmadan kacan: {}

🏆 En iyi erken modlar
{}

🚨 En cok kacan firsatlar
{}

{}

{}

Ort. Max Hareket: %{:.2f}
""".format(market_name, label, days, main, prep, prep_rate, gold, gold_rate, vtp1, vtp2, vtp3, tp3_rate, vstop, vtp3_no_gold, missed, top_modules(recent), missed_text, gra_missed_details_text(recent), gra_stats_text(recent), avg_max).strip()


def performance_center_reports_if_due(chat_id=None, market_name="BOT"):
    """V58: Haftalik ve aylik raporlari zamaninda gonderir."""
    if not PERFORMANCE_CENTER_ENABLED:
        return
    now = datetime.utcnow()
    if now.hour < PERFORMANCE_REPORT_HOUR_UTC:
        return
    ft_update_open_records()

    def already_sent(path, key):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip() == key
        except Exception:
            pass
        return False

    def mark_sent(path, key):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(key)
        except Exception as e:
            print("Performance state hata:", e, flush=True)

    if PERFORMANCE_WEEKLY_REPORT_ENABLED and now.weekday() == PERFORMANCE_WEEKLY_DAY_UTC:
        week_key = now.strftime("%Y-W%W")
        if not already_sent(PERFORMANCE_WEEKLY_STATE_FILE, week_key):
            if PERFORMANCE_SEND_EMPTY_REPORTS or ft_has_recent_records(7):
                send_telegram(ft_period_report_text(7, "HAFTALIK", market_name), chat_id)
            else:
                print(f"{market_name} weekly report atlandi: kayit yok", flush=True)
            mark_sent(PERFORMANCE_WEEKLY_STATE_FILE, week_key)

    if PERFORMANCE_MONTHLY_REPORT_ENABLED and now.day == PERFORMANCE_MONTHLY_DAY_UTC:
        month_key = now.strftime("%Y-%m")
        if not already_sent(PERFORMANCE_MONTHLY_STATE_FILE, month_key):
            if PERFORMANCE_SEND_EMPTY_REPORTS or ft_has_recent_records(30):
                send_telegram(ft_period_report_text(30, "AYLIK", market_name), chat_id)
            else:
                print(f"{market_name} monthly report atlandi: kayit yok", flush=True)
            mark_sent(PERFORMANCE_MONTHLY_STATE_FILE, month_key)

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
COOLDOWN_PRE_BREAKOUT_WATCH = 75 * 60
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

# V43 TREND DEVAM GUVENI:
# BEAT/DYDX gibi sessiz trend sinyalleri ana kanala 2-3 kez dusup yurumeye devam ederse
# bu tekrarlar sadece spam sayilmaz; Elite Hazirlik/Gold puanina kontrollu bonus olarak yansir.
TREND_CONT_MIN_REPEAT_60M = int(os.getenv("TREND_CONT_MIN_REPEAT_60M", "2"))
TREND_CONT_MIN_REPEAT_120M = int(os.getenv("TREND_CONT_MIN_REPEAT_120M", "3"))
TREND_CONT_MAX_GAIN = float(os.getenv("TREND_CONT_MAX_GAIN", "22"))
TREND_CONT_MIN_SCORE = int(os.getenv("TREND_CONT_MIN_SCORE", "45"))
TREND_CONT_BONUS_MID = int(os.getenv("TREND_CONT_BONUS_MID", "10"))
TREND_CONT_BONUS_STRONG = int(os.getenv("TREND_CONT_BONUS_STRONG", "18"))

MEMORY_REENTRY_MIN_HISTORY = 24
MEMORY_REENTRY_MIN_MONEY = 1.80
MEMORY_REENTRY_MIN_POWER = 3.00
SECOND_WAVE_MIN_15M_USDT = 30_000
SECOND_WAVE_MIN_30M_USDT = 80_000
ELITE_REENTRY_COOLDOWN = 90 * 60

# V16 STO/BEL/LUMIA FIX: Ana kanalda tam yerinde görünen squeeze patlamaları
# tek radar diye Elite kapısından dönmesin. Henüz fiyat kaçmadan gelen
# sıkışma kırılımı + para/hacim + OBV/MACD birleşimini Elite’e zorlar.
PRE_ROCKET_MIN_MONEY = 1.75
PRE_ROCKET_MIN_VOL_RATIO = 1.80
PRE_ROCKET_MIN_POWER = 4.80
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

# V24 KAT FIX: Direncin hemen altında, hafıza/re-entry ile geç gelen AL sinyallerini kes.
# KAT örneği: direnç mesafesi %0.43, ana kanal tekrar 7, ikinci dalga var ama fiyat tepe sonrası düşüyordu.
SR_HARD_BLOCK_PCT = 0.55
SR_MEMORY_LATE_BLOCK_PCT = 0.90
SR_MEMORY_REPEAT_BLOCK_COUNT = 5
SR_NEAR_RESISTANCE_EXTRA_PENALTY = 18

# V25 CANLI PULLBACK / SATIS BASKISI FILTRESI:
# SYN / KAT tipi: coin hafizada guclu gorunse bile son mumlarda satis basladiysa
# Elite AL vermesin veya skoru ciddi dussun.
PULLBACK_RED_CANDLE_PENALTY = 10
PULLBACK_TWO_RED_PENALTY = 14
PULLBACK_MACD_WEAK_PENALTY = 10
PULLBACK_OBV_FALL_PENALTY = 10
PULLBACK_RSI_DROP_PENALTY = 8
PULLBACK_EMA9_LOST_PENALTY = 14
PULLBACK_FROM_HIGH_WARN = 4.0
PULLBACK_FROM_HIGH_BLOCK = 6.0
PULLBACK_TOTAL_BLOCK_SCORE = 32

# V26 GRAFIK / TEKNIK UYUMSUZLUK FILTRESI:
# Teknik/hafiza/para AL diyor ama grafik son mumlarda dusus veya yorulma gosteriyorsa
# Elite AL yerine izleme kalsin. KAT/SYN tipi gec AL sinyallerini azaltir.
ALIGNMENT_WARN_PENALTY = 10
ALIGNMENT_WEAK_PENALTY = 18
ALIGNMENT_BLOCK_PENALTY = 32
ALIGNMENT_BLOCK_SCORE = 45

# V28 ORDER BOOK / EMIR DEFTERI DUVAR SKORU:
# Binance order book ile alis-satis duvarlarini, yukari likidite boslugunu
# ve direnc altinda satis duvari riskini olcer.
ORDERBOOK_CACHE_SECONDS = 20
ORDERBOOK_LIMIT = 50
ORDERBOOK_NEAR_PCT = 1.00
ORDERBOOK_WALL_LOOK_PCT = 2.00
ORDERBOOK_WALL_MULTIPLIER = 3.00
ORDERBOOK_MIN_WALL_USDT = 25_000
ORDERBOOK_STRONG_IMBALANCE = 1.60
ORDERBOOK_WEAK_IMBALANCE = 0.65
ORDERBOOK_ASK_WALL_CLOSE_PCT = 0.75
ORDERBOOK_BID_WALL_CLOSE_PCT = 0.75
ORDERBOOK_SCORE_BONUS_STRONG = 8
ORDERBOOK_SCORE_BONUS_OK = 4
ORDERBOOK_SCORE_PENALTY_WEAK = 10
ORDERBOOK_ASK_WALL_PENALTY = 14

# V29 ORDER FLOW / LIKIDITE BOSLUGU / LIKIDASYON PROXY:
# Binance taker flow + OI + order book verisini birlestirip
# alici gercekten saldiriyor mu ve yukari sikisma ihtimali var mi olcer.
ORDERFLOW_STRONG_SCORE = 78
ORDERFLOW_WEAK_SCORE = 38
ORDERFLOW_BLOCK_SCORE = 28
ORDERFLOW_BUY_SELL_RATIO_STRONG = 1.80
ORDERFLOW_BUY_SELL_RATIO_WEAK = 0.70
ORDERFLOW_DELTA_STRONG = 12.0
ORDERFLOW_DELTA_WEAK = -10.0
ORDERFLOW_SCORE_BONUS_STRONG = 10
ORDERFLOW_SCORE_BONUS_OK = 5
ORDERFLOW_SCORE_PENALTY_WEAK = 12
LIQUIDITY_GAP_SCORE_BONUS = 7
LIQUIDATION_PROXY_BONUS = 6

# V30 SERT KALITE KAPILARI:
# Liste icinden eksik kalan pratik parcalar: saatlik/4s trend skoru, delta guc kapisi,
# cok yakin direnc sert blok ve yukselis yorgunlugu filtresi.
HTF_TREND_MIN_FOR_ELITE = 48
HTF_TREND_MIN_FOR_GOLD = 65
HTF_TREND_BONUS_STRONG = 8
HTF_TREND_PENALTY_WEAK = 14
DELTA_POWER_MIN_RATIO = 3.0
DELTA_POWER_MIN_ORDERFLOW = 55
DELTA_POWER_BLOCK_ORDERFLOW = 45
HARD_RESISTANCE_BLOCK_PCT = 0.30
FATIGUE_6H_GAIN_WARN = 12.0
FATIGUE_6H_GAIN_BLOCK = 15.0
FATIGUE_PULLBACK_MIN = 1.2
FATIGUE_PENALTY = 22

# V31 CVD / KUMULATIF DELTA:
# Binance taker long/short akisini hafizada biriktirir.
# Tek mumluk delta degil; son 30/60/120 dk alici-satici birikimi ve fiyatla uyumunu olcer.
CVD_MEMORY_EXPIRE_SECONDS = 2 * 60 * 60
CVD_EVENT_DEDUP_SECONDS = 90
CVD_STRONG_SCORE = 78
CVD_WEAK_SCORE = 38
CVD_BLOCK_SCORE = 30
CVD_SCORE_BONUS_STRONG = 10
CVD_SCORE_BONUS_OK = 5
CVD_SCORE_PENALTY_WEAK = 12
CVD_DIVERGENCE_PENALTY = 14

# V36 AI KARAR KATMANI:
# Radar agirligi + radar sirasi + canli orderflow/CVD/HTF uyumu tek Elite Guven Skorunda toplanir.
# Bu skor, Elite Skoru 100 olsa bile gec/tek radar ve satici akisli sinyalleri kesmek icin kullanilir.
BINANCE_ELITE_CONFIDENCE_BLOCK_SCORE = 35
BINANCE_ELITE_CONFIDENCE_WARN_SCORE = 55
BINANCE_ELITE_CONFIDENCE_BONUS_SCORE = 75

MIN_EARLY_RS = 70
MIN_SAFE_CONFIDENCE = 68
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
sent_pre_breakout_watch = {}
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
orderbook_cache = {}
cvd_memory = {}

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


def send_log(msg):
    """Teknik log/hata mesajlarini ayri kanala yollar."""
    try:
        send_telegram(msg, BINANCE_LOG_CHAT_ID)
    except Exception as e:
        print("Log kanal hata:", e, flush=True)


def pie_now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def pie_load_records():
    if not PIE_ENABLED:
        return []
    try:
        if not os.path.exists(PIE_DATA_FILE):
            return []
        with open(PIE_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print("PIE load hata:", e, flush=True)
        return []


def pie_save_records(records):
    if not PIE_ENABLED:
        return
    try:
        tmp = PIE_DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PIE_DATA_FILE)
    except Exception as e:
        print("PIE save hata:", e, flush=True)


def pie_float(x, default=0.0):
    try:
        return float(x or default)
    except Exception:
        return float(default)


def pie_build_binance_levels(d):
    try:
        levels = build_entry_levels(d)
        return {
            "entry": pie_float(levels.get("entry")),
            "stop": pie_float(levels.get("stop")),
            "tp1": pie_float(levels.get("tp1")),
            "tp2": pie_float(levels.get("tp2")),
            "tp3": pie_float(levels.get("tp3")),
            "risk_pct": pie_float(levels.get("risk_pct")),
            "tp_system": levels.get("tp_system", "RISK_BAZLI"),
        }
    except Exception:
        price = pie_float(d.get("entry", d.get("price", 0)))
        risk_pct = 0.032 if d.get("module") in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP") else 0.028
        return {"entry": price, "stop": price * (1 - risk_pct), "tp1": price * (1 + risk_pct * 1.2), "tp2": price * (1 + risk_pct * 1.8), "tp3": price * (1 + risk_pct * 2.6), "risk_pct": risk_pct * 100, "tp_system": "RISK_BAZLI"}


def pie_record_elite_signal(symbol, d, support_modules, elite_score, levels=None, market="BINANCE"):
    if not PIE_ENABLED:
        return
    levels = levels or pie_build_binance_levels(d)
    records = pie_load_records()
    now_ts = time.time()
    signal_id = f"{market}_{symbol}_{d.get('module','UNKNOWN')}_{int(now_ts)}"
    rec = {
        "id": signal_id,
        "market": market,
        "bot_name": BOT_NAME,
        "symbol": symbol,
        "module": d.get("module", "UNKNOWN"),
        "support_modules": list(support_modules or []),
        "created_at": pie_now_iso(),
        "created_ts": now_ts,
        "status": "OPEN",
        "entry": pie_float(levels.get("entry")),
        "stop": pie_float(levels.get("stop")),
        "tp1": pie_float(levels.get("tp1")),
        "tp2": pie_float(levels.get("tp2")),
        "tp3": pie_float(levels.get("tp3")),
        "tp_system": levels.get("tp_system", d.get("tp_mode", "YOK")),
        "elite_score": int(elite_score or 0),
        "elite_confidence_score": int(d.get("elite_confidence_score", 50) or 50),
        "elite_confidence_label": d.get("elite_confidence_label", "YOK"),
        "radar_count": 1 + len(support_modules or []),
        "btc_status": d.get("btc_status", ""),
        "market_impact_pct": pie_float(d.get("market_impact_pct")),
        "money_impact": pie_float(d.get("money_impact")),
        "volume_power": pie_float(d.get("volume_power")),
        "order_flow_score": int(d.get("order_flow_score", 50) or 50),
        "orderbook_score": int(d.get("orderbook_score", 50) or 50),
        "htf_trend_score": int(d.get("htf_trend_score", 50) or 50),
        "sr_resistance_distance_pct": pie_float(d.get("resistance_distance_pct", d.get("sr_resistance_distance_pct", 999)), 999),
        "max_price": pie_float(levels.get("entry")),
        "min_price": pie_float(levels.get("entry")),
        "max_gain_pct": 0.0,
        "max_dd_pct": 0.0,
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "stop_hit": False,
        "last_update_ts": 0,
    }
    records.append(rec)
    # Dosya sisip kalmasin: son 500 kayit yeterli.
    pie_save_records(records[-500:])
    print("PIE RECORD:", signal_id, symbol, d.get("module"), "Entry:", rec["entry"], "TP1:", rec["tp1"], "Stop:", rec["stop"], flush=True)


def pie_format_update(rec, event, price):
    elapsed_min = int((time.time() - float(rec.get("created_ts", time.time()))) / 60)
    return f"""
📊 PIE SINYAL TAKIP - {event}

Coin: {rec.get('symbol')}
Mod: {rec.get('module')}
Giris: {pie_float(rec.get('entry')):.8f}
Anlik: {pie_float(price):.8f}
Max: %{pie_float(rec.get('max_gain_pct')):.2f}
DD: %{pie_float(rec.get('max_dd_pct')):.2f}
Sure: {elapsed_min} dk
Elite: {rec.get('elite_score')}/100 | Guven: {rec.get('elite_confidence_score')}/100
""".strip()


def pie_update_open_signals(chat_id=None):
    if not PIE_ENABLED:
        return
    records = pie_load_records()
    if not records:
        return
    changed = False
    now_ts = time.time()
    for rec in records:
        if rec.get("status") not in ("OPEN", "TP1", "TP2"):
            continue
        if now_ts - float(rec.get("last_update_ts", 0) or 0) < PIE_UPDATE_COOLDOWN_SECONDS:
            continue
        symbol = rec.get("symbol")
        entry = pie_float(rec.get("entry"))
        if not symbol or entry <= 0:
            continue
        try:
            ticker = safe_fetch_ticker(symbol)
            if not ticker:
                continue
            price = pie_float(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
            if price <= 0:
                continue
            rec["last_price"] = price
            rec["last_update_ts"] = now_ts
            rec["max_price"] = max(pie_float(rec.get("max_price"), entry), price)
            rec["min_price"] = min(pie_float(rec.get("min_price"), entry), price)
            rec["max_gain_pct"] = ((rec["max_price"] - entry) / entry * 100) if entry else 0
            rec["max_dd_pct"] = ((rec["min_price"] - entry) / entry * 100) if entry else 0
            event = None
            if price <= pie_float(rec.get("stop")) and not rec.get("tp1_hit"):
                rec["stop_hit"] = True; rec["status"] = "STOP"; event = "STOP"
            elif price >= pie_float(rec.get("tp3")):
                rec["tp1_hit"] = rec["tp2_hit"] = rec["tp3_hit"] = True; rec["status"] = "TP3"; event = "TP3"
            elif price >= pie_float(rec.get("tp2")) and not rec.get("tp2_hit"):
                rec["tp1_hit"] = rec["tp2_hit"] = True; rec["status"] = "TP2"; event = "TP2"
            elif price >= pie_float(rec.get("tp1")) and not rec.get("tp1_hit"):
                rec["tp1_hit"] = True; rec["status"] = "TP1"; event = "TP1"
            elif (now_ts - float(rec.get("created_ts", now_ts))) > PIE_MAX_TRACK_HOURS * 3600:
                rec["status"] = "EXPIRED"; event = "SURE DOLDU"
            if event:
                send_telegram(pie_format_update(rec, event, price), chat_id)
            changed = True
        except Exception as e:
            print("PIE update hata:", symbol, e, flush=True)
    if changed:
        pie_save_records(records)


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
            data = safe_fetch_ohlcv(symbol, timeframe, limit=limit)
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
            ticker = safe_fetch_ticker(symbol)
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


def fetch_orderbook_context(symbol, price=None):
    """
    V28 ORDER BOOK KONTROLU:
    Binance emir defterinden yakindaki alis/satis duvarlarini ve likidite boslugunu olcer.
    Bu veri karar icindir; mesajda sade sekilde Order Book skoru/status olarak gosterilir.
    """
    cache_key = f"{symbol}_ob"
    now = time.time()
    cached = orderbook_cache.get(cache_key)
    if cached and now - cached.get("time", 0) < ORDERBOOK_CACHE_SECONDS:
        return cached.get("data")

    out = {
        "orderbook_ok": False,
        "orderbook_score": 50,
        "orderbook_status": "ORDERBOOK VERI YOK",
        "bid_wall_price": 0.0,
        "bid_wall_usdt": 0.0,
        "bid_wall_distance_pct": 999.0,
        "ask_wall_price": 0.0,
        "ask_wall_usdt": 0.0,
        "ask_wall_distance_pct": 999.0,
        "bid_usdt_1pct": 0.0,
        "ask_usdt_1pct": 0.0,
        "book_imbalance": 1.0,
        "liquidity_gap_up": False,
        "liquidity_gap_down": False,
        "orderbook_block": False,
        "orderbook_reason": "VERI YOK",
    }

    try:
        ob = exchange.fetch_order_book(symbol, limit=ORDERBOOK_LIMIT)
        bids = ob.get("bids", []) or []
        asks = ob.get("asks", []) or []
        if not bids or not asks:
            orderbook_cache[cache_key] = {"time": now, "data": out}
            return out

        live_price = float(price or 0)
        if live_price <= 0:
            live_price = float((bids[0][0] + asks[0][0]) / 2)
        if live_price <= 0:
            orderbook_cache[cache_key] = {"time": now, "data": out}
            return out

        def level_usdt(level):
            return float(level[0]) * float(level[1])

        bids_1 = [b for b in bids if 0 <= (live_price - float(b[0])) / live_price * 100 <= ORDERBOOK_NEAR_PCT]
        asks_1 = [a for a in asks if 0 <= (float(a[0]) - live_price) / live_price * 100 <= ORDERBOOK_NEAR_PCT]
        bids_2 = [b for b in bids if 0 <= (live_price - float(b[0])) / live_price * 100 <= ORDERBOOK_WALL_LOOK_PCT]
        asks_2 = [a for a in asks if 0 <= (float(a[0]) - live_price) / live_price * 100 <= ORDERBOOK_WALL_LOOK_PCT]

        bid_usdt_1 = sum(level_usdt(x) for x in bids_1)
        ask_usdt_1 = sum(level_usdt(x) for x in asks_1)
        imbalance = (bid_usdt_1 + 1.0) / (ask_usdt_1 + 1.0)

        avg_bid = (sum(level_usdt(x) for x in bids_2) / len(bids_2)) if bids_2 else 0.0
        avg_ask = (sum(level_usdt(x) for x in asks_2) / len(asks_2)) if asks_2 else 0.0
        bid_wall = max(bids_2, key=level_usdt) if bids_2 else None
        ask_wall = max(asks_2, key=level_usdt) if asks_2 else None

        bid_wall_price = float(bid_wall[0]) if bid_wall else 0.0
        ask_wall_price = float(ask_wall[0]) if ask_wall else 0.0
        bid_wall_usdt = level_usdt(bid_wall) if bid_wall else 0.0
        ask_wall_usdt = level_usdt(ask_wall) if ask_wall else 0.0
        bid_wall_dist = ((live_price - bid_wall_price) / live_price * 100) if bid_wall_price > 0 else 999.0
        ask_wall_dist = ((ask_wall_price - live_price) / live_price * 100) if ask_wall_price > 0 else 999.0

        real_bid_wall = bid_wall_usdt >= max(ORDERBOOK_MIN_WALL_USDT, avg_bid * ORDERBOOK_WALL_MULTIPLIER) if avg_bid > 0 else False
        real_ask_wall = ask_wall_usdt >= max(ORDERBOOK_MIN_WALL_USDT, avg_ask * ORDERBOOK_WALL_MULTIPLIER) if avg_ask > 0 else False

        liquidity_gap_up = bool(ask_usdt_1 > 0 and bid_usdt_1 > ask_usdt_1 * 1.8 and (not real_ask_wall or ask_wall_dist > 1.2))
        liquidity_gap_down = bool(bid_usdt_1 > 0 and ask_usdt_1 > bid_usdt_1 * 1.8 and (not real_bid_wall or bid_wall_dist > 1.2))

        score = 50
        reasons = []
        if imbalance >= ORDERBOOK_STRONG_IMBALANCE:
            score += 18; reasons.append("alis tarafi guclu")
        elif imbalance >= 1.15:
            score += 8; reasons.append("alis tarafi onde")
        elif imbalance <= ORDERBOOK_WEAK_IMBALANCE:
            score -= 18; reasons.append("satis tarafi guclu")
        elif imbalance <= 0.85:
            score -= 8; reasons.append("satis tarafi onde")

        if real_bid_wall and bid_wall_dist <= ORDERBOOK_BID_WALL_CLOSE_PCT:
            score += 10; reasons.append("yakinda alis duvari")
        if real_ask_wall and ask_wall_dist <= ORDERBOOK_ASK_WALL_CLOSE_PCT:
            score -= 16; reasons.append("yakinda satis duvari")
        if liquidity_gap_up:
            score += 10; reasons.append("yukari likidite boslugu")
        if liquidity_gap_down:
            score -= 10; reasons.append("asagi likidite boslugu")

        orderbook_block = bool(real_ask_wall and ask_wall_dist <= 0.45 and imbalance <= 1.05 and ask_wall_usdt > bid_wall_usdt * 1.2)
        if orderbook_block:
            reasons.append("satis duvari cok yakin")

        score = int(max(0, min(100, round(score))))
        if orderbook_block:
            status = "SATICI_DUVARI_BLOCK"
        elif score >= 72:
            status = "ALICI USTUN"
        elif score >= 60:
            status = "ALICI AVANTAJLI"
        elif score <= 30:
            status = "SATICI USTUN"
        elif score <= 42:
            status = "SATICI AVANTAJLI"
        else:
            status = "DENGELI"

        out.update({
            "orderbook_ok": True,
            "orderbook_score": score,
            "orderbook_status": status,
            "bid_wall_price": bid_wall_price,
            "bid_wall_usdt": bid_wall_usdt if real_bid_wall else 0.0,
            "bid_wall_distance_pct": bid_wall_dist if real_bid_wall else 999.0,
            "ask_wall_price": ask_wall_price,
            "ask_wall_usdt": ask_wall_usdt if real_ask_wall else 0.0,
            "ask_wall_distance_pct": ask_wall_dist if real_ask_wall else 999.0,
            "bid_usdt_1pct": bid_usdt_1,
            "ask_usdt_1pct": ask_usdt_1,
            "book_imbalance": imbalance,
            "liquidity_gap_up": liquidity_gap_up,
            "liquidity_gap_down": liquidity_gap_down,
            "orderbook_block": orderbook_block,
            "orderbook_reason": ", ".join(reasons[:5]) if reasons else "DENGELI",
        })
        orderbook_cache[cache_key] = {"time": now, "data": out}
        return out
    except Exception as e:
        print("Order book context hata:", symbol, e, flush=True)
        orderbook_cache[cache_key] = {"time": now, "data": out}
        return out


def attach_orderbook_context(symbol, d):
    if not d:
        return d
    price = float(d.get("entry", d.get("price", 0)) or 0)
    ob = fetch_orderbook_context(symbol, price)
    d.update(ob)
    return d


def attach_orderflow_context(symbol, d):
    """
    V29 ORDER FLOW SKORU:
    Taker long/short akisi, delta, OI ve order book boslugunu birlestirir.
    Gercek Coinglass likidasyon haritasi degildir; Binance verisinden squeeze/likidasyon PROXY uretir.
    """
    if not d:
        return d

    long15 = float(d.get("long_flow_15m", 0) or 0)
    short15 = float(d.get("short_flow_15m", 0) or 0)
    long1h = float(d.get("long_flow_1h", 0) or 0)
    short1h = float(d.get("short_flow_1h", 0) or 0)
    delta15 = float(d.get("delta_ratio_15m", 0) or 0)
    delta1h = float(d.get("delta_ratio_1h", 0) or 0)
    oi15 = float(d.get("oi_15m_pct", 0) or 0)
    oi1h = float(d.get("oi_1h_pct", 0) or 0)
    ob_score = int(d.get("orderbook_score", 50) or 50)

    total15 = long15 + short15
    total1h = long1h + short1h
    buy_sell_ratio_15m = (long15 + 1.0) / (short15 + 1.0)
    buy_sell_ratio_1h = (long1h + 1.0) / (short1h + 1.0)

    score = 50
    reasons = []

    if buy_sell_ratio_15m >= ORDERFLOW_BUY_SELL_RATIO_STRONG:
        score += 18; reasons.append("15m agresif alici")
    elif buy_sell_ratio_15m >= 1.20:
        score += 8; reasons.append("15m alici onde")
    elif buy_sell_ratio_15m <= ORDERFLOW_BUY_SELL_RATIO_WEAK:
        score -= 18; reasons.append("15m agresif satici")
    elif buy_sell_ratio_15m <= 0.85:
        score -= 8; reasons.append("15m satici onde")

    if delta15 >= ORDERFLOW_DELTA_STRONG:
        score += 14; reasons.append("delta pozitif")
    elif delta15 >= 6:
        score += 7; reasons.append("delta alici")
    elif delta15 <= ORDERFLOW_DELTA_WEAK:
        score -= 14; reasons.append("delta negatif")
    elif delta15 <= -5:
        score -= 7; reasons.append("delta satici")

    if delta1h >= 8:
        score += 6; reasons.append("1h alici devam")
    elif delta1h <= -8:
        score -= 6; reasons.append("1h satici devam")

    if d.get("oi_long_supported") or d.get("oi_strong_long_supported"):
        score += 6; reasons.append("OI long destekli")
    elif d.get("oi_weak"):
        score -= 5; reasons.append("OI zayif")

    if d.get("liquidity_gap_up"):
        score += 8; reasons.append("yukari likidite boslugu")
    if d.get("liquidity_gap_down"):
        score -= 8; reasons.append("asagi likidite boslugu")

    if ob_score >= 70:
        score += 5; reasons.append("order book alici")
    elif ob_score <= 35:
        score -= 8; reasons.append("order book satici")

    # Likidasyon proxy: gercek likidasyon kumeleri degil; OI + alici akis + yukari bosluk kombinasyonu.
    short_squeeze_proxy = (
        oi15 >= 1.0
        and delta15 >= 6
        and buy_sell_ratio_15m >= 1.15
        and (d.get("liquidity_gap_up") or ob_score >= 60)
    )
    long_squeeze_risk = (
        oi15 >= 1.0
        and delta15 <= -6
        and buy_sell_ratio_15m <= 0.85
        and (d.get("liquidity_gap_down") or ob_score <= 42)
    )

    if short_squeeze_proxy:
        score += 8; reasons.append("short squeeze proxy")
    if long_squeeze_risk:
        score -= 12; reasons.append("long squeeze riski")

    orderflow_block = bool(score <= ORDERFLOW_BLOCK_SCORE or (long_squeeze_risk and ob_score <= 42))
    score = int(max(0, min(100, round(score))))

    if orderflow_block:
        status = "ORDER_FLOW_BLOCK"
    elif score >= 82:
        status = "AGRESIF ALICI"
    elif score >= 65:
        status = "ALICI AVANTAJLI"
    elif score <= 35:
        status = "AGRESIF SATICI"
    elif score <= 45:
        status = "SATICI AVANTAJLI"
    else:
        status = "DENGELI"

    # Likidite boslugu skorunu daha okunabilir ayri goster.
    gap_score = 50
    if d.get("liquidity_gap_up"):
        gap_score += 30
    if d.get("liquidity_gap_down"):
        gap_score -= 30
    if d.get("ask_wall_usdt", 0) > 0 and d.get("ask_wall_distance_pct", 999) <= ORDERBOOK_ASK_WALL_CLOSE_PCT:
        gap_score -= 15
    if d.get("bid_wall_usdt", 0) > 0 and d.get("bid_wall_distance_pct", 999) <= ORDERBOOK_BID_WALL_CLOSE_PCT:
        gap_score += 10
    gap_score = int(max(0, min(100, gap_score)))
    if gap_score >= 75:
        gap_status = "YUKARI BOSLUK"
    elif gap_score <= 35:
        gap_status = "ASAGI BOSLUK RISKI"
    else:
        gap_status = "DENGELI"

    if short_squeeze_proxy:
        liq_status = "SHORT SIKISMA ADAYI"
        liq_score = min(100, score + 8)
    elif long_squeeze_risk:
        liq_status = "LONG SIKISMA RISKI"
        liq_score = max(0, 100 - score)
    else:
        liq_status = "LIKIDASYON NOTR"
        liq_score = 50

    d.update({
        "orderflow_score": score,
        "orderflow_status": status,
        "orderflow_reason": ", ".join(reasons[:6]) if reasons else "DENGELI",
        "buy_sell_ratio_15m": buy_sell_ratio_15m,
        "buy_sell_ratio_1h": buy_sell_ratio_1h,
        "orderflow_block": orderflow_block,
        "liquidity_gap_score": gap_score,
        "liquidity_gap_status": gap_status,
        "liquidation_proxy_score": int(liq_score),
        "liquidation_proxy_status": liq_status,
        "short_squeeze_proxy": bool(short_squeeze_proxy),
        "long_squeeze_risk": bool(long_squeeze_risk),
    })
    return d


def cleanup_cvd_memory():
    now = time.time()
    for symbol in list(cvd_memory.keys()):
        cvd_memory[symbol] = [
            e for e in cvd_memory[symbol]
            if now - e.get("time", 0) <= CVD_MEMORY_EXPIRE_SECONDS
        ]
        if not cvd_memory[symbol]:
            cvd_memory.pop(symbol, None)


def update_cvd_memory(symbol, d):
    """
    V31 CVD HAFIZASI:
    Net delta verisini zaman icinde biriktirir. Aynı 90 sn icinde ayni sembol tekrar yazilmaz.
    Bu gercek tick-by-tick footprint degil; Binance taker flow datasindan uretilen pratik CVD katmanidir.
    """
    if not d:
        return

    now = time.time()
    events = cvd_memory.setdefault(symbol, [])
    if events and now - events[-1].get("time", 0) < CVD_EVENT_DEDUP_SECONDS:
        # En yeni bar icin daha guclu delta gelirse son kaydi guncelle.
        if abs(float(d.get("net_delta_15m", 0) or 0)) > abs(float(events[-1].get("net_delta", 0) or 0)):
            events[-1].update({
                "time": now,
                "price": float(d.get("entry", d.get("price", 0)) or 0),
                "net_delta": float(d.get("net_delta_15m", 0) or 0),
                "delta_ratio": float(d.get("delta_ratio_15m", 0) or 0),
                "long_flow": float(d.get("long_flow_15m", 0) or 0),
                "short_flow": float(d.get("short_flow_15m", 0) or 0),
            })
        cleanup_cvd_memory()
        return

    events.append({
        "time": now,
        "price": float(d.get("entry", d.get("price", 0)) or 0),
        "net_delta": float(d.get("net_delta_15m", 0) or 0),
        "delta_ratio": float(d.get("delta_ratio_15m", 0) or 0),
        "long_flow": float(d.get("long_flow_15m", 0) or 0),
        "short_flow": float(d.get("short_flow_15m", 0) or 0),
    })
    cleanup_cvd_memory()


def cvd_context(symbol, current_price=0):
    cleanup_cvd_memory()
    events = cvd_memory.get(symbol, [])
    now = time.time()
    out = {
        "cvd_ok": False,
        "cvd_score": 50,
        "cvd_status": "CVD VERI YOK",
        "cvd_trend": "YOK",
        "cvd_30m": 0.0,
        "cvd_60m": 0.0,
        "cvd_120m": 0.0,
        "cvd_delta_ratio_avg": 0.0,
        "cvd_price_change_pct": 0.0,
        "cvd_hidden_accumulation": False,
        "cvd_fake_pump": False,
        "cvd_distribution_risk": False,
        "cvd_block": False,
        "cvd_reason": "VERI YOK",
    }
    if not events:
        return out

    e30 = [e for e in events if now - e.get("time", 0) <= 30 * 60]
    e60 = [e for e in events if now - e.get("time", 0) <= 60 * 60]
    e120 = [e for e in events if now - e.get("time", 0) <= 120 * 60]
    ref = e60 if e60 else e120
    if not ref:
        return out

    cvd30 = sum(e.get("net_delta", 0) for e in e30)
    cvd60 = sum(e.get("net_delta", 0) for e in e60)
    cvd120 = sum(e.get("net_delta", 0) for e in e120)
    long60 = sum(e.get("long_flow", 0) for e in e60)
    short60 = sum(e.get("short_flow", 0) for e in e60)
    total60 = long60 + short60
    avg_delta_ratio = (cvd60 / total60 * 100) if total60 > 0 else 0.0

    first_price = float(ref[0].get("price", 0) or 0)
    last_price = float(current_price or ref[-1].get("price", first_price) or 0)
    price_change = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0.0

    score = 50
    reasons = []
    if avg_delta_ratio >= 18:
        score += 24; reasons.append("cvd cok guclu")
    elif avg_delta_ratio >= 10:
        score += 16; reasons.append("cvd guclu")
    elif avg_delta_ratio >= 4:
        score += 8; reasons.append("cvd pozitif")
    elif avg_delta_ratio <= -18:
        score -= 24; reasons.append("cvd cok negatif")
    elif avg_delta_ratio <= -10:
        score -= 16; reasons.append("cvd negatif")
    elif avg_delta_ratio <= -4:
        score -= 8; reasons.append("cvd zayif")

    # Kisa/orta vade ayni yone akiyorsa guven artar.
    if cvd30 > 0 and cvd60 > 0:
        score += 7; reasons.append("30/60dk alici birikimi")
    elif cvd30 < 0 and cvd60 < 0:
        score -= 7; reasons.append("30/60dk satici birikimi")

    hidden_accumulation = bool(abs(price_change) <= 1.5 and avg_delta_ratio >= 8 and cvd60 > 0)
    fake_pump = bool(price_change >= 2.5 and avg_delta_ratio <= -4 and cvd60 < 0)
    distribution_risk = bool(price_change >= 1.0 and avg_delta_ratio <= -8)

    if hidden_accumulation:
        score += 10; reasons.append("gizli toplama")
    if fake_pump:
        score -= CVD_DIVERGENCE_PENALTY; reasons.append("sahte yukselis riski")
    if distribution_risk:
        score -= 10; reasons.append("dagitim riski")

    score = int(max(0, min(100, round(score))))
    cvd_block = bool(score <= CVD_BLOCK_SCORE or fake_pump)

    if cvd_block:
        status = "CVD_BLOCK"
    elif score >= 82:
        status = "CVD COK GUCLU"
    elif score >= 65:
        status = "CVD POZITIF"
    elif score <= 35:
        status = "CVD NEGATIF"
    elif score <= 45:
        status = "CVD ZAYIF"
    else:
        status = "CVD NOTR"

    if cvd60 > 0 and cvd30 >= 0:
        trend = "YUKARI"
    elif cvd60 < 0 and cvd30 <= 0:
        trend = "ASAGI"
    else:
        trend = "KARISIK"

    out.update({
        "cvd_ok": True,
        "cvd_score": score,
        "cvd_status": status,
        "cvd_trend": trend,
        "cvd_30m": cvd30,
        "cvd_60m": cvd60,
        "cvd_120m": cvd120,
        "cvd_delta_ratio_avg": avg_delta_ratio,
        "cvd_price_change_pct": price_change,
        "cvd_hidden_accumulation": hidden_accumulation,
        "cvd_fake_pump": fake_pump,
        "cvd_distribution_risk": distribution_risk,
        "cvd_block": cvd_block,
        "cvd_reason": ", ".join(reasons[:5]) if reasons else "NOTR",
    })
    return out


def attach_cvd_context(symbol, d):
    if not d:
        return d
    update_cvd_memory(symbol, d)
    price = float(d.get("entry", d.get("price", 0)) or 0)
    d.update(cvd_context(symbol, price))
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

            if qv < BINANCE_UNIVERSE_MIN_QV:
                continue

            if volatility < BINANCE_UNIVERSE_MIN_VOLATILITY:
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


def binance_elite_confidence_package(d, support_modules=None):
    """V36: Elite Guven Skoru. Radar agirligi, radar sirasi, OrderFlow ve CVD birlikte degerlendirilir."""
    support_modules = support_modules or []
    if not d:
        return {"score": 0, "label": "YOK", "reasons": "VERI YOK"}
    module = d.get("module", "UNKNOWN")
    history_modules = list(d.get("history_modules", []) or [])
    modules = []
    for m in history_modules + [module] + list(support_modules):
        if m and m not in modules:
            modules.append(m)
    s = set(modules)
    weights = {
        "SAFE": 15, "FAST_LIQUIDITY_SWEEP": 15, "SWEEP": 13, "PRE_ROCKET_SQUEEZE": 14,
        "MONEY_ACCEL": 12, "MONEY": 10, "DIP": 9, "TREND_BUILDUP": 8, "HISTORY_BUILDUP": 7,
        "EARLY": 5, "MOMENTUM": 1,
    }
    score = 25 + min(35, sum(weights.get(x, 0) for x in modules))
    reasons = []
    if {"EARLY", "MONEY_ACCEL"}.issubset(s) or {"EARLY", "MONEY"}.issubset(s):
        score += 8; reasons.append("erken+para")
    if ("SAFE" in s or "SWEEP" in s or "FAST_LIQUIDITY_SWEEP" in s) and ("MONEY_ACCEL" in s or "MONEY" in s):
        score += 10; reasons.append("giris+para destekli")
    if {"TREND_BUILDUP", "MONEY_ACCEL"}.issubset(s) or {"TREND_BUILDUP", "MONEY"}.issubset(s):
        score += 7; reasons.append("trend+para")
    if module in ("MOMENTUM", "HISTORY_BUILDUP", "TREND_BUILDUP") and len(s) <= 2:
        score -= 12; reasons.append("gec/tek radar")

    of_score = int(d.get("orderflow_score", 50) or 50)
    cvd_score = int(d.get("cvd_score", 50) or 50)
    htf_score = int(d.get("htf_trend_score", 50) or 50)
    align_penalty = int(d.get("alignment_penalty", 0) or 0)
    pullback_penalty = int(d.get("live_pullback_penalty", 0) or 0)
    resistance = float(d.get("resistance_distance_pct", 999) or 999)

    if of_score >= ORDERFLOW_STRONG_SCORE:
        score += 8; reasons.append("orderflow guclu")
    elif of_score <= ORDERFLOW_WEAK_SCORE:
        score -= 10; reasons.append("orderflow zayif")
    if cvd_score >= CVD_STRONG_SCORE:
        score += 8; reasons.append("CVD guclu")
    elif cvd_score <= CVD_WEAK_SCORE or d.get("cvd_fake_pump") or d.get("cvd_distribution_risk"):
        score -= 10; reasons.append("CVD risk")
    if htf_score >= 70:
        score += 5
    elif htf_score < HTF_TREND_MIN_FOR_ELITE and module not in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        score -= 8; reasons.append("HTF zayif")
    if align_penalty >= ALIGNMENT_WEAK_PENALTY:
        score -= 10; reasons.append("grafik uyum zayif")
    if pullback_penalty >= PULLBACK_TOTAL_BLOCK_SCORE:
        score -= 10; reasons.append("canli satis baskisi")
    if d.get("long_squeeze_risk") or d.get("orderflow_block") or d.get("cvd_block"):
        score -= 12; reasons.append("akis blok riski")
    if 0 <= resistance <= HARD_RESISTANCE_BLOCK_PCT and not d.get("resistance_broken") and not d.get("short_squeeze_proxy"):
        score -= 10; reasons.append("direnc cok yakin")

    score = int(max(0, min(100, round(score))))
    if score >= 82:
        label = "COK GUCLU"
    elif score >= BINANCE_ELITE_CONFIDENCE_BONUS_SCORE:
        label = "GUCLU"
    elif score >= BINANCE_ELITE_CONFIDENCE_WARN_SCORE:
        label = "ORTA"
    elif score >= BINANCE_ELITE_CONFIDENCE_BLOCK_SCORE:
        label = "ZAYIF"
    else:
        label = "BLOCK"
    return {"score": score, "label": label, "reasons": ", ".join(reasons[:4]) if reasons else "DENGELI"}


def attach_binance_elite_confidence(best, support_modules=None):
    pkg = binance_elite_confidence_package(best, support_modules)
    best["elite_confidence_score"] = pkg["score"]
    best["elite_confidence_label"] = pkg["label"]
    best["elite_confidence_reason"] = pkg["reasons"]
    return best


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
                    "higher_low_count": max(e.get("higher_low_count", 0), d.get("higher_low_count", 0)),
                    "higher_high_count": max(e.get("higher_high_count", 0), d.get("higher_high_count", 0)),
                    "obv_up": bool(e.get("obv_up") or d.get("obv_up")),
                    "macd_turn": bool(e.get("macd_turn") or d.get("macd_turn")),
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
            "higher_low_count": d.get("higher_low_count", 0),
            "higher_high_count": d.get("higher_high_count", 0),
            "obv_up": bool(d.get("obv_up")),
            "macd_turn": bool(d.get("macd_turn")),
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
            "trend_signal_count_60m": 0,
            "trend_signal_count_120m": 0,
            "trend_signal_gain": 0,
            "trend_continuation_score": 0,
            "trend_continuation_bonus": 0,
            "trend_continuation_ok": False,
            "trend_continuation_text": "YOK",
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

    trend60 = [e for e in e60 if e.get("module") == "TREND_BUILDUP"]
    trend120 = [e for e in e120 if e.get("module") == "TREND_BUILDUP"]
    trend_first = next((e.get("price", 0) for e in trend120 if e.get("price", 0) > 0), 0)
    trend_last = next((e.get("price", 0) for e in reversed(trend120) if e.get("price", 0) > 0), trend_first)
    trend_gain = ((trend_last - trend_first) / trend_first * 100) if trend_first > 0 else 0
    trend_score = 0
    if len(trend60) >= TREND_CONT_MIN_REPEAT_60M:
        trend_score += 24
    if len(trend120) >= TREND_CONT_MIN_REPEAT_120M:
        trend_score += 24
    if 1.0 <= trend_gain <= TREND_CONT_MAX_GAIN:
        trend_score += 12
    elif trend_gain > TREND_CONT_MAX_GAIN:
        trend_score -= 12
    trend_score += min(max((max([e.get("higher_low_count", 0) for e in trend120] or [0]) - 2) * 4, 0), 12)
    trend_score += min(max((max([e.get("higher_high_count", 0) for e in trend120] or [0]) - 1) * 4, 0), 12)
    if any(e.get("obv_up") for e in trend120):
        trend_score += 6
    if any(e.get("macd_turn") for e in trend120):
        trend_score += 6
    trend_score = int(max(0, min(100, trend_score)))
    trend_bonus = TREND_CONT_BONUS_STRONG if trend_score >= 70 else (TREND_CONT_BONUS_MID if trend_score >= TREND_CONT_MIN_SCORE else 0)
    trend_ok = bool(len(trend60) >= TREND_CONT_MIN_REPEAT_60M and trend_score >= TREND_CONT_MIN_SCORE)
    trend_text = f"Trend tekrar {len(trend60)}/60dk {len(trend120)}/120dk | Guven {trend_score}/100 | Gain %{trend_gain:.2f}"

    return {
        "main_signal_count_60m": len(e60),
        "main_signal_count_120m": len(e120),
        "main_signal_modules": modules,
        "main_signal_text": ", ".join(modules),
        "main_signal_first_price": first_price,
        "main_signal_gain": gain,
        "main_signal_bonus": bonus,
        "trend_signal_count_60m": len(trend60),
        "trend_signal_count_120m": len(trend120),
        "trend_signal_gain": trend_gain,
        "trend_continuation_score": trend_score,
        "trend_continuation_bonus": trend_bonus,
        "trend_continuation_ok": trend_ok,
        "trend_continuation_text": trend_text,
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



def pre_breakout_watch_signal(symbol, rs):
    """
    V44 PRE BREAKOUT WATCH / ERKEN KIRILIM:
    NFP tipi dipten toparlanip henuz dikey mum gelmeden, BB orta bant/EMA geri alinirken
    OBV-MACD-hacim uyanisini yakalar. AL degildir; ana kanal erken takip mesajidir.
    """
    df15 = fetch_df(symbol, "15m", 140)
    df1h = fetch_df(symbol, "1h", 100)
    if df15 is None or df1h is None or len(df15) < 60:
        return False, None

    m15 = df15.iloc[-1]
    p15 = df15.iloc[-2]
    h1 = df1h.iloc[-1]
    h1_prev = df1h.iloc[-2]
    price = float(m15.close)

    low_24h = df15["low"].tail(96).min()
    high_24h = df15["high"].tail(96).max()
    dist_from_low = ((price - low_24h) / low_24h * 100) if low_24h > 0 else 999
    pullback_from_high = ((high_24h - price) / high_24h * 100) if high_24h > 0 else 999

    gains = recent_price_gains(df15, price)
    price_gain_15m = gains.get("price_gain_15m", 0)
    price_gain_30m = gains.get("price_gain_30m", 0)

    vol_ratio_15m = (m15.volume / m15.vol_avg) if m15.vol_avg > 0 else 0
    last4_vol = df15["volume"].tail(4).mean()
    prev12_vol = df15["volume"].iloc[-16:-4].mean()
    vol_ratio = (last4_vol / prev12_vol) if prev12_vol > 0 else vol_ratio_15m
    usdt_vol = df15["volume"].tail(4).sum() * price
    avg_usdt = df15["vol_avg"].tail(4).sum() * price if df15["vol_avg"].tail(4).sum() > 0 else 0
    money_impact = (usdt_vol / avg_usdt) if avg_usdt > 0 else 0
    volume_power = money_impact * max(vol_ratio, vol_ratio_15m)

    ema_reclaim = (m15.close > m15.ema21 and p15.close <= p15.ema21) or (m15.close > m15.ema9 and m15.ema9 >= m15.ema21 * 0.985)
    bb_mid_reclaim = m15.close > m15.bb_middle and p15.close <= p15.bb_middle
    macd_improving = m15.macd > df15["macd"].iloc[-4] or h1.macd > h1_prev.macd
    macd_cross_near = m15.macd > m15.macd_signal or abs(m15.macd - m15.macd_signal) <= max(abs(m15.macd), 1e-12) * 0.60
    obv_turn = df15["obv"].iloc[-1] > df15["obv"].iloc[-8]
    bb_ready = m15.bb_width <= df15["bb_width"].tail(40).quantile(0.70) or m15.bb_width < 0.11
    green_body = m15.close > m15.open and m15.body_ratio >= 0.38

    # Geç kalmış pump'u değil, erken kırılımı yakala.
    if not (42 <= m15.rsi <= 70):
        return False, None
    if price_gain_15m > 6.0 or price_gain_30m > 10.5:
        return False, None
    if dist_from_low > 24 or pullback_from_high < 1.0:
        return False, None

    score = 0
    reasons = []
    if rs >= 70:
        score += 2; reasons.append("RS guclu")
    if ema_reclaim:
        score += 3; reasons.append("EMA geri aliniyor")
    if bb_mid_reclaim:
        score += 3; reasons.append("BB orta bant geri alindi")
    if macd_improving:
        score += 2; reasons.append("MACD erken toparlaniyor")
    if macd_cross_near:
        score += 1; reasons.append("MACD kesisime yakin")
    if obv_turn:
        score += 2; reasons.append("OBV donus basladi")
    if vol_ratio >= 1.15 or vol_ratio_15m >= 1.20:
        score += 2; reasons.append("Hacim uyanmaya basladi")
    if money_impact >= 1.10:
        score += 2; reasons.append("Para etkisi erken pozitif")
    if bb_ready:
        score += 1; reasons.append("Bollinger henuz cok genislememis")
    if green_body:
        score += 1; reasons.append("Yesil kirilim mumu")
    if 2 <= dist_from_low <= 18:
        score += 1; reasons.append("Dipten kopus erken bolge")

    valid = score >= 10 and (ema_reclaim or bb_mid_reclaim) and macd_improving and (obv_turn or money_impact >= 1.20 or vol_ratio >= 1.35)
    if not valid:
        return False, None

    return True, {
        "module": "PRE_BREAKOUT_WATCH",
        "priority": 27,
        "score": score,
        "rs": rs,
        "price": price,
        "vol_ratio": max(vol_ratio, vol_ratio_15m),
        "usdt_vol": usdt_vol,
        "money_impact": money_impact,
        "volume_power": volume_power,
        "rsi": m15.rsi,
        "dist_from_low": dist_from_low,
        "pullback_from_high": pullback_from_high,
        "price_gain_15m": price_gain_15m,
        "price_gain_30m": price_gain_30m,
        "ema_reclaim": ema_reclaim,
        "bb_mid_reclaim": bb_mid_reclaim,
        "macd_turn": macd_improving,
        "macd_cross_near": macd_cross_near,
        "obv_up": obv_turn,
        "bb_width": m15.bb_width,
        "bb_ready": bb_ready,
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
        score >= 12
        and rs >= MIN_EARLY_RS
        and (vol_ratio_1h >= 1.20 or vol_ratio_15m >= 1.25)
        and (usdt_vol_1h >= 20000 or usdt_vol_15m >= 9000)
        and money_impact >= 1.35
        and (
            obv_up_1h
            or obv_up_15m
            or macd_turn_1h
            or macd_turn_15m
            or bb_expanding
        )
        and 40 <= h1.rsi <= 80
        and dist_from_low <= 16
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
        confidence >= MIN_SAFE_CONFIDENCE
        and not fomo_block
        and vol_ratio >= 1.45
        and usdt_vol >= 25000
        and money_impact >= 1.20
        and volume_power >= 2.10
        and change_3m >= 0.05
        and (trend_new or trend_up)
        and (macd_turn or macd_bull or obv_up)
        and 43 <= t15.rsi <= 74
        and dist_from_low <= 22
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
        score >= 9
        and vol_ratio >= 1.35
        and usdt_vol >= 50000
        and h1.lower_wick >= 0.45
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
            or money_impact >= 1.10
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
        score >= 9
        and sweep
        and lower_wick >= 0.40
        and recovery >= 0.55
        and vol_ratio >= 1.30
        and usdt_vol >= 30000
        and money_impact >= 1.10
        and 28 <= m15.rsi <= 62
        and dist_from_low <= 10
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
        score >= 15
        and dist_from_low <= 14
        and recovery >= 0.50
        and lower_wick >= 0.22
        and vol_ratio >= 1.10
        and money_impact >= 1.00
        and volume_power >= 1.15
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
        score >= 21
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
        cont_score >= 6
        and 0.4 <= price_gain <= 5.5
        and money_now >= 1.30
        and power_now >= 2.20
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
        mom_score >= 7
        and price_gain >= 1.20
        and money_now >= 1.40
        and power_now >= 2.60
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
{float(d.get('vol_ratio_1h', 0) or 0):.2f}x

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
{float(d.get('vol_ratio_1h', 0) or 0):.2f}x

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
Trend Devam Guveni: {d.get('trend_continuation_score', 0)}/100
Ana Trend Tekrar: {d.get('trend_signal_count_60m', 0)}x/60dk | {d.get('trend_signal_count_120m', 0)}x/120dk
Trend Bonus: {d.get('trend_continuation_bonus', 0)}
"""
        decision = "15m alt Bollinger igne + bant icine donus. Direkt long degil; 5m/15m retest takip."

    elif module == "PRE_BREAKOUT_WATCH":
        title = "PRE BREAKOUT WATCH"
        body = f"""
15m Degisim: %{d.get('price_gain_15m', 0):.2f}
30m Degisim: %{d.get('price_gain_30m', 0):.2f}
24s Dip Mesafesi: %{d.get('dist_from_low', 0):.2f}
Tepeden Uzaklik: %{d.get('pullback_from_high', 0):.2f}
EMA Reclaim: {"VAR" if d.get("ema_reclaim") else "YOK"}
BB Orta Bant Reclaim: {"VAR" if d.get("bb_mid_reclaim") else "YOK"}
MACD Erken Donus: {"VAR" if d.get("macd_turn") else "YOK"}
OBV Donus: {"VAR" if d.get("obv_up") else "YOK"}
BB Width: {d.get('bb_width', 0):.4f}
"""
        decision = "Erken kirilim radari. AL degildir; momentum patlamadan once takip icin atilir."

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
1H Hacim Artisi: {float(d.get('vol_ratio_1h', 0) or 0):.2f}x
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
sent_elite_prep = {}

ELITE_MIN_SCORE = 88
ELITE_PREP_MIN_SCORE = 68
ELITE_PREP_MAX_SCORE = 100
ELITE_PREP_MIN_WALK = 60
ELITE_PREP_MIN_ORDERFLOW = 40
ELITE_PREP_MIN_TREND = 45

# V35 HAZIRLIK GEVSETME:
# Ana kanalda ayni coin israrla geliyorsa bu AL degil ama hazirlik kanalina dusmelidir.
# 1000RATS tipi: 1 saatte 3+ tekrar, para/hacim gucu var ama Elite kapisi henuz tamam degil.
ELITE_PREP_REPEAT_60M = 3
ELITE_PREP_REPEAT_120M = 5
ELITE_PREP_REPEAT_MIN_MONEY = 1.60
ELITE_PREP_REPEAT_MIN_POWER = 3.50
ELITE_PREP_REPEAT_MAX_RSI = 78

ELITE_PREP_COOLDOWN = 45 * 60
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


def near_resistance_late_memory_block(d):
    """
    V24 KAT FIX:
    Direnç çok yakınken hafıza/re-entry/second wave yüzünden geç AL gelmesini engeller.
    Güçlü para olsa bile, fiyat direnç altında ve geçmiş radar çok tekrarlıysa Elite yerine izleme kalsın.
    """
    if not d or not d.get("sr_ok"):
        return False, "OK"
    if d.get("resistance_broken"):
        return False, "OK"

    module = d.get("module", "UNKNOWN")
    resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
    main_count = int(d.get("main_signal_count_120m", 0) or 0)
    memory_like = bool(
        d.get("memory_reentry")
        or d.get("second_wave_bonus")
        or d.get("main_repeat_buildup")
        or d.get("money_memory_bonus")
        or d.get("repeat_force")
        or d.get("history_force")
        or module == "HISTORY_BUILDUP"
    )

    # Dip/sweep sinyallerinde ana fikir likidite süpürme olduğu için bu blok daha esnek kalır.
    if module in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        return False, "OK"

    # Direnç neredeyse sıfır mesafedeyse AL verme; kırılımı bekle.
    if 0 <= resistance_distance <= SR_HARD_BLOCK_PCT:
        return True, "DIRENC_COK_YAKIN_KIRILIM_BEKLE"

    # Hafıza/re-entry ile gelen ve çok tekrar etmiş coin direnç altındaysa geç kalmış olabilir.
    if (
        memory_like
        and 0 <= resistance_distance <= SR_MEMORY_LATE_BLOCK_PCT
        and main_count >= SR_MEMORY_REPEAT_BLOCK_COUNT
    ):
        return True, "DIRENC_ALTINDA_GEC_MEMORY_REENTRY"

    return False, "OK"

def attach_live_pullback_context(symbol, d):
    """
    V25 CANLI PULLBACK KONTROLU:
    Son 15m mumlarda satis basladi mi? MACD histogram zayifliyor mu?
    OBV dusuyor mu? Fiyat tepe sonrasinda geri cekiliyor mu?
    Bu bilgiler Elite kapisinda ve Yurume Skorunda kullanilir.
    """
    if not d:
        return d
    try:
        df15 = fetch_df(symbol, "15m", 120)
        if df15 is None or len(df15) < 8:
            d["live_pullback_status"] = "VERI YOK"
            d["live_pullback_penalty"] = 0
            d["live_pullback_block"] = False
            return d

        last = df15.iloc[-1]
        prev = df15.iloc[-2]
        prev2 = df15.iloc[-3]
        price = float(d.get("price", last.close) or last.close)

        red_candle = bool(last.close < last.open)
        close_down = bool(last.close < prev.close)
        prev_red = bool(prev.close < prev.open)
        two_red = bool(red_candle and prev_red)

        macd_hist_now = float(last.macd - last.macd_signal)
        macd_hist_prev = float(prev.macd - prev.macd_signal)
        macd_hist_prev2 = float(prev2.macd - prev2.macd_signal)
        macd_weakening = bool(macd_hist_now < macd_hist_prev)
        macd_weakening_2 = bool(macd_hist_now < macd_hist_prev < macd_hist_prev2)

        obv_falling = bool(float(last.obv) < float(prev.obv))
        rsi_drop = float(prev.rsi - last.rsi)
        rsi_fast_drop = bool(rsi_drop >= 4.0)
        ema9_lost = bool(price < float(last.ema9))

        high_24h = float(df15["high"].tail(96).max())
        pullback_from_high = ((high_24h - price) / high_24h * 100) if high_24h > 0 else 0.0

        resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
        module = d.get("module", "UNKNOWN")
        dip_like = module in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP")

        penalty = 0
        reasons = []
        if close_down or red_candle:
            penalty += PULLBACK_RED_CANDLE_PENALTY
            reasons.append("son mum kirmizi/zayif")
        if two_red:
            penalty += PULLBACK_TWO_RED_PENALTY
            reasons.append("iki kirmizi mum")
        if macd_weakening:
            penalty += PULLBACK_MACD_WEAK_PENALTY
            reasons.append("MACD hist zayifliyor")
        if macd_weakening_2:
            penalty += 6
            reasons.append("MACD 2 mumdur zayif")
        if obv_falling:
            penalty += PULLBACK_OBV_FALL_PENALTY
            reasons.append("OBV dusuyor")
        if rsi_fast_drop:
            penalty += PULLBACK_RSI_DROP_PENALTY
            reasons.append("RSI hizli dusuyor")
        if ema9_lost:
            penalty += PULLBACK_EMA9_LOST_PENALTY
            reasons.append("EMA9 alti")
        if pullback_from_high >= PULLBACK_FROM_HIGH_WARN:
            penalty += 10
            reasons.append("tepeden geri cekilme")

        # Blok kurallari: dip/sweep haric, satis basladiysa hafiza tek basina AL verdirmesin.
        hard_block = False
        if not dip_like:
            if two_red and macd_weakening and obv_falling:
                hard_block = True
            if pullback_from_high >= PULLBACK_FROM_HIGH_BLOCK and (close_down or red_candle) and (macd_weakening or obv_falling):
                hard_block = True
            if 0 <= resistance_distance <= 1.20 and (close_down or red_candle) and (macd_weakening or obv_falling):
                hard_block = True
            if penalty >= PULLBACK_TOTAL_BLOCK_SCORE and (close_down or red_candle):
                hard_block = True

        if hard_block:
            status = "SATIS_BASKISI_BLOCK"
        elif penalty >= 22:
            status = "SATIS_BASKISI_YUKSEK"
        elif penalty >= 10:
            status = "SATIS_BASKISI_VAR"
        else:
            status = "OK"

        d.update({
            "live_red_candle": bool(red_candle),
            "live_close_down": bool(close_down),
            "live_two_red": bool(two_red),
            "live_macd_weakening": bool(macd_weakening),
            "live_macd_weakening_2": bool(macd_weakening_2),
            "live_obv_falling": bool(obv_falling),
            "live_rsi_drop": rsi_drop,
            "live_rsi_fast_drop": bool(rsi_fast_drop),
            "live_ema9_lost": bool(ema9_lost),
            "live_pullback_from_high": pullback_from_high,
            "live_pullback_penalty": int(penalty),
            "live_pullback_block": bool(hard_block),
            "live_pullback_status": status,
            "live_pullback_reasons": ", ".join(reasons[:5]) if reasons else "OK",
        })
        return d
    except Exception as e:
        print("Live pullback context hata:", symbol, e, flush=True)
        d["live_pullback_status"] = "VERI HATA"
        d["live_pullback_penalty"] = 0
        d["live_pullback_block"] = False
        return d

def attach_graph_technical_alignment(symbol, d):
    """
    V26 GRAFIK-TEKNIK UYUM KONTROLU:
    Teknik skor/hafiza guclu olsa bile 15m grafik son anda bozuluyorsa Elite AL'i keser.
    Grafik tarafi: mum yonu, EMA, OBV, MACD histogram, tepeden geri cekilme, yakin direnc.
    Teknik tarafi: para etkisi, hacim gucu, market etki, memory/re-entry, OI/Delta.
    """
    if not d:
        return d
    try:
        df15 = fetch_df(symbol, "15m", 140)
        df1h = fetch_df(symbol, "1h", 90)
        if df15 is None or len(df15) < 8:
            d.update({
                "alignment_status": "VERI YOK",
                "alignment_penalty": 0,
                "alignment_block": False,
                "alignment_score": 50,
                "alignment_reasons": "VERI YOK",
            })
            return d

        last = df15.iloc[-1]
        prev = df15.iloc[-2]
        prev2 = df15.iloc[-3]
        price = float(d.get("price", last.close) or last.close)

        # Grafik negatifleri
        red_candle = bool(last.close < last.open)
        close_down = bool(last.close < prev.close)
        two_red = bool(red_candle and prev.close < prev.open)
        ema9_lost = bool(price < float(last.ema9))
        ema21_lost = bool(price < float(last.ema21))
        macd_hist_now = float(last.macd - last.macd_signal)
        macd_hist_prev = float(prev.macd - prev.macd_signal)
        macd_hist_prev2 = float(prev2.macd - prev2.macd_signal)
        macd_weak = bool(macd_hist_now < macd_hist_prev)
        macd_weak_2 = bool(macd_hist_now < macd_hist_prev < macd_hist_prev2)
        obv_down = bool(float(last.obv) < float(prev.obv))
        rsi_drop = float(prev.rsi - last.rsi)
        rsi_fast_drop = bool(rsi_drop >= 4.0)
        high_24h = float(df15["high"].tail(96).max())
        pullback_from_high = ((high_24h - price) / high_24h * 100) if high_24h > 0 else 0.0
        resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)

        graph_bad = 0
        reasons = []
        if close_down or red_candle:
            graph_bad += 1; reasons.append("son mum zayif")
        if two_red:
            graph_bad += 2; reasons.append("iki kirmizi mum")
        if macd_weak:
            graph_bad += 1; reasons.append("MACD hist zayif")
        if macd_weak_2:
            graph_bad += 1; reasons.append("MACD 2 mum zayif")
        if obv_down:
            graph_bad += 1; reasons.append("OBV dusuyor")
        if rsi_fast_drop:
            graph_bad += 1; reasons.append("RSI hizli dusuyor")
        if ema9_lost:
            graph_bad += 1; reasons.append("EMA9 alti")
        if ema21_lost:
            graph_bad += 2; reasons.append("EMA21 alti")
        if pullback_from_high >= 4.0:
            graph_bad += 1; reasons.append("tepeden donus")
        if 0 <= resistance_distance <= 1.0:
            graph_bad += 1; reasons.append("direnc yakin")

        # Teknik pozitifleri
        money = max(float(d.get("money_impact", 0) or 0), float(d.get("effective_money_impact", 0) or 0), float(d.get("history_money_max", 0) or 0))
        power = max(float(d.get("volume_power", 0) or 0), float(d.get("effective_volume_power", 0) or 0), float(d.get("history_power_max", 0) or 0))
        market = max(float(d.get("market_impact_pct", 0) or 0), float(d.get("effective_market_impact_pct", 0) or 0), float(d.get("history_market_max", 0) or 0), float(d.get("money_market_60m", 0) or 0))
        tech_good = 0
        if money >= 2.5: tech_good += 1
        if power >= 8: tech_good += 1
        if market >= 0.35: tech_good += 1
        if d.get("memory_reentry") or d.get("second_wave_bonus") or d.get("money_memory_bonus"): tech_good += 1
        if d.get("oi_long_supported") or d.get("oi_strong_long_supported"): tech_good += 1
        if d.get("buyer_dominant") or d.get("strong_buyer_dominant"): tech_good += 1

        # Uyum skoru: 50 baz; teknik artirir, grafik bozulma dusurur.
        alignment_score = 50 + tech_good * 7 - graph_bad * 10
        alignment_score = int(max(0, min(100, alignment_score)))

        penalty = 0
        block = False
        status = "POZITIF"
        if graph_bad >= 6 and tech_good >= 2:
            penalty = ALIGNMENT_BLOCK_PENALTY; block = True; status = "UYUMSUZ_BLOCK"
        elif graph_bad >= 4 and (close_down or red_candle) and (macd_weak or obv_down):
            penalty = ALIGNMENT_WEAK_PENALTY; status = "UYUMSUZ"
        elif graph_bad >= 2:
            penalty = ALIGNMENT_WARN_PENALTY; status = "NOTR/ZAYIF"

        # Direnc cok yakin + grafik zayifsa daha sert davran.
        if 0 <= resistance_distance <= 1.0 and (close_down or red_candle) and (macd_weak or obv_down):
            penalty += 12
            status = "DIRENC_ALTI_UYUMSUZ"
            if graph_bad >= 4:
                block = True

        d.update({
            "alignment_status": status,
            "alignment_penalty": int(penalty),
            "alignment_block": bool(block),
            "alignment_score": alignment_score,
            "alignment_graph_bad": int(graph_bad),
            "alignment_tech_good": int(tech_good),
            "alignment_reasons": ", ".join(reasons[:6]) if reasons else "OK",
        })
        return d
    except Exception as e:
        print("Graph technical alignment hata:", symbol, e, flush=True)
        d.update({
            "alignment_status": "HATA/ES GEC",
            "alignment_penalty": 0,
            "alignment_block": False,
            "alignment_score": 50,
            "alignment_reasons": "HATA",
        })
        return d


def attach_higher_timeframe_trend_context(symbol, d):
    """
    V30 SAATLIK / 4S TREND + YUKSELIS YORGUNLUGU:
    15m sinyal guclu olsa bile 1H/4H yapi zayifsa veya coin 6 saatte cok gidip
    tepeden donmeye basladiysa Elite kapisini zorlastirir.
    """
    if not d:
        return d
    try:
        df15 = fetch_df(symbol, "15m", 160)
        df1h = fetch_df(symbol, "1h", 120)
        df4h = fetch_df(symbol, "4h", 80)
        if df15 is None or df1h is None or len(df15) < 30 or len(df1h) < 20:
            d.update({
                "htf_trend_score": 50,
                "htf_trend_status": "HTF VERI YOK",
                "htf_trend_reason": "VERI YOK",
                "fatigue_block": False,
                "fatigue_penalty": 0,
            })
            return d

        m15 = df15.iloc[-1]
        h1 = df1h.iloc[-1]
        h1p = df1h.iloc[-2]
        score = 50
        reasons = []

        if h1.close > h1.ema21:
            score += 12; reasons.append("1H EMA21 ustu")
        else:
            score -= 12; reasons.append("1H EMA21 alti")
        if h1.ema9 >= h1.ema21:
            score += 8; reasons.append("1H EMA pozitif")
        else:
            score -= 6; reasons.append("1H EMA zayif")
        if h1.macd > h1.macd_signal and h1.macd >= h1p.macd:
            score += 10; reasons.append("1H MACD guclu")
        elif h1.macd < h1.macd_signal:
            score -= 8; reasons.append("1H MACD zayif")
        if 45 <= float(h1.rsi) <= 68:
            score += 6; reasons.append("1H RSI saglikli")
        elif float(h1.rsi) >= 74:
            score -= 10; reasons.append("1H RSI sisik")

        if df4h is not None and len(df4h) >= 20:
            h4 = df4h.iloc[-1]
            h4p = df4h.iloc[-2]
            if h4.close > h4.ema21:
                score += 8; reasons.append("4H EMA21 ustu")
            else:
                score -= 6; reasons.append("4H EMA21 alti")
            if h4.macd >= h4p.macd:
                score += 5; reasons.append("4H MACD toparliyor")
            else:
                score -= 4; reasons.append("4H MACD zayif")

        price = float(m15.close)
        p6h = float(df15["close"].iloc[-25]) if len(df15) >= 25 else float(df15["close"].iloc[0])
        high_6h = float(df15["high"].tail(24).max())
        gain_6h = ((price - p6h) / p6h * 100) if p6h > 0 else 0.0
        pullback_from_6h_high = ((high_6h - price) / high_6h * 100) if high_6h > 0 else 0.0
        last_red = bool(df15["close"].iloc[-1] < df15["open"].iloc[-1])
        prev_red = bool(df15["close"].iloc[-2] < df15["open"].iloc[-2])
        macd_hist_now = float(df15["macd"].iloc[-1] - df15["macd_signal"].iloc[-1])
        macd_hist_prev = float(df15["macd"].iloc[-2] - df15["macd_signal"].iloc[-2])
        hist_weak = macd_hist_now < macd_hist_prev

        fatigue_penalty = 0
        fatigue_block = False
        if gain_6h >= FATIGUE_6H_GAIN_WARN and (pullback_from_6h_high >= FATIGUE_PULLBACK_MIN or (last_red and hist_weak)):
            fatigue_penalty += FATIGUE_PENALTY
            reasons.append("6s yukselis yorgun")
        if gain_6h >= FATIGUE_6H_GAIN_BLOCK and pullback_from_6h_high >= FATIGUE_PULLBACK_MIN and (last_red or prev_red or hist_weak):
            fatigue_block = True
            reasons.append("tepe sonrasi yorulma")

        score = int(max(0, min(100, round(score - fatigue_penalty))))
        if fatigue_block:
            status = "YORGUNLUK_BLOCK"
        elif score >= 76:
            status = "HTF GUCLU"
        elif score >= 60:
            status = "HTF POZITIF"
        elif score <= 38:
            status = "HTF ZAYIF"
        else:
            status = "HTF NOTR"

        d.update({
            "htf_trend_score": score,
            "htf_trend_status": status,
            "htf_trend_reason": ", ".join(reasons[:6]) if reasons else "NOTR",
            "htf_gain_6h": gain_6h,
            "htf_pullback_from_high": pullback_from_6h_high,
            "fatigue_block": bool(fatigue_block),
            "fatigue_penalty": int(fatigue_penalty),
        })
        return d
    except Exception as e:
        print("HTF trend context hata:", symbol, e, flush=True)
        d.update({
            "htf_trend_score": 50,
            "htf_trend_status": "HTF HATA",
            "htf_trend_reason": "HATA",
            "fatigue_block": False,
            "fatigue_penalty": 0,
        })
        return d

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
    trend_continuation_ok = bool(d.get("trend_continuation_ok"))
    money_memory_ok = bool(d.get("money_memory_bonus"))
    fomo_exception = (memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok or main_repeat_ok or trend_continuation_ok or money_memory_ok) and d.get("money_gain_from_first", 0) <= 12
    momentum_reload_ok = (
        module == "MOMENTUM"
        and ("MONEY_ACCEL" in support_modules or "MONEY" in support_modules or second_wave_ok or memory_reentry_ok or repeat_force_ok)
        and money_impact >= RELOAD_MIN_MONEY
        and volume_power >= RELOAD_MIN_POWER
        and market_impact_pct >= RELOAD_MIN_MARKET
        and rsi_value <= 72
    )

    if trend_continuation_ok:
        score += int(d.get("trend_continuation_bonus", 0) or 0)
        if module == "TREND_BUILDUP":
            score += 6

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

    # V24 KAT FIX: Dirence cok yakin memory/re-entry sinyalleri Elite skorunu sismesin.
    resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
    if d.get("sr_ok") and not d.get("resistance_broken") and 0 <= resistance_distance <= SR_MEMORY_LATE_BLOCK_PCT:
        score -= SR_NEAR_RESISTANCE_EXTRA_PENALTY

    # V28: Order book duvarlari Elite skoruna etki etsin.
    ob_score = int(d.get("orderbook_score", 50) or 50)
    if ob_score >= 72:
        score += ORDERBOOK_SCORE_BONUS_STRONG
    elif ob_score >= 60:
        score += ORDERBOOK_SCORE_BONUS_OK
    elif ob_score <= 35:
        score -= ORDERBOOK_SCORE_PENALTY_WEAK
    if d.get("ask_wall_usdt", 0) > 0 and d.get("ask_wall_distance_pct", 999) <= ORDERBOOK_ASK_WALL_CLOSE_PCT:
        score -= ORDERBOOK_ASK_WALL_PENALTY
    if d.get("liquidity_gap_up"):
        score += 5
    if d.get("liquidity_gap_down"):
        score -= 5

    # V29: Order Flow / Likidite Boslugu / Likidasyon proxy skor etkisi.
    of_score = int(d.get("orderflow_score", 50) or 50)
    gap_score = int(d.get("liquidity_gap_score", 50) or 50)
    if of_score >= ORDERFLOW_STRONG_SCORE:
        score += ORDERFLOW_SCORE_BONUS_STRONG
    elif of_score >= 65:
        score += ORDERFLOW_SCORE_BONUS_OK
    elif of_score <= ORDERFLOW_WEAK_SCORE:
        score -= ORDERFLOW_SCORE_PENALTY_WEAK
    if gap_score >= 75:
        score += LIQUIDITY_GAP_SCORE_BONUS
    elif gap_score <= 35:
        score -= LIQUIDITY_GAP_SCORE_BONUS
    if d.get("short_squeeze_proxy"):
        score += LIQUIDATION_PROXY_BONUS
    if d.get("long_squeeze_risk"):
        score -= LIQUIDATION_PROXY_BONUS + 6

    # V31: CVD / kümülatif delta skor etkisi.
    cvd_score = int(d.get("cvd_score", 50) or 50)
    if cvd_score >= CVD_STRONG_SCORE:
        score += CVD_SCORE_BONUS_STRONG
    elif cvd_score >= 65:
        score += CVD_SCORE_BONUS_OK
    elif cvd_score <= CVD_WEAK_SCORE:
        score -= CVD_SCORE_PENALTY_WEAK
    if d.get("cvd_hidden_accumulation"):
        score += 6
    if d.get("cvd_fake_pump") or d.get("cvd_distribution_risk"):
        score -= CVD_DIVERGENCE_PENALTY

    # V25: Canli satis baskisi skoru sisirmesin.
    live_pullback_penalty = int(d.get("live_pullback_penalty", 0) or 0)
    if live_pullback_penalty > 0:
        score -= live_pullback_penalty

    alignment_penalty = int(d.get("alignment_penalty", 0) or 0)
    if alignment_penalty > 0:
        score -= alignment_penalty

    late_risk, late_reason = late_rise_pullback_risk(d, support_modules)
    if late_risk:
        score -= LATE_RISE_SCORE_PENALTY
        d["late_rise_block_reason"] = late_reason

    if is_fomo_block(d) and not fomo_exception:
        score -= 30

    # V30: HTF trend, delta gucu ve cok yakin direnc sert kalite etkisi.
    htf_score = int(d.get("htf_trend_score", 50) or 50)
    if htf_score >= 76:
        score += HTF_TREND_BONUS_STRONG
    elif htf_score <= 38:
        score -= HTF_TREND_PENALTY_WEAK
    score -= int(d.get("fatigue_penalty", 0) or 0)

    delta_ratio = float(d.get("delta_ratio_15m", 0) or 0)
    orderflow_score = int(d.get("orderflow_score", 50) or 50)
    if delta_ratio < DELTA_POWER_MIN_RATIO and orderflow_score < DELTA_POWER_MIN_ORDERFLOW:
        score -= 14
    if d.get("sr_ok") and not d.get("resistance_broken") and 0 <= resistance_distance <= HARD_RESISTANCE_BLOCK_PCT:
        score -= 35

    # V36: Elite Guven Skoru final puana kontrollu etki eder.
    conf = int(d.get("elite_confidence_score", 50) or 50)
    if conf >= 82:
        score += 10
    elif conf >= BINANCE_ELITE_CONFIDENCE_BONUS_SCORE:
        score += 6
    elif conf < BINANCE_ELITE_CONFIDENCE_BLOCK_SCORE:
        score -= 18
    elif conf < BINANCE_ELITE_CONFIDENCE_WARN_SCORE:
        score -= 8

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
    trend_continuation_ok = bool(best.get("trend_continuation_ok"))
    repeat_force_ok = bool(best.get("repeat_force"))
    history_force_ok = bool(best.get("history_force"))
    effective_money = max(best.get("money_impact", 0), best.get("effective_money_impact", 0))
    effective_power = max(best.get("volume_power", 0), best.get("effective_volume_power", 0))
    effective_market = max(best.get("market_impact_pct", 0), best.get("effective_market_impact_pct", 0))

    fomo_exception = (memory_reentry_ok or second_wave_ok or repeat_force_ok or history_force_ok or trend_continuation_ok) and best.get("money_gain_from_first", 0) <= 12
    if is_fomo_block(best) and not fomo_exception:
        return False, "FOMO_BLOCK"

    # V21: SYN tipi gec trend / tepeden geri cekilme korumasi.
    late_risk, late_reason = late_rise_pullback_risk(best, support_modules)
    if late_risk:
        return False, late_reason

    # V24 KAT FIX: Direnc altinda, hafiza/re-entry ile gec gelen AL'i direkt kes.
    nr_block, nr_reason = near_resistance_late_memory_block(best)
    if nr_block:
        return False, nr_reason

    # V25: Son mumlarda satis baskisi basladiysa hafiza/re-entry bile AL verdirmesin.
    if best.get("live_pullback_block"):
        return False, best.get("live_pullback_status", "SATIS_BASKISI_BLOCK")

    # V26: Teknik guclu ama grafik zayifsa Elite AL verme.
    if best.get("alignment_block"):
        return False, best.get("alignment_status", "GRAFIK_TEKNIK_UYUMSUZ")

    # V28: Order book satici duvari cok yakin ise Elite AL verme.
    if best.get("orderbook_block"):
        return False, best.get("orderbook_status", "ORDERBOOK_SATICI_DUVARI")

    # V29: Order flow agresif saticiya donduyse Elite AL verme.
    if best.get("orderflow_block"):
        return False, best.get("orderflow_status", "ORDER_FLOW_BLOCK")

    # V31: CVD negatif / sahte yukselis varsa Elite AL verme.
    if best.get("cvd_block"):
        return False, best.get("cvd_status", "CVD_BLOCK")
    if best.get("cvd_fake_pump") and int(best.get("orderflow_score", 50) or 50) < 70:
        return False, "CVD_SAHTE_YUKSELIS"

    # V30: Saatlik/4s trend, delta gucu ve cok yakin direnc sert kapilari.
    if best.get("fatigue_block"):
        return False, best.get("htf_trend_status", "YUKSELIS_YORGUNLUGU_BLOCK")
    if int(best.get("htf_trend_score", 50) or 50) < HTF_TREND_MIN_FOR_ELITE and module not in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        return False, "HTF_TREND_ZAYIF"
    if (
        float(best.get("delta_ratio_15m", 0) or 0) < DELTA_POWER_MIN_RATIO
        and int(best.get("orderflow_score", 50) or 50) < DELTA_POWER_BLOCK_ORDERFLOW
        and not best.get("strong_buyer_dominant")
    ):
        return False, "DELTA_ORDERFLOW_ZAYIF"
    if (
        best.get("sr_ok")
        and not best.get("resistance_broken")
        and 0 <= float(best.get("resistance_distance_pct", 999) or 999) <= HARD_RESISTANCE_BLOCK_PCT
        and not best.get("short_squeeze_proxy")
    ):
        return False, "DIRENC_030_COK_YAKIN"

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
        if not (money_memory_ok or history_ok or memory_reentry_ok or second_wave_ok or main_repeat_ok or trend_continuation_ok or repeat_force_ok or history_force_ok or module == "TREND_BUILDUP"):
            return False, "PARA_ZAYIF"

    if not market_impact_ok(best):
        market_memory_exception = (
            money_memory_ok or memory_reentry_ok or second_wave_ok or main_repeat_ok or trend_continuation_ok or repeat_force_ok or history_force_ok
        ) and (best.get("money_market_60m", 0) >= 0.25 or effective_market >= 0.25 or best.get("money_mem_60m", 0) >= 250_000)
        if not market_memory_exception:
            return False, "MARKET_ETKI_ZAYIF"

    rsi_value = best.get("rsi", best.get("rsi15", 0))
    if rsi_value > 72 and not (module == "PRE_ROCKET_SQUEEZE" and rsi_value <= PRE_ROCKET_MAX_RSI) and not (trend_continuation_ok and rsi_value <= 76):
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
        or trend_continuation_ok
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
    if int(d.get("htf_trend_score", 50) or 50) < HTF_TREND_MIN_FOR_GOLD:
        return False
    if int(d.get("orderflow_score", 50) or 50) < 65:
        return False
    if d.get("sr_ok") and not d.get("resistance_broken") and 0 <= float(d.get("resistance_distance_pct", 999) or 999) <= 1.0:
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
    if elite_gold and int(d.get("cvd_score", 50) or 50) < 58:
        return False

    return elite_gold



def walking_score_signal(d, support_modules=None):
    """
    V23 YURUME SKORU:
    Elite skoru filtre kapisidir; yürüme skoru ise gelen Elite sinyalleri arasinda
    hangisinin daha kaliteli / devam etme ihtimali daha yuksek oldugunu siralar.
    Para kalitesi + radar kombinasyonu + hafiza + yapi kalitesi birlikte puanlanir.
    """
    support_modules = support_modules or []
    if not d:
        return {"walking_score": 0, "quality_class": "D", "walking_reasons": "VERI YOK"}

    score = 0
    reasons = []
    module = d.get("module", "UNKNOWN")

    money = max(float(d.get("money_impact", 0) or 0), float(d.get("effective_money_impact", 0) or 0), float(d.get("history_money_max", 0) or 0))
    power = max(float(d.get("volume_power", 0) or 0), float(d.get("effective_volume_power", 0) or 0), float(d.get("history_power_max", 0) or 0))
    market = max(float(d.get("market_impact_pct", 0) or 0), float(d.get("effective_market_impact_pct", 0) or 0), float(d.get("history_market_max", 0) or 0), float(d.get("money_market_60m", 0) or 0))
    rs = float(d.get("rs", 0) or 0)
    rsi_value = float(d.get("rsi", d.get("rsi15", 0)) or 0)

    combo_score, radar_count = radar_combo_score(d, support_modules)
    history_points = int(d.get("history_points", 0) or 0)
    waves = int(d.get("money_wave_count", 0) or 0)
    money_mem_60m = float(d.get("money_mem_60m", 0) or 0)
    main_count_120 = int(d.get("main_signal_count_120m", 0) or 0)
    resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
    support_distance = float(d.get("support_distance_pct", 999) or 999)
    rise_6h = float(d.get("price_change_6h", 0) or 0)
    dist_from_low = float(d.get("dist_from_low", 0) or 0)
    price_gain_from_first = float(d.get("price_gain_from_first", 0) or 0)

    # 1) Para kalitesi - agirlik yaklasik %40
    if money >= 5:
        score += 18; reasons.append("Para cok guclu")
    elif money >= 3:
        score += 15; reasons.append("Para guclu")
    elif money >= 2:
        score += 11; reasons.append("Para iyi")
    elif money >= 1.5:
        score += 7; reasons.append("Para orta")
    else:
        score += 2; reasons.append("Para zayif")

    if power >= 20:
        score += 14; reasons.append("Hacim gucu cok yuksek")
    elif power >= 10:
        score += 11; reasons.append("Hacim gucu yuksek")
    elif power >= 5:
        score += 8; reasons.append("Hacim gucu iyi")
    elif power >= 3:
        score += 5; reasons.append("Hacim gucu orta")

    if market >= 3:
        score += 10; reasons.append("Market etki cok guclu")
    elif market >= 1:
        score += 8; reasons.append("Market etki guclu")
    elif market >= 0.35:
        score += 5; reasons.append("Market etki iyi")
    elif market >= 0.10:
        score += 3; reasons.append("Market etki var")

    # 2) Radar kalitesi - agirlik yaklasik %25
    if radar_count >= 4:
        score += 16; reasons.append("Radar sayisi cok guclu")
    elif radar_count >= 3:
        score += 13; reasons.append("Radar sayisi guclu")
    elif radar_count >= 2:
        score += 8; reasons.append("Radar sayisi yeterli")
    else:
        score += 2; reasons.append("Tek radar")

    if combo_score >= 8:
        score += 9; reasons.append("Radar kombinasyonu guclu")
    elif combo_score >= 5:
        score += 6; reasons.append("Radar kombinasyonu iyi")
    elif combo_score >= 3:
        score += 3; reasons.append("Radar kombinasyonu orta")

    # 3) Hafiza / devam kalitesi - agirlik yaklasik %20
    if d.get("memory_reentry"):
        score += 8; reasons.append("Memory Re-Entry")
    if d.get("second_wave_bonus"):
        score += 8; reasons.append("Second Wave")
    if d.get("money_memory_bonus"):
        score += 7; reasons.append("Money Memory")
    if waves >= 5:
        score += 6; reasons.append("Coklu para dalgasi")
    elif waves >= 3:
        score += 4; reasons.append("Para dalgasi var")
    if money_mem_60m >= 1_000_000:
        score += 5; reasons.append("60dk para hafizasi yuksek")
    elif money_mem_60m >= 250_000:
        score += 3; reasons.append("60dk para hafizasi var")
    if history_points >= 35:
        score += 5; reasons.append("Radar hafizasi guclu")
    elif history_points >= 20:
        score += 3; reasons.append("Radar hafizasi var")
    if main_count_120 >= 5:
        score += 4; reasons.append("Ana kanal tekrar guclu")
    elif main_count_120 >= 3:
        score += 2; reasons.append("Ana kanal tekrar var")

    # 4) Yapi kalitesi - agirlik yaklasik %15
    if 0 <= support_distance <= 2.5:
        score += 5; reasons.append("Destek ustu")
    elif 0 <= support_distance <= 5:
        score += 3; reasons.append("Destek yakin")
    if resistance_distance >= 8 and resistance_distance < 900:
        score += 6; reasons.append("Direnc rahat")
    elif resistance_distance >= 4 and resistance_distance < 900:
        score += 4; reasons.append("Direnc uzak")
    elif 0 <= resistance_distance <= 0.9:
        score -= 22; reasons.append("Direnc cok yakin")
    elif 0 <= resistance_distance <= 1.5:
        score -= 14; reasons.append("Direnc yakin")
    if d.get("resistance_broken"):
        score += 5; reasons.append("Direnc kirilimi")
    if d.get("buyer_dominant"):
        score += 4; reasons.append("Delta alici baskin")
    if d.get("strong_buyer_dominant"):
        score += 6; reasons.append("Delta guclu alici")
    if d.get("seller_dominant") or d.get("strong_seller_dominant"):
        score -= 12; reasons.append("Delta satici baskin")
    if d.get("oi_strong_long_supported"):
        score += 5; reasons.append("OI guclu long destekli")
    elif d.get("oi_long_supported"):
        score += 3; reasons.append("OI long destekli")
    elif d.get("oi_weak"):
        score -= 4; reasons.append("OI zayif")

    # Erkenlik / FOMO cezalari
    if rise_6h >= 18:
        score -= 16; reasons.append("6s yukselis fazla")
    elif rise_6h >= 12:
        score -= 8; reasons.append("6s yukselis yuksek")
    if dist_from_low >= 28:
        score -= 12; reasons.append("Dipten cok uzak")
    elif dist_from_low >= 20:
        score -= 6; reasons.append("Dipten uzak")
    if price_gain_from_first > 6:
        score -= 10; reasons.append("Ilk sinyalden sonra gec")
    if rsi_value >= 76:
        score -= 12; reasons.append("RSI sisik")
    elif rsi_value >= 72:
        score -= 6; reasons.append("RSI yuksek")
    elif 45 <= rsi_value <= 66:
        score += 3; reasons.append("RSI saglikli")
    if rs >= 85:
        score += 4; reasons.append("RS cok guclu")
    elif rs >= 75:
        score += 2; reasons.append("RS guclu")

    # Mod bazli ufak ayar
    if module in ("HISTORY_BUILDUP", "PRE_ROCKET_SQUEEZE", "TREND_BUILDUP"):
        score += 3
    if module == "MOMENTUM" and radar_count <= 1:
        score -= 8; reasons.append("Tek momentum riskli")

    # V25: Yurume skorunda canli satis baskisini daha net goster.
    live_pullback_penalty = int(d.get("live_pullback_penalty", 0) or 0)
    if live_pullback_penalty >= 30:
        score -= 20; reasons.append("Canli satis baskisi yuksek")
    elif live_pullback_penalty >= 18:
        score -= 12; reasons.append("Canli satis baskisi var")
    elif live_pullback_penalty >= 10:
        score -= 7; reasons.append("Son mum zayif")

    alignment_penalty = int(d.get("alignment_penalty", 0) or 0)
    if alignment_penalty >= 30:
        score -= 18; reasons.append("Grafik-teknik uyumsuz")
    elif alignment_penalty >= 18:
        score -= 10; reasons.append("Grafik zayif")
    elif alignment_penalty >= 10:
        score -= 5; reasons.append("Uyum notr")

    # V29: Yurume skorunda order flow ve likidite boslugu etkisi.
    of_score = int(d.get("orderflow_score", 50) or 50)
    gap_score = int(d.get("liquidity_gap_score", 50) or 50)
    if of_score >= 82:
        score += 12; reasons.append("Agresif alici")
    elif of_score >= 65:
        score += 6; reasons.append("Order flow alici")
    elif of_score <= 35:
        score -= 14; reasons.append("Order flow satici")
    if gap_score >= 75:
        score += 7; reasons.append("Yukari likidite boslugu")
    elif gap_score <= 35:
        score -= 8; reasons.append("Asagi bosluk riski")
    if d.get("short_squeeze_proxy"):
        score += 8; reasons.append("Short sikisma adayi")
    if d.get("long_squeeze_risk"):
        score -= 12; reasons.append("Long sikisma riski")

    score = max(0, min(100, int(round(score))))
    if score >= 92:
        quality = "A+"
    elif score >= 84:
        quality = "A"
    elif score >= 74:
        quality = "B"
    elif score >= 62:
        quality = "C"
    else:
        quality = "D"

    # Mesaj cok uzamasin diye ilk 6 sebep.
    reason_text = ", ".join(reasons[:6]) if reasons else "Nötr"
    return {"walking_score": score, "quality_class": quality, "walking_reasons": reason_text}



def is_elite_prep_candidate(best, elite_score, support_modules=None):
    """
    V35 BINANCE ELITE HAZIRLIK:
    Hazirlik kanali AL degildir; ana kanalda israrli gelen, para/hacim toparlayan
    ama Elite AL kapisini henuz tamamlayamayan coinleri erken takip kanalina yollar.
    Elite kapisi yine sıkı kalır; hazırlık kapısı daha esnektir.
    """
    if not best:
        return False, "VERI_YOK"

    support_modules = support_modules or []
    module = best.get("module", "UNKNOWN")
    if module in ("EARLY",):
        return False, "COK_ERKEN"

    if elite_score < ELITE_PREP_MIN_SCORE or elite_score > ELITE_PREP_MAX_SCORE:
        return False, "SKOR_ARALIK_DISI"

    walk = walking_score_signal(best, support_modules)
    walk_score = int(walk.get("walking_score", 0) or 0)
    orderflow_score = int(best.get("orderflow_score", 50) or 50)
    htf_score = int(best.get("htf_trend_score", 50) or 50)
    cvd_score = int(best.get("cvd_score", 50) or 50)
    resistance_distance = float(best.get("resistance_distance_pct", 999) or 999)

    main60 = int(best.get("main_signal_count_60m", 0) or 0)
    main120 = int(best.get("main_signal_count_120m", 0) or 0)
    money = max(float(best.get("money_impact", 0) or 0), float(best.get("effective_money_impact", 0) or 0))
    power = max(float(best.get("volume_power", 0) or 0), float(best.get("effective_volume_power", 0) or 0))
    rsi_value = float(best.get("rsi", best.get("rsi15", 0)) or 0)

    repeat_prep = (
        (main60 >= ELITE_PREP_REPEAT_60M or main120 >= ELITE_PREP_REPEAT_120M or best.get("main_repeat_buildup"))
        and money >= ELITE_PREP_REPEAT_MIN_MONEY
        and power >= ELITE_PREP_REPEAT_MIN_POWER
        and rsi_value <= ELITE_PREP_REPEAT_MAX_RSI
    )

    # Sert teknik tehlike varsa hazirlik bile verme; ana kanalda izleme kalsin.
    if best.get("orderbook_block") or best.get("orderflow_block") or best.get("cvd_block"):
        return False, "SERT_FLOW_BLOCK"
    if best.get("alignment_block") or best.get("live_pullback_block"):
        return False, "GRAFIK_SATIS_BLOCK"
    if 0 <= resistance_distance <= HARD_RESISTANCE_BLOCK_PCT:
        return False, "DIRENC_COK_YAKIN"
    if best.get("fatigue_block"):
        return False, "YORGUNLUK_BLOCK"

    # V35: Ana kanal israrli tekrar ediyorsa Order Flow/CVD biraz zayif olsa bile
    # hazirlik kanalina al. Bu AL degildir; kullanici coini kacmadan takip eder.
    if repeat_prep:
        if htf_score < 38:
            return False, "TEKRAR_VAR_AMA_HTF_ZAYIF"
        if cvd_score < 30:
            return False, "TEKRAR_VAR_AMA_CVD_COK_ZAYIF"
        return True, "ANA_KANAL_TEKRAR_HAZIRLIK"

    if walk_score < ELITE_PREP_MIN_WALK:
        return False, "YURUME_ZAYIF"
    if orderflow_score < ELITE_PREP_MIN_ORDERFLOW:
        return False, "ORDER_FLOW_ZAYIF"
    if htf_score < ELITE_PREP_MIN_TREND:
        return False, "TREND_ZAYIF"
    if cvd_score < 35:
        return False, "CVD_COK_ZAYIF"

    return True, "OK"



def weak_elite_should_go_prep(best, support_modules=None):
    """
    V34 ZAYIF ELITE -> HAZIRLIK:
    Elite skoru yuksek olsa bile kalite C/D, CVD zayif, order flow dengeli/zayif,
    delta notr/negatif veya order book satici ise direkt Elite AL yerine Hazirlik kanalina atar.
    Amac: SNDK tipi "skor 100 ama alici saldirisi net degil" sinyalleri AL kanalindan once izlemeye almak.
    """
    support_modules = support_modules or []
    if not best:
        return False, "VERI_YOK"

    walk = walking_score_signal(best, support_modules)
    walk_score = int(walk.get("walking_score", 0) or 0)
    quality = walk.get("quality_class", "D")
    orderflow_score = int(best.get("orderflow_score", 50) or 50)
    cvd_score = int(best.get("cvd_score", 50) or 50)
    delta_ratio = float(best.get("delta_ratio_15m", 0) or 0)
    orderbook_score = int(best.get("orderbook_score", 50) or 50)
    resistance_distance = float(best.get("resistance_distance_pct", 999) or 999)

    weak_flags = []
    if quality in ("C", "D") or walk_score < 70:
        weak_flags.append("kalite/yurume zayif")
    if orderflow_score < 55:
        weak_flags.append("order flow net degil")
    if cvd_score < 45:
        weak_flags.append("cvd zayif")
    if delta_ratio < 3:
        weak_flags.append("delta notr/negatif")
    if orderbook_score < 35:
        weak_flags.append("order book satici")
    if 0 <= resistance_distance <= 1.00:
        weak_flags.append("direnc yakin")

    # En az iki zayiflik varsa Elite AL yerine Hazirlik'a dusur.
    if len(weak_flags) >= 2:
        return True, ", ".join(weak_flags[:4])
    return False, "OK"

def format_elite_prep_signal(symbol, d, elite_score, support_modules=None):
    """
    V33 SADE ELITE HAZIRLIK MESAJI:
    Hazirlik kanali sadece erken takip ekranidir.
    Order Flow / CVD / Delta / OI / Order Book / Likidite / Trend gibi detaylar
    Elite AL ONAY mesajinda gosterilir.
    """
    support_modules = support_modules or []
    walk = walking_score_signal(d, support_modules)
    walk_score = int(walk.get("walking_score", 0) or 0)
    q = walk.get("quality_class", "D")
    combo_score, radar_count = radar_combo_score(d, support_modules)

    module = d.get("module", "UNKNOWN")
    price = float(d.get("entry", d.get("price", 0)) or 0)

    short_notes = []
    if walk_score >= 80:
        short_notes.append("Yurume guclu")
    elif walk_score >= 70:
        short_notes.append("Yurume aday")

    if int(d.get("orderflow_score", 50) or 50) >= 65:
        short_notes.append("Alici akisi var")
    if int(d.get("cvd_score", 50) or 50) >= 65:
        short_notes.append("CVD pozitif")
    if d.get("memory_reentry") or d.get("second_wave_bonus"):
        short_notes.append("Hafiza / ikinci dalga")
    if int(d.get("main_signal_count_60m", 0) or 0) >= ELITE_PREP_REPEAT_60M:
        short_notes.append(f"Ana kanal tekrar {int(d.get('main_signal_count_60m', 0) or 0)}x")
    if float(d.get("resistance_distance_pct", 999) or 999) <= 1.5:
        short_notes.append("Direnc yakin, kirilim beklenmeli")

    note_text = " | ".join(short_notes[:3]) if short_notes else "Elite kapisina yaklasiyor"

    return f"""
🏆 BINANCE ELITE HAZIRLIK

🔥 {symbol.replace(':USDT','')} 🔥

Mod: {module}
Fiyat: {price:.8f}

Elite Aday Skoru: {elite_score}/100
Yurume Skoru: {walk_score}/100
Kalite: {q}
Radar: {radar_count} | Kombinasyon: {combo_score}

Kisa Not:
{note_text}

Karar:
AL DEGIL - ELITE AL ONAY BEKLE
""".strip()

def send_elite_prep_signal(symbol, best, support, elite_score):
    if not BINANCE_ELITE_PREP_CHAT_ID:
        return False

    ok, reason = is_elite_prep_candidate(best, elite_score, support)
    if not ok:
        print("ELITE PREP BLOCK:", symbol, best.get("module"), reason, "EliteScore:", elite_score, flush=True)
        return False

    key = symbol + "_ELITE_PREP"
    if not can_send(sent_elite_prep, key, ELITE_PREP_COOLDOWN):
        return False

    send_telegram(format_elite_prep_signal(symbol, best, elite_score, support), BINANCE_ELITE_PREP_CHAT_ID)
    ft_record_stage(symbol, best, "PREP", support, {"elite_score": elite_score})
    print("ELITE PREP SEND:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
    return True

def format_elite_signal(symbol, d, elite_score, support_modules=None):
    """
    V29 SADE TELEGRAM MESAJI:
    Radar/para hafizasi detaylari bot icinde kalir; Telegram sadece karar verdiren bilgileri gosterir.
    Coin adi belirgin olsun diye Unicode bold kullanilir, parse_mode gerektirmez.
    """
    support_modules = support_modules or []
    module = d.get("module", "UNKNOWN")
    combo_score, radar_count = radar_combo_score(d, support_modules)
    levels = build_entry_levels(d)
    elite_gold = is_elite_gold_signal(d, elite_score, support_modules, symbol)
    walk = walking_score_signal(d, support_modules)

    def bold_text(s):
        normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        bold = "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
        table = str.maketrans({a: b for a, b in zip(normal, bold)})
        return str(s).upper().translate(table)

    def fmt_usdt(v):
        try:
            v = float(v or 0)
        except Exception:
            v = 0.0
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"{v/1_000:.0f}K"
        return f"{v:.0f}"

    def yes_no(v):
        return "VAR" if v else "YOK"

    q = walk.get("quality_class", "D")
    walk_score = int(walk.get("walking_score", 0) or 0)

    market_impact = max(
        float(d.get("market_impact_pct", 0) or 0),
        float(d.get("effective_market_impact_pct", 0) or 0),
        float(d.get("history_market_max", 0) or 0),
        float(d.get("money_market_60m", 0) or 0),
    )
    money_impact = max(
        float(d.get("money_impact", 0) or 0),
        float(d.get("effective_money_impact", 0) or 0),
        float(d.get("history_money_max", 0) or 0),
    )
    volume_power = max(
        float(d.get("volume_power", 0) or 0),
        float(d.get("effective_volume_power", 0) or 0),
        float(d.get("history_power_max", 0) or 0),
    )

    resistance_distance = float(d.get("resistance_distance_pct", 999) or 999)
    support_distance = float(d.get("support_distance_pct", 999) or 999)
    delta_status = d.get("delta_status", "DELTA VERI YOK")
    oi_status = d.get("oi_status", "OI VERI YOK")
    alignment_status = d.get("alignment_status", "YOK")
    alignment_score = int(d.get("alignment_score", 0) or 0)
    alignment_penalty = int(d.get("alignment_penalty", 0) or 0)
    live_pullback_penalty = int(d.get("live_pullback_penalty", 0) or 0)
    orderbook_status = d.get("orderbook_status", "ORDERBOOK VERI YOK")
    orderbook_score = int(d.get("orderbook_score", 50) or 50)
    orderflow_status = d.get("orderflow_status", "ORDER FLOW VERI YOK")
    orderflow_score = int(d.get("orderflow_score", 50) or 50)
    gap_status = d.get("liquidity_gap_status", "BOSLUK VERI YOK")
    gap_score = int(d.get("liquidity_gap_score", 50) or 50)
    liq_status = d.get("liquidation_proxy_status", "LIKIDASYON NOTR")
    liq_score = int(d.get("liquidation_proxy_score", 50) or 50)
    cvd_status = d.get("cvd_status", "CVD VERI YOK")
    cvd_score = int(d.get("cvd_score", 50) or 50)
    cvd_trend = d.get("cvd_trend", "YOK")

    risk_reasons = []
    positives = []
    negatives = []

    if walk_score >= 90:
        positives.append("Yurume skoru cok guclu")
    elif walk_score >= 80:
        positives.append("Yurume skoru guclu")

    if money_impact >= 3:
        positives.append("Para guclu")
    elif money_impact >= 2:
        positives.append("Para iyi")

    if volume_power >= 10:
        positives.append("Hacim gucu cok yuksek")
    elif volume_power >= 5:
        positives.append("Hacim gucu iyi")

    if market_impact >= 1:
        positives.append("Market etki guclu")

    if radar_count >= 3:
        positives.append("Radarlar guclu")

    if d.get("memory_reentry"):
        positives.append("Memory Re-Entry")
    if d.get("second_wave_bonus"):
        positives.append("Second Wave")
    if d.get("buyer_dominant") or d.get("strong_buyer_dominant"):
        positives.append("Delta alici baskin")
    if d.get("oi_long_supported") or d.get("oi_strong_long_supported"):
        positives.append("OI long destekli")
    if orderbook_score >= 70:
        positives.append("Order book alici")
    if d.get("liquidity_gap_up"):
        positives.append("Yukari likidite boslugu")
    if orderflow_score >= 80:
        positives.append("Agresif alici")
    elif orderflow_score >= 65:
        positives.append("Order flow alici")
    if d.get("short_squeeze_proxy"):
        positives.append("Short sikisma adayi")
    if cvd_score >= 78:
        positives.append("CVD cok guclu")
    elif cvd_score >= 65:
        positives.append("CVD pozitif")
    if d.get("cvd_hidden_accumulation"):
        positives.append("CVD gizli toplama")

    if d.get("orderbook_block") or orderbook_score <= 35:
        risk_reasons.append("Order book satici")
        negatives.append("Order book satici")
    elif d.get("ask_wall_usdt", 0) > 0 and d.get("ask_wall_distance_pct", 999) <= ORDERBOOK_ASK_WALL_CLOSE_PCT:
        risk_reasons.append("Yakin satis duvari")
        negatives.append("Yakin satis duvari")

    if d.get("orderflow_block") or orderflow_score <= 35:
        risk_reasons.append("Order flow satici")
        negatives.append("Order flow satici")
    elif d.get("long_squeeze_risk"):
        risk_reasons.append("Long sikisma riski")
        negatives.append("Long sikisma riski")

    if d.get("cvd_block") or cvd_score <= 35:
        risk_reasons.append("CVD negatif")
        negatives.append("CVD negatif")
    elif d.get("cvd_fake_pump"):
        risk_reasons.append("CVD sahte yukselis")
        negatives.append("CVD sahte yukselis")
    elif d.get("cvd_distribution_risk"):
        risk_reasons.append("CVD dagitim riski")
        negatives.append("CVD dagitim riski")

    if 0 <= resistance_distance <= 0.80:
        risk_reasons.append("Direnc cok yakin")
        negatives.append("Direnc cok yakin")
    elif 0 <= resistance_distance <= 1.50:
        risk_reasons.append("Direnc yakin")
        negatives.append("Direnc yakin")

    if "SATICI" in str(delta_status):
        risk_reasons.append("Delta satici baskin")
        negatives.append("Delta satici baskin")
    elif "NOTR" in str(delta_status):
        negatives.append("Delta notr")

    if "ZAYIF" in str(oi_status):
        risk_reasons.append("OI zayif")
        negatives.append("OI zayif")

    if "UYUMSUZ" in str(alignment_status) or alignment_penalty >= 30:
        risk_reasons.append("Grafik-teknik uyumsuz")
        negatives.append("Grafik-teknik uyumsuz")
    elif alignment_penalty >= 18:
        risk_reasons.append("Grafik zayif")
        negatives.append("Grafik zayif")

    if live_pullback_penalty >= 24:
        risk_reasons.append("Canli satis baskisi")
        negatives.append("Canli satis baskisi")

    if not positives:
        positives.append("Filtrelerden gecti")
    if not negatives:
        negatives.append("Belirgin negatif yok")

    if len(risk_reasons) >= 2 or resistance_distance <= 0.55 or "UYUMSUZ" in str(alignment_status):
        risk_status = "YUKSEK"
        result = "DIKKATLI AL / KIRILIM BEKLE"
    elif risk_reasons or q in ("C", "D"):
        risk_status = "ORTA"
        result = "KONTROLLU AL"
    elif q in ("A+", "A") and walk_score >= 84:
        risk_status = "DUSUK"
        result = "GUCLU AL"
    else:
        risk_status = "ORTA"
        result = "NORMAL AL"

    title = "🔥 BINANCE ELITE GOLD AL ONAY" if elite_gold else "🚀 BINANCE ELITE AL ONAY"
    coin_line = f"🔥 {bold_text(symbol.replace(':USDT',''))} 🔥"

    positives_text = "\n".join([f"✔ {x}" for x in positives[:4]])
    negatives_text = "\n".join([f"❌ {x}" for x in negatives[:4]])
    risk_reason_text = ", ".join(risk_reasons[:3]) if risk_reasons else "Belirgin ana risk yok"
    pie_history_text = pie_signal_history_text(d, support_modules, "BINANCE")

    return f"""
{title}

{coin_line}

🏆 Kalite: {q}
📈 Yurume Skoru: {walk_score}/100
✅ Grafik-Teknik Uyum: {alignment_status} ({alignment_score}/100)
🧭 1H/4H Trend: {d.get('htf_trend_status', 'YOK')} ({int(d.get('htf_trend_score', 50) or 50)}/100)
⚠️ Risk Durumu: {risk_status}

━━━━━━━━━━━━━━━━

Mod: {module}
Karar: AL
Elite Skoru: {elite_score}/100
🧠 Elite Guven: {int(d.get('elite_confidence_score', 50) or 50)}/100 - {d.get('elite_confidence_label', 'YOK')}
Radar: {radar_count} | Kombinasyon: {combo_score}

{pie_history_text}

🎯 Giris: {levels['entry']:.8f}
🛑 Stop: {levels['stop']:.8f}
TP1: {levels['tp1']:.8f}
TP2: {levels['tp2']:.8f}
TP3: {levels['tp3']:.8f}
TP Sistemi: {levels.get('tp_system', 'RISK_KATLI')}

━━━━━━━━━━━━━━━━

🟢 Destek: {d.get('support_level', 0):.8f}
🔴 Direnc: {d.get('resistance_level', 0):.8f}
📏 Destek Mesafesi: %{support_distance:.2f}
📏 Direnc Mesafesi: %{resistance_distance:.2f}
Direnc Durumu: {d.get('sr_status', 'SR VERI YOK')}

━━━━━━━━━━━━━━━━

💰 Para Etkisi: {money_impact:.2f}x
📊 Hacim Gucu: {volume_power:.2f}
🌊 Market Etki: %{market_impact:.2f}

📚 Order Book: {orderbook_status} ({orderbook_score}/100)
🟢 Alis Duvari: {fmt_usdt(d.get('bid_wall_usdt', 0))} @ {d.get('bid_wall_price', 0):.8f}
🔴 Satis Duvari: {fmt_usdt(d.get('ask_wall_usdt', 0))} @ {d.get('ask_wall_price', 0):.8f}

⚡ Order Flow: {orderflow_status} ({orderflow_score}/100)
🚀 Likidite Boslugu: {gap_status} ({gap_score}/100)
🔥 Likidasyon Proxy: {liq_status} ({liq_score}/100)
📈 CVD: {cvd_status} ({cvd_score}/100) | Trend: {cvd_trend}

📈 OI: {oi_status}
⚖️ Delta: {delta_status}

🟢 Long Akisi: {fmt_usdt(d.get('long_flow_15m', 0))} USDT
🔴 Short Akisi: {fmt_usdt(d.get('short_flow_15m', 0))} USDT
Net Delta: {fmt_usdt(d.get('net_delta_15m', 0))} USDT

━━━━━━━━━━━━━━━━

📝 BOT OZETI

{positives_text}

{negatives_text}

Risk Sebebi:
{risk_reason_text}

Guven Sebebi:
{d.get('elite_confidence_reason', 'YOK')}

Sonuc:
{result}
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
    if not BINANCE_ELITE_GOLD_CHAT_ID:
        return False

    # V19: Elite karari verilmeden once destek/direnc baglamini ekle.
    best = attach_support_resistance_context(symbol, best)

    # V25: Elite karari verilmeden once son 15m canli satis/pullback durumunu ekle.
    best = attach_live_pullback_context(symbol, best)

    # V26: Grafik ve teknik uyumlu mu kontrol et.
    best = attach_graph_technical_alignment(symbol, best)

    # V30: 1H / 4H trend ve yukselis yorgunlugu kontrolu.
    best = attach_higher_timeframe_trend_context(symbol, best)

    # V28: Emir defteri / order book duvarlarini ekle.
    best = attach_orderbook_context(symbol, best)

    # V29: Order flow / likidite boslugu / likidasyon proxy ekle.
    best = attach_orderflow_context(symbol, best)

    # V31: CVD / kümülatif delta hafizasini ekle.
    best = attach_cvd_context(symbol, best)

    # V36: AI karar katmani - radar agirligi + sira + canli kalite guveni.
    best = attach_binance_elite_confidence(best, support)

    elite_score = elite_score_signal(best, support)

    weak_prep, weak_reason = weak_elite_should_go_prep(best, support)
    if elite_score >= ELITE_MIN_SCORE and weak_prep:
        print("ELITE WEAK -> PREP:", symbol, best.get("module"), weak_reason, "EliteScore:", elite_score, flush=True)
        send_elite_prep_signal(symbol, best, support, elite_score)
        return False

    ok, reason = is_elite_al_candidate(best, support)
    if not ok:
        print("ELITE BLOCK:", symbol, best.get("module"), reason, "EliteScore:", elite_score, flush=True)
        send_elite_prep_signal(symbol, best, support, elite_score)
        return False

    if elite_score < ELITE_MIN_SCORE:
        print("ELITE SCORE LOW:", symbol, best.get("module"), "EliteScore:", elite_score, flush=True)
        send_elite_prep_signal(symbol, best, support, elite_score)
        return False

    if int(best.get("elite_confidence_score", 50) or 50) < BINANCE_ELITE_CONFIDENCE_BLOCK_SCORE and best.get("module") not in ("DIP", "SWEEP", "FAST_LIQUIDITY_SWEEP"):
        print("ELITE CONFIDENCE BLOCK:", symbol, best.get("module"), best.get("elite_confidence_score"), best.get("elite_confidence_reason"), flush=True)
        send_elite_prep_signal(symbol, best, support, elite_score)
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

    # V45 PIE KAYIT FIX:
    # Elite/Gold mesaji Telegram'a gitmeden once mutlaka PIE kaydina yazilir.
    # Boylece gunluk performans raporu gercek Elite sinyallerini sayar.
    try:
        levels = pie_build_binance_levels(best)
        pie_record_elite_signal(symbol, best, support, elite_score, levels, market="BINANCE")
    except Exception as e:
        print("PIE RECORD FIX HATA:", symbol, e, flush=True)

    ft_record_stage(symbol, best, "GOLD", support, {"elite_score": elite_score, "elite_gold": elite_gold})

    # V46: Binance iki kanalli yapi. Final AL/Gold mesajlari Gold kanalina gider.
    target_chat_id = BINANCE_ELITE_GOLD_CHAT_ID
    send_telegram(format_elite_signal(symbol, best, elite_score, support), target_chat_id)
    mark_elite_sent_today(symbol)
    print("ELITE GOLD SEND:" if elite_gold else "ELITE AL SEND:", symbol, best.get("module"), "EliteScore:", elite_score, "Chat:", target_chat_id, flush=True)
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
        "PRE_BREAKOUT_WATCH": (sent_pre_breakout_watch, COOLDOWN_PRE_BREAKOUT_WATCH),
    }

    cache, cooldown = cooldown_map.get(best["module"], (sent_early, COOLDOWN_EARLY))
    key = symbol + "_" + best["module"]

    if best["module"] == "EARLY" and not can_send_early_today(symbol):
        print("EARLY DAILY LIMIT:", symbol, "Limit:", EARLY_MAX_PER_SYMBOL_PER_DAY, flush=True)
        return False

    if can_send(cache, key, cooldown):
        ft_record_stage(symbol, best, "MAIN", support, {"btc_status": btc_status, "funding_status": funding.get("status", "") if isinstance(funding, dict) else ""})
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

        pre_breakout_ok, pre_breakout_data = pre_breakout_watch_signal(symbol, rs)
        if pre_breakout_data:
            pre_breakout_data = attach_market_impact(pre_breakout_data, item)
            update_money_memory(symbol, pre_breakout_data)

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
            (pre_breakout_ok, pre_breakout_data),
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
        for _sig in [early_data, money_data, momentum_data, safe_data, dip_data, sweep_data, fast_sweep_data, pre_rocket_data, pre_breakout_data, trend_data, history_data]:
            attach_oi_context(_sig, oi_context)
            attach_taker_flow_context(_sig, taker_context)
            attach_cvd_context(symbol, _sig)

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
        if pre_breakout_ok:
            signals.append(pre_breakout_data)
        if trend_ok:
            signals.append(trend_data)
        if history_ok:
            signals.append(history_data)

        radar_health_record({
            "Early": early_ok,
            "Money": money_ok,
            "Momentum": momentum_ok,
            "Safe": safe_ok,
            "Dip": dip_ok,
            "Sweep": sweep_ok,
            "FastSweep": fast_sweep_ok,
            "PreRocket": pre_rocket_ok,
            "PreBreakout": pre_breakout_ok,
            "Trend": trend_ok,
            "History": history_ok,
        })

        if signals:
            sent = send_selected_signal(symbol, signals, funding, btc_status)
            if sent:
                return
            explain_reject_summary(
                symbol, rs, funding["status"],
                {"SelectedSignal": True, "EliteOrGoldGate": False},
                money_state_present=(symbol in money_state),
                extra="Sinyal olustu ama kanal/Elite kapisi gecilmedi"
            )

        else:
            explain_reject_summary(
                symbol, rs, funding["status"],
                {
                    "Early": early_ok,
                    "Money": money_ok,
                    "Momentum": momentum_ok,
                    "Safe": safe_ok,
                    "Dip": dip_ok,
                    "Sweep": sweep_ok,
                    "FastSweep": fast_sweep_ok,
                    "PreRocket": pre_rocket_ok,
                    "PreBreakout": pre_breakout_ok,
                    "Trend": trend_ok,
                    "History": history_ok,
                },
                money_state_present=(symbol in money_state),
                extra="IC FILTRE"
            )

    except Exception as e:
        print("Analiz hata:", symbol, e, flush=True)

def run_bot():
    send_log(
        f"🟢 {BOT_NAME} BASLADI\n"
        f"Radar Manager aktif.\n"
        f"Ana Kanal: {CHAT_ID}\n"
        f"Hazirlik: {BINANCE_ELITE_PREP_CHAT_ID}\n"
        f"Gold: {BINANCE_ELITE_GOLD_CHAT_ID}\n"
        f"Performance: {BINANCE_PERFORMANCE_CHAT_ID}\n"
        f"Log: {BINANCE_LOG_CHAT_ID}\n"
        f"PIE: {PIE_DATA_FILE}\n"
        f"FullTracking: {FULL_TRACKING_DATA_FILE}\n"
        f"RadarHealth: {RADAR_HEALTH_FILE}"
    )
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
            pie_update_open_signals(BINANCE_PERFORMANCE_CHAT_ID)
            ft_update_open_records()
            pie_daily_report_if_due(BINANCE_PERFORMANCE_CHAT_ID, "BINANCE")
            performance_center_reports_if_due(BINANCE_PERFORMANCE_CHAT_ID, "BINANCE")

            universe = build_universe()
            print("Taranacak coin:", len(universe), "MoneyState:", len(money_state), flush=True)

            for item in universe:
                analyze(item, btc_ok, btc_status)
                time.sleep(0.20)

            print(f"Tur bitti. {SLEEP_SECONDS} saniye bekleniyor.", flush=True)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            print("Genel hata:", e, flush=True)
            send_log(f"🔴 Binance bot genel hata:\n{e}")
            time.sleep(30)


@app.route("/")
def home():
    return "BINANCE FUTURES V52 + AYRI PERFORMANCE/LOG KANALLARI Aktif", 200


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
