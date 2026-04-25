from flask import Flask, request
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = "8637824602:AAG8V2VJ3QM0WI40PUpu1zbT-67qCpWgbOQ"
CHAT_ID = "6977265844"

  
@app.route('/', methods=['POST'])
def webhook():
    data =request.get_json(silent=True) or request.data.decode("utf-8") or "TradingView alarmı geldi"  
    message = f"ALARM GELDİ 🚨\n\n{data}"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message
    })
    
    return "ok"

app.run(host='0.0.0.0', port=10000)
