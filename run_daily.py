import os
import sqlite3
import json
import requests
from datetime import datetime, timezone

from agent.signal_extractor import extract_signals
from agent.bias_engine import load_weights, score_signals, bias_from_score
from agent.polymarket import get_spx_up_down_probs_for_today
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
    """, (date_iso, bias, confidence, json.dumps(analysis), score, None, None, None))
    conn.commit()
    conn.close()


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def contribution_breakdown(signals: dict, weights: dict):
    rows = []
    for k, v in (signals or {}).items():
        w = float(weights.get(k, 0.0))
        vv = (v or "").strip().lower()
        if vv == "bullish":
            rows.append((k, +w))
        elif vv == "bearish":
            rows.append((k, -w))
        else:
            rows.append((k, 0.0))
    # sort by absolute impact
    rows.sort(key=lambda x: abs(x[1]), reverse=True)
    return rows[:5]

def main():
    init_db()
    date_iso = datetime.now(timezone.utc).date().isoformat()

    # 1) Fetch news and extract AI signals + briefing
    news = fetch_news()
    analysis = extract_signals(news)
    ####################debug#########
    analysis["debug"]["signal_counts"] = {
    "bullish": sum(1 for v in analysis.get("signals", {}).values() if str(v).lower() == "bullish"),
    "bearish": sum(1 for v in analysis.get("signals", {}).values() if str(v).lower() == "bearish"),
    "neutral": sum(1 for v in analysis.get("signals", {}).values() if str(v).lower() == "neutral"),
    }
    ###################################
    analysis.setdefault("signals", {})
    analysis.setdefault("drivers", [])
    analysis.setdefault("key_risk", "")
    
    

    # 2) Base score from your discrete AI signals + weights
    weights = load_weights(WEIGHTS_PATH)
    score_base = score_signals(analysis["signals"], weights)

    ###########debug#############
    top = contribution_breakdown(analysis["signals"], weights)
    analysis["debug"]["top_contrib"] = top
    #############################

    
    # 3) Polymarket numeric boost (crowd tilt)
    pm_boost = 0.0
    pm = get_spx_up_down_probs_for_today()

    if pm and "up" in pm and "down" in pm:
        p_up = float(pm["up"])
        p_down = float(pm["down"])

        # Convert probability to a centered tilt:
        # 50% => 0.0, 95% => +0.9, 5% => -0.9
        tilt = (p_up - 0.5) * 2.0  # [-1, +1]

        # Weight/cap so it can't completely dominate everything
        PM_WEIGHT = 1.0           # tune: 0.5–1.5 typical
        PM_CAP = 1.0              # max absolute boost
        pm_boost = clamp(tilt * PM_WEIGHT, -PM_CAP, PM_CAP)

        analysis["polymarket"] = {
            "spx_up_prob": round(p_up, 3),
            "spx_down_prob": round(p_down, 3),
            "tilt": round(tilt, 3),
            "score_boost": round(pm_boost, 3),
            "event_title": pm.get("title", ""),
            "event_slug": pm.get("event_slug", ""),
        }
    else:
        analysis["polymarket"] = {
            "note": "Polymarket SPX market not found or API unavailable.",
            "score_boost": 0.0
        }

    # 4) Final score = base + polymarket boost
    score = score_base + pm_boost

    # 5) Convert score -> bias + confidence
    bias, confidence = bias_from_score(score)

    # 6) Persist decision
    log_decision(date_iso, bias, confidence, analysis, score)

    # 7) Telegram message
    drivers = analysis.get("drivers") or []
    drivers_txt = "\n".join([f"• {d}" for d in drivers[:5]]) if drivers else "• (none)"

    if pm and "up" in pm and "down" in pm:
        pm_line = (
            f"Polymarket SPX: Up {pm['up']*100:.1f}% / Down {pm['down']*100:.1f}%\n"
            f"Polymarket boost: {pm_boost:+.2f}"
        )
    else:
        pm_line = "Polymarket SPX: unavailable\nPolymarket boost: +0.00"

    msg = (
        "📊 US Futures Bias\n\n"
        f"Bias: {bias} | Confidence: {confidence:.1f}%\n"
        f"Score: {score:.2f} (base {score_base:.2f} + pm {pm_boost:+.2f})\n"
        f"{pm_line}\n\n"
        "Drivers:\n"
        f"{drivers_txt}\n\n"
        f"Key risk: {analysis.get('key_risk','')}"
    )

    print(msg, flush=True)
    send_telegram(msg)


if __name__ == "__main__":
    main()



