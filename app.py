# app.py - Flask backend for CryptoBit Coin Price Tracker

from flask import Flask, render_template, jsonify
import os
import time
import datetime
import json
import numpy as np
import requests
import pandas as pd
import threading  # For background data update
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

app = Flask(__name__)

# ==================== CONFIG ====================
CHECK_INTERVAL = 15  # seconds
SAVE_LOGS = True

# Coins to track
COINS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'TON': 'toncoin',
    'BNB': 'binancecoin'
}

data = {coin: {'prices_1m': [], 'times_1m': [], 'prices_5m': [], 'times_5m': [],
               'prices_15m': [], 'times_15m': [], 'prices_1h': [], 'times_1h': [],
               'volumes_1m': [],  # For volume history
               'last_signal': "", 'score': 0} for coin in COINS}

latest_data = {}  # To store latest fetched data for API

def get_prices():
    ids = ','.join(COINS.values())
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}",
            timeout=10
        )
        data_json = r.json()
        prices = {}
        changes = {}
        volumes = {}
        for item in data_json:
            symbol = item['symbol'].upper()
            if symbol in COINS:
                prices[symbol] = item.get('current_price')
                changes[symbol] = item.get('price_change_percentage_24h', 0)
                volumes[symbol] = item.get('total_volume', 0)
        return prices, changes, volumes
    except:
        return {}, {}, {}

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=8)
        return int(r.json()["data"][0]["value"])
    except:
        return 50

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = np.diff(prices)
    gains = deltas[-period:]
    losses = -deltas[-period:]
    gain = np.mean(gains[gains > 0]) if np.any(gains > 0) else 0
    loss = np.mean(losses[losses > 0]) if np.any(losses > 0) else 0.001
    if loss == 0: return 100
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def ema(prices, period):
    if len(prices) == 0: return 0
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

def predict_signal(coin_data):
    score = 0
    reasons = []

    prices_1m = coin_data['prices_1m']
    prices_5m = coin_data['prices_5m']
    prices_15m = coin_data['prices_15m']
    prices_1h = coin_data['prices_1h']
    volumes_1m = coin_data['volumes_1m']

    if len(prices_1m) < 60:
        return "Collecting data...", 0, "text-warning", []  # Bootstrap yellow

    # Multi-timeframe RSI
    rsi_1m = rsi(prices_1m)
    rsi_5m = rsi(prices_5m) if len(prices_5m) > 14 else rsi_1m
    rsi_15m = rsi(prices_15m) if len(prices_15m) > 14 else rsi_1m
    rsi_1h = rsi(prices_1h) if len(prices_1h) > 14 else rsi_1m

    if rsi_1m < 27: score += 20; reasons.append("1m RSI Oversold")
    if rsi_1m > 73: score -= 18; reasons.append("1m RSI Overbought")
    if rsi_5m < 30: score += 15; reasons.append("5m RSI Support")
    if rsi_15m < 35: score += 12; reasons.append("15m RSI Bullish")
    if rsi_1h < 40: score += 10; reasons.append("1h RSI Strong Buy Zone")
    if rsi_1h > 70: score -= 15; reasons.append("1h RSI Overbought")

    # Multi-timeframe EMA
    try:
        ema12_1m = ema(prices_1m, 12)
        ema26_1m = ema(prices_1m, 26)
        ema12_15m = ema(prices_15m, 12) if len(prices_15m) > 26 else ema12_1m
        ema26_15m = ema(prices_15m, 26) if len(prices_15m) > 26 else ema26_1m

        if ema12_1m > ema26_1m: score += 18; reasons.append("1m Golden Cross")
        else: score -= 18; reasons.append("1m Death Cross")
        if ema12_15m > ema26_15m: score += 14; reasons.append("15m Bull Trend")
    except: pass

    # Momentum across frames
    if len(prices_1m) >= 12:
        mom_1m = (prices_1m[-1] / prices_1m[-12] - 1) * 100
        if mom_1m > 3.5: score -= 25; reasons.append("1m Pump Risk")
        if mom_1m < -3.5: score += 20; reasons.append("1m Bounce Likely")

    if len(prices_15m) >= 4:
        mom_15m = (prices_15m[-1] / prices_15m[-4] - 1) * 100
        if mom_15m > 5: score -= 20; reasons.append("15m Overextended")
        if mom_15m < -5: score += 15; reasons.append("15m Oversold")

    # Volume analysis
    if len(volumes_1m) >= 10:
        avg_volume = np.mean(volumes_1m[-10:-1])
        current_volume = volumes_1m[-1]
        volume_change = (current_volume - avg_volume) / avg_volume if avg_volume > 0 else 0
        price_change_short = (prices_1m[-1] - prices_1m[-5]) / prices_1m[-5] if len(prices_1m) >= 5 else 0
        if volume_change > 0.2 and price_change_short > 0:
            score += 15; reasons.append("Rising Volume + Price")
        elif volume_change > 0.2 and price_change_short < 0:
            score -= 15; reasons.append("Rising Volume + Dump")

    fg = get_fear_greed()
    if fg < 20: score += 30; reasons.append("Market Extreme Fear")
    if fg > 90: score -= 25; reasons.append("Market Extreme Greed")

    prob = min(99, abs(score))
    if score >= 65:
        return "STRONG BUY", prob, "text-success", reasons  # Green
    elif score >= 35:
        return "Bullish", prob, "text-info", reasons  # Cyan
    elif score <= -65:
        return "STRONG SELL", prob, "text-danger", reasons  # Red
    elif score <= -35:
        return "Bearish", prob, "text-purple", reasons  # Magenta
    else:
        return "Neutral", 25, "text-warning", reasons  # Yellow

