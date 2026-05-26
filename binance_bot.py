import time
import requests
from datetime import datetime

# TELEGRAM
TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
TELEGRAM_CHAT_ID = "6977265844"

# WEBSHARE PROXY
proxy_host = "38.154.203.95"
proxy_port = "5863"
proxy_user = "maxwemri"
proxy_pass = "ashvrfdkt6r5"

proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"

proxies = {
    "http": proxy_url,
    "https": proxy_url
}

BASE_URL = "https://fapi.binance.com"
SCAN_INTERVAL = 60


def telegram_send(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=15
        )
        print("Telegram cevap:", r.status_code)
    except Exception as e:
        print("Telegram hata:", e)


def binance_get(endpoint, params=None):
    try:
        url = BASE_URL + endpoint
        r = requests.get(
            url,
            params=params,
            proxies=proxies,
            timeout=20
        )

        print("Binance status:", r.status_code)

        data = r.json()

        if isinstance(data, dict):
            print("Binance cevap:", data)
            return None

        return data

    except Exception as e:
        print("Binance API hata:", e)
        telegram_send(f"⚠️ Binance veri hatası hocam:\n{e}")
        return None


def test_binance():
    data = binance_get("/fapi/v1/ticker/24hr")

    if isinstance(data, list):
        msg = f"✅ Binance proxy bağlantısı başarılı hocam.\nTaranan coin sayısı: {len(data)}"
        print(msg)
        telegram_send(msg)
        return True

    telegram_send("⚠️ Binance verisi gelmedi hocam. Proxy kullanıcı/şifre veya IP engeli devam ediyor.")
    return False


def main():
    telegram_send("🧪 TEST MESAJI: Binance Railway bot başladı hocam.")

    test_binance()

    while True:
        data = binance_get("/fapi/v1/ticker/24hr")

        if isinstance(data, list):
            usdt_symbols = [
                x for x in data
                if isinstance(x, dict)
                and x.get("symbol", "").endswith("USDT")
                and "USDC" not in x.get("symbol", "")
                and "BUSD" not in x.get("symbol", "")
            ]

            print("Taranan coin:", len(usdt_symbols), datetime.now())

            telegram_send(
                f"✅ Binance tarama çalışıyor hocam.\n"
                f"Taranan coin: {len(usdt_symbols)}\n"
                f"Saat: {datetime.now()}"
            )
        else:
            print("Binance verisi yok:", datetime.now())

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
