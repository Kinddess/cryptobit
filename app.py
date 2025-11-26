# app.py - Enhanced CryptoBit Live Tracker
from flask import Flask, render_template, jsonify
import threading
import time
import datetime
import json
import numpy as np
import requests
import pandas as pd
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIG ====================
CHECK_INTERVAL = 15  # seconds
MAX_POINTS_1M = 600  # 10 hours of 1m data
MAX_POINTS_5M = 288  # 24h of 5m
MAX_POINTS_15M = 200
MAX_POINTS_1H = 168  # 7 days
COINS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'TON': 'toncoin',
    'BNB': 'binancecoin'
}


@dataclass
class CoinData:
    symbol: str
    prices_1m: deque = None
    times_1m: deque = None
    volumes_1m: deque = None

    def __post_init__(self):
        self.prices_1m = deque(maxlen=MAX_POINTS_1M)
        self.times_1m = deque(maxlen=MAX_POINTS_1M)
        self.volumes_1m = deque(maxlen=MAX_POINTS_1M)

        # Higher timeframes (resampled properly)
        self.prices_5m = deque(maxlen=MAX_POINTS_5M)
        self.prices_15m = deque(maxlen=MAX_POINTS_15M)
        self.prices_1h = deque(maxlen=MAX_POINTS_1H)
        self.times_5m = deque(maxlen=MAX_POINTS_5M)
        self.times_15m = deque(maxlen=MAX_POINTS_15M)
        self.times_1h = deque(maxlen=MAX_POINTS_1H)

    def append_1m(self, price: float, volume: float):
        now = datetime.datetime.now()
        self.prices_1m.append(price)
        self.times_1m.append(now)
        self.volumes_1m.append(volume)

        # Proper time-based resampling
        minutes = now.minute
        if len(self.prices_1m) >= 5 and minutes % 5 == 0 and (
                len(self.prices_5m) == 0 or self.times_5m[-1].minute != minutes):
            self.prices_5m.append(price)
            self.times_5m.append(now)
        if minutes % 15 == 0 and (len(self.prices_15m) == 0 or self.times_15m[-1].minute != minutes):
            self.prices_15m.append(price)
            self.times_15m.append(now)
        if now.hour % 1 == 0 and minutes < 5 and (len(self.prices_1h) == 0 or self.times_1h[-1].hour != now.hour):
            self.prices_1h.append(price)
            self.times_1h.append(now)


# Global state (thread-safe with lock)
data_store = {coin: CoinData(coin) for coin in COINS}
latest_response = {}
data_lock = threading.Lock()


def get_prices_safe():
    ids = ','.join(COINS.values())
    try:
        headers = {'User-Agent': 'CryptoBitTracker/1.0'}
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": ids, "price_change_percentage": "24h"},
            headers=headers,
            timeout=10
        )
        if r.status_code == 429:
            logger.warning("Rate limited by CoinGecko")
            time.sleep(60)
            return {}, {}
        return {item['symbol'].upper(): (item['current_price'], item.get('price_change_percentage_24h', 0),
                                         item.get('total_volume', 0))
                for item in r.json() if item['symbol'].upper() in COINS}
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return {}


def get_fear_greed_safe():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        return int(r.json()["data"][0]["value"])
    except:
        return 50


# Fixed RSI (Standard Welles Wilder formula)
def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    up = deltas[-period:]
    down = -deltas[-period:]
    up = np.append([0], up[up > 0])
    down = np.append([0], down[down > 0])

    if len(up) <= 1 or len(down) <= 1:
        return 50.0

    avg_gain = np.mean(up[up > 0]) if np.any(up > 0) else 0
    avg_loss = np.mean(down[down > 0]) if np.any(down > 0) else 0.000001

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def ema_series(prices: List[float], span: int):
    if not prices:
        return []
    return pd.Series(prices).ewm(span=span, adjust=False).mean().tolist()