def update_data():
    while True:
        prices, changes, volumes = get_prices()
        fg = get_fear_greed()
        dashboard = []
        charts = {}
        for coin in COINS:
            price = prices.get(coin)
            if price is None:
                continue

            volume = volumes.get(coin, 0)
            coin_data = data[coin]
            coin_data['prices_1m'].append(price)
            coin_data['times_1m'].append(datetime.datetime.now().isoformat())
            coin_data['volumes_1m'].append(volume)
            if len(coin_data['prices_1m']) > 500:
                coin_data['prices_1m'].pop(0)
                coin_data['times_1m'].pop(0)
                coin_data['volumes_1m'].pop(0)

            # Resample
            if len(coin_data['prices_1m']) % 5 == 0:
                coin_data['prices_5m'].append(price)
                coin_data['times_5m'].append(datetime.datetime.now().isoformat())
                if len(coin_data['prices_5m']) > 200:
                    coin_data['prices_5m'].pop(0)
                    coin_data['times_5m'].pop(0)
            if len(coin_data['prices_1m']) % 15 == 0:
                coin_data['prices_15m'].append(price)
                coin_data['times_15m'].append(datetime.datetime.now().isoformat())
                if len(coin_data['prices_15m']) > 100:
                    coin_data['prices_15m'].pop(0)
                    coin_data['times_15m'].pop(0)
            if len(coin_data['prices_1m']) % 60 == 0:
                coin_data['prices_1h'].append(price)
                coin_data['times_1h'].append(datetime.datetime.now().isoformat())
                if len(coin_data['prices_1h']) > 50:
                    coin_data['prices_1h'].pop(0)
                    coin_data['times_1h'].pop(0)

            msg, prob, color_class, reasons = predict_signal(coin_data)

            dashboard.append({
                'coin': coin,
                'price': price,
                'change': changes[coin],
                'signal': msg,
                'prob': prob,
                'color_class': color_class,
                'reasons': ', '.join(reasons[:2])
            })

            # Generate chart as base64
            fig, ax = plt.subplots(figsize=(10, 5))
            fig.patch.set_facecolor('#0d1117')
            ax.set_facecolor('#0d1117')
            ax.plot(range(len(coin_data['prices_1m'])), coin_data['prices_1m'], '#00ff88', lw=2.5)
            if len(coin_data['prices_1m']) > 30:
                ax.plot(range(len(coin_data['prices_1m'])), pd.Series(coin_data['prices_1m']).ewm(span=12).mean(), '#ffaa00', alpha=0.8)
                ax.plot(range(len(coin_data['prices_1m'])), pd.Series(coin_data['prices_1m']).ewm(span=26).mean(), '#ff00ff', alpha=0.8)
            ax.set_title(f"{coin} • ${price:,.0f if price else 'N/A'}", color='white')
            ax.tick_params(colors='white')
            ax.grid(True, alpha=0.2)
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=200, facecolor='#0d1117')
            buf.seek(0)
            charts[coin] = base64.b64encode(buf.getvalue()).decode('utf-8')
            plt.close(fig)

        latest_data['dashboard'] = dashboard
        latest_data['fg'] = fg
        latest_data['charts'] = charts
        latest_data['timestamp'] = datetime.datetime.now().isoformat()

        if SAVE_LOGS:
            with open("multi_coin_log.json", "a") as f:
                json.dump(latest_data, f)
                f.write("\n")

        time.sleep(CHECK_INTERVAL)

# Start background thread for data update
threading.Thread(target=update_data, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html', coins=list(COINS.keys()))

@app.route('/api/data')
def api_data():
    return jsonify(latest_data)

if __name__ == '__main__':
    app.run(debug=True)