import os
import requests
import uuid
from flask import Flask, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TRANSAK_API_KEY = os.getenv("TRANSAK_API_KEY")
TRANSAK_API_SECRET = os.getenv("TRANSAK_API_SECRET")
TRANSAK_ENV = os.getenv("TRANSAK_ENV", "STAGING")

if TRANSAK_ENV == "PRODUCTION":
    API_BASE = "https://api.transak.com"
else:
    API_BASE = "https://api-stg.transak.com"

def get_partner_token():
    url = f"{API_BASE}/api/v2/partner/api-keys/token"
    payload = {"apiKey": TRANSAK_API_KEY, "apiSecret": TRANSAK_API_SECRET}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json().get("accessToken")

@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout():
    data = request.json
    wallet = data.get('walletAddress')
    fiat_amount = data.get('fiatAmount', 10000)
    fiat_currency = data.get('fiatCurrency', 'MXN')
    try:
        token = get_partner_token()
        widget_params = {
            "apiKey": TRANSAK_API_KEY,
            "cryptoCurrencyCode": "USDT",
            "network": "polygon",
            "fiatCurrency": fiat_currency,
            "fiatAmount": fiat_amount,
            "walletAddress": wallet,
            "isAmountInFiat": True,
            "hideExchangeScreen": True,
            "partnerOrderId": str(uuid.uuid4()),
            "userData": {"email": f"user_{uuid.uuid4().hex[:8]}@avalon.fund"}
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        resp = requests.post(f"{API_BASE}/api/v2/auth/session", json={"widgetParams": widget_params}, headers=headers)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "timestamp": datetime.now().isoformat()}), 200

if __name__ == "__main__":
    # Esto solo se ejecuta localmente, Render usará gunicorn
    app.run(host='0.0.0.0', port=8080)