def generate_signal(coin_data: CoinData):
    p1m = list(coin_data.prices_1m)
    p5m = list(coin_data.prices_5m)
    p15m = list(coin_data.prices_15m)
    p1h = list(coin_data.prices_1h)
    vol = list(coin_data.volumes_1m)

    if len(p1m) < 100:
        return "Warming Up", 0, "text-secondary", []

    score = 0
    reasons = []

    # RSI Multi-timeframe
    rsi1 = calculate_rsi(p1m, 14)
    rsi5 = calculate_rsi(p5m, 14) if len(p5m) >= 20 else rsi1
    rsi15 = calculate_rsi(p15m, 14) if len(p15m) >= 20 else rsi1
    rsi60 = calculate_rsi(p1h, 14) if len(p1h) >= 20 else rsi1

    if rsi1 < 25:
        score += 25; reasons.append("1m Extreme Oversold")
    elif rsi1 < 30:
        score += 18; reasons.append("1m Oversold")
    if rsi1 > 75: score -= 22; reasons.append("1m Overbought")
    if rsi60 < 40: score += 15; reasons.append("1h Bullish Structure")

    # EMA Trend
    if len(p1m) >= 50:
        ema12 = ema_series(p1m, 12)
        ema26 = ema_series(p1m, 26)
        if ema12 and ema26 and ema12[-1] > ema26[-1]:
            score += 20
            reasons.append("EMA Bullish")
        else:
            score -= 20
            reasons.append("EMA Bearish")

    # Volume Surge
    if len(vol) >= 20:
        recent_vol = np.mean(vol[-10:])
        prev_vol = np.mean(vol[-20:-10])
        if recent_vol > prev_vol * 1.8:
            price_change = (p1m[-1] - p1m[-10]) / p1m[-10]
            if price_change > 0.01:
                score += 18;
                reasons.append("Volume Surge Up")
            elif price_change < -0.01:
                score -= 20;
                reasons.append("Distribution Risk")

    # Fear & Greed Boost
    fg = get_fear_greed_safe()
    if fg < 20:
        score += 30; reasons.append(f"Extreme Fear ({fg})")
    elif fg > 80:
        score -= 20; reasons.append(f"Extreme Greed ({fg})")

    prob = min(98, max(10, abs(score)))

    if score >= 60:
        return "STRONG BUY", prob, "text-success fw-bold", reasons[:3]
    elif score >= 30:
        return "BUY", prob, "text-info", reasons[:3]
    elif score <= -60:
        return "STRONG SELL", prob, "text-danger fw-bold", reasons[:3]
    elif score <= -30:
        return "SELL", prob, "text-warning", reasons[:3]
    else:
        return "NEUTRAL", 30, "text-muted", reasons[:2]


def background_updater():
    while True:
        start_time = time.time()
        prices_data = get_prices_safe()
        fg_index = get_fear_greed_safe()

        dashboard = []
        chart_data = {}

        for symbol, coin_data in data_store.items():
            if symbol not in prices_data:
                continue
            price, change_24h, volume = prices_data[symbol]
            coin_data.append_1m(price, volume)

            signal, prob, color, reasons = generate_signal(coin_data)

            dashboard.append({
                "coin": symbol,
                "price": round(price, 6),
                "change": round(change_24h, 2),
                "signal": signal,
                "prob": prob,
                "color_class": color,
                "reasons": " • ".join(reasons) if reasons else "Analyzing..."
            })

            # Chart data (last 150 points)
            prices = list(coin_data.prices_1m)[-150:]
            if len(prices) > 26:
                ema_fast = ema_series(prices, 12)
                ema_slow = ema_series(prices, 26)
            else:
                ema_fast = ema_slow = []

            chart_data[symbol] = {
                "labels": list(range(len(prices))),
                "prices": prices,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow
            }

        response = {
            "dashboard": dashboard,
            "chart_data": chart_data,
            "fg": fg_index,
            "timestamp": datetime.datetime.now().isoformat()
        }

        with data_lock:
            global latest_response
            latest_response = response

        elapsed = time.time() - start_time
        sleep_time = max(0, CHECK_INTERVAL - elapsed)
        time.sleep(sleep_time)


# Start background thread
threading.Thread(target=background_updater, daemon=True).start()


@app.route('/')
def index():
    return render_template('index.html', coins=list(COINS.keys()))


@app.route('/api/data')
def api_data():
    with data_lock:
        return jsonify(latest_response or {"dashboard": [], "fg": 50, "timestamp": None})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)