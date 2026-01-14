import os
import requests
import json
import sqlite3
from datetime import datetime, timezone
from agent.signal_extractor import extract_analysis
from agent.bias_engine import compute_bias
from dotenv import load_dotenv
from delivery.telegram import send_telegram

load_dotenv()


NEWS_API_KEY = os.getenv("NEWS_API_KEY")

def fetch_news():
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": '(S&P OR Nasdaq OR "stock market" OR futures OR "Federal Reserve" OR CPI OR inflation OR yields OR treasury)',
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 25,
        "apiKey": NEWS_API_KEY
    }

    r = requests.get(url, params=params)
    data = r.json()

    if data.get("status") != "ok":
        print("⚠️ News API error:", data)
        return "No major market-moving news detected."

    headlines = [a.get("title", "") for a in data.get("articles", []) if a.get("title")]
    if not headlines:
        return "No major market-moving news detected."

    return " | ".join(headlines)



def log_decision(bias, confidence, signals, score):
    conn = sqlite3.connect("memory/daily_log.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS log (
        date TEXT PRIMARY KEY,
        bias TEXT,
        confidence REAL,
        signals TEXT,
        score REAL,
        spx_close_return REAL,
        ndx_close_return REAL,
        outcome TEXT
    )
    """)

    c.execute("""
    INSERT OR REPLACE INTO log
    (date, bias, confidence, signals, score, spx_close_return, ndx_close_return, outcome)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).date().isoformat(),
        bias,
        confidence,
        json.dumps(analysis),
        score,
        None,
        None,
        None
    ))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    news = fetch_news()
    
    analysis = extract_analysis(news)
    signals = analysis["signals"]

    bias, confidence, score = compute_bias(signals)


    log_decision(bias, confidence, signals, score)

    print(f"Bias: {bias} | Confidence: {confidence}%")
    
    tilt_es = analysis["index_tilt"]["ES"]
    tilt_nq = analysis["index_tilt"]["NQ"]
    drivers = analysis["drivers"]
    key_risk = analysis["key_risk"]

    msg = (
        f"📊 US Futures Bias\n\n"
        f"Bias: {bias} | Confidence: {confidence}%\n"
        f"ES tilt: {tilt_es} | NQ tilt: {tilt_nq}\n\n"
        f"Drivers:\n"
        f"• {drivers[0]}\n"
        f"• {drivers[1]}\n"
        f"• {drivers[2]}\n\n"
        f"Key risk: {key_risk}"
    )
    send_telegram(msg)
