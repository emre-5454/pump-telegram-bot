from flask import Flask, request
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"


@app.route('/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return "OK", 200
data = request.get_json(silent=True)

if data:
    coin = data.get("coin", "Bilinmiyor")
    price = data.get("price", "Yok")

    message = f"🚨 ALARM GELDİ\n\nCoin: {coin}\nFiyat: {price}"
else:
    message = "🚨 TradingView alarmı geldi (veri boş)"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message
    })
    
    return "ok"

app.run(host='0.0.0.0', port=10000)
