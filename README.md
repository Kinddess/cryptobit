# CryptoBit Pro – Live Crypto Tracker & Signal Dashboard

A **beautiful, real-time cryptocurrency price tracker** with professional-grade technical analysis:  
**Bollinger Bands • RSI • MACD • EMA 12/26 • Multi-timeframe signals • Fear & Greed Index**

Live demo feel: instant price updates, glowing signals, flashing price changes, and a sleek dark pro interface.

### Features
- Live prices for BTC, ETH, SOL, TON, BNB (CoinGecko)
- Real-time 1-minute chart with:
  - Bollinger Bands (20, 2)
  - EMA 12 & EMA 26
  - RSI (14) panel
  - MACD panel with histogram
- Smart multi-timeframe signal engine (custom scoring)
- Confidence % and key trigger reasons
- Live Fear & Greed Index integration
- Fully responsive – works perfectly on mobile & desktop
- No login, no ads, no tracking – just pure crypto

### Tech Stack
- Backend: **Python + Flask**
- Frontend: **HTML + Bootstrap 5 + Chart.js**
- Data: **CoinGecko API** (free) + Alternative.me F&G

### How to Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/yourname/cryptobit-pro.git
cd cryptobit-pro

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate    # Linux/Mac
# or
venv\Scripts\activate       # Windows

# 3. Install requirements
pip install flask requests pandas numpy

# 4. Run the app
python app.py
```

Open your browser → http://127.0.0.1:5000

### Project Structure
```
├── app.py                  # Main Flask backend + signal engine
├── templates/
│   └── index.html          # Gorgeous frontend with RSI + MACD + BB
└── README.md               # This file
```

### Disclaimer
This is an **educational/entertainment tool**.  
Signals are based on technical indicators and sentiment — **not financial advice**.  
Always do your own research and never risk more than you can afford to lose.

### Credits
Built with love by kinddess 
Powered by CoinGecko & Alternative.me APIs  
Design inspired by professional trading terminals

Enjoy the alpha!  
Made for crypto degens, by a crypto degen.
