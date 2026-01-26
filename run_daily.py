import os
import sqlite3
import requests
from datetime import datetime, timezone

from agent.signal_extractor import extract_signals
from agent.bias_engine import load_weights, score_signals, bias_from_score
from agent.polymarket import find_spx_up_down_probs_for_today
from delivery.telegram import send_telegram

DB_PATH = "memory/daily_log.db"
WEIGHTS_PATH = "config/signal_weights.json"

NEWS_API_KEY = os.getenv("NEWS_API_KEY")

def init_db():
    os.makedirs("memory", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()

def fetch_news() -> str:
    if not NEWS_API_KEY:
        return "NEWS_API_KEY not set. No news fetched."

    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "country": "us",
        "category": "business",
        "pageSize": 15,
        "apiKey": NEWS_API_KEY,
    }
    r = requests.get(url, params=params, timeout=25)
    data = r.json()

    if data.get("status") != "ok":
        return f"News API error: {data}"

    titles = [a.get("title", "") for a in data.get("articles", [])]
    titles = [t for t in titles if t]
    return " | ".join(titles) if titles else "No headlines returned."

def log_decision(date_iso: str, bias: str, confidence: float, analysis: dict, score: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
      INSERT OR REPLACE INTO log (date, bias, confidence, signals, score, spx_close_return, ndx_close_return, outcome)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (date_iso, bias, confidence, __import__("json").dumps(analysis), score, None, None, None))
    conn.commit()
    conn.close()

def main():
    init_db()
    date_iso = datetime.now(timezone.utc).date().isoformat()

    news = fetch_news()
    analysis = extract_signals(news)
    analysis.setdefault("signals", {})
    analysis.setdefault("drivers", [])
    analysis.setdefault("key_risk", "")

    # --- Polymarket SPX up/down signal ---
    pm = find_spx_up_down_probs_for_today()
    if pm:
        p_up = pm["up"]
        p_down = pm["down"]

        # Convert probability -> signal
        if p_up >= 0.60:
            analysis["signals"]["polymarket_spx"] = "bullish"
        elif p_down >= 0.60:
            analysis["signals"]["polymarket_spx"] = "bearish"
        else:
            analysis["signals"]["polymarket_spx"] = "neutral"

        analysis["polymarket"] = {
            "spx_up_prob": round(p_up, 3),
            "spx_down_prob": round(p_down, 3),
            "event_title": pm.get("title", ""),
            "event_slug": pm.get("event_slug", "")
        }
    else:
        analysis["signals"]["polymarket_spx"] = "neutral"
        analysis["polymarket"] = {"note": "Polymarket SPX market not found or API unavailable."}

    weights = load_weights(WEIGHTS_PATH)
    score = score_signals(analysis["signals"], weights)
    bias, confidence = bias_from_score(score)

    log_decision(date_iso, bias, confidence, analysis, score)

    # Telegram message
    pm_line = ""
    if pm:
        pm_line = f"\nPolymarket SPX: Up {pm['up']*100:.1f}% / Down {pm['down']*100:.1f}%"
    else:
        pm_line = "\nPolymarket SPX: unavailable"

    drivers = analysis.get("drivers") or []
    drivers_txt = "\n".join([f"• {d}" for d in drivers[:5]]) if drivers else "• (none)"

    msg = (
        "📊 US Futures Bias\n\n"
        f"Bias: {bias} | Confidence: {confidence:.1f}%\n"
        f"Score: {score:.2f}"
        f"{pm_line}\n\n"
        "Drivers:\n"
        f"{drivers_txt}\n\n"
        f"Key risk: {analysis.get('key_risk','')}"
    )
    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    main()
