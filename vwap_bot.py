import os
import time
import requests
import datetime
from flask import Flask, jsonify
from threading import Thread

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
OANDA_API_KEY = os.getenv("OANDA_API_KEY")
TIMEZONE_OFFSET = int(os.getenv("TIMEZONE_OFFSET", 0))
PAIRS = ["GBP_USD", "EUR_USD", "XAU_USD"]
TIMEFRAME = "M15"

app = Flask(__name__)
last_signals = {}

def is_market_open():
    now = datetime.datetime.utcnow()
    return now.weekday() < 5

def fetch_candles(pair):
    url = f"https://api-fxpractice.oanda.com/v3/instruments/{pair}/candles"
    params = {"count": 100, "granularity": TIMEFRAME, "price": "M"}
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        print(f"Error fetching {pair}")
        return []
    return r.json().get("candles", [])

def calculate_vwap(candles):
    cum_pv = 0
    cum_vol = 0
    for c in candles:
        high = float(c["mid"]["h"])
        low = float(c["mid"]["l"])
        close = float(c["mid"]["c"])
        vol = float(c["volume"])
        typical_price = (high + low + close) / 3
        cum_pv += typical_price * vol
        cum_vol += vol
    return cum_pv / cum_vol if cum_vol else None

def detect_vwap_signal(candles):
    if len(candles) < 20:
        return None

    current = candles[-1]
    close = float(current["mid"]["c"])
    vwap = calculate_vwap(candles[:-1])
    body = abs(float(current["mid"]["c"]) - float(current["mid"]["o"]))
    wick = abs(float(current["mid"]["h"]) - float(current["mid"]["l"]))

    if not vwap:
        return None

    # Buy below VWAP + confirmation
    if close > vwap and body > wick * 0.5:
        entry = close
        tp = round(entry + (entry - vwap) * 2, 5)
        sl = round(vwap, 5)
        return {"type": "Buy", "entry": entry, "tp": tp, "sl": sl}
    # Sell above VWAP + confirmation
    elif close < vwap and body > wick * 0.5:
        entry = close
        tp = round(entry - (vwap - entry) * 2, 5)
        sl = round(vwap, 5)
        return {"type": "Sell", "entry": entry, "tp": tp, "sl": sl}
    return None

def send_discord(pair, signal):
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=TIMEZONE_OFFSET)
    chart = f"https://www.tradingview.com/chart/?symbol=OANDA:{pair.replace('_','')}"
    embed = {
        "title": f"{signal['type']} Signal on {pair}",
        "description": f"📍 **Entry**: `{signal['entry']}`\n🎯 **TP**: `{signal['tp']}`\n🛑 **SL**: `{signal['sl']}`\n\n[📈 Chart]({chart})",
        "color": 3066993 if signal["type"] == "Buy" else 15158332,
        "timestamp": now.isoformat()
    }
    res = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
    print("✅ Signal sent" if res.status_code == 204 else f"❌ Discord error: {res.text}")

def scan():
    while True:
        if not is_market_open():
            print("Market closed")
            time.sleep(300)
            continue
        print("📡 Scanning for VWAP signals...")
        for pair in PAIRS:
            candles = fetch_candles(pair)
            signal = detect_vwap_signal(candles)
            if signal:
                last_entry = last_signals.get(pair)
                if last_entry != signal["entry"]:
                    send_discord(pair, signal)
                    last_signals[pair] = signal["entry"]
                else:
                    print(f"No new signal for {pair}")
            else:
                print(f"No setup on {pair}")
        time.sleep(300)

@app.route('/')
def home():
    return jsonify({"status": "VWAP Bot is live"})

def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    scan()
