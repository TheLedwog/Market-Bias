import sqlite3
import json
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os

from agent.learner import update_weights
from delivery.telegram import send_telegram

print("✅ run_evaluation.py started", flush=True)


DB_PATH = "memory/daily_log.db"

# After this many failed evaluation attempts, give up on a day and mark it
# "skipped" so it stops blocking newer days (the queue always processes the
# OLDEST unscored day, so one permanently-unfetchable day wedges everything
# behind it). Evaluation runs ~3x per weekday, so 6 ≈ two trading days.
MAX_EVAL_ATTEMPTS = 6

# Yahoo Finance daily-bars chart API (keyless). Stooq's CSV endpoint now
# requires an API key and returns a "Get your apikey" message instead of data.
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


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
      outcome TEXT,
      eval_attempts INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()
    
def get_last_unscored_day(conn):
    c = conn.cursor()
    c.execute("SELECT date, bias, signals FROM log WHERE outcome IS NULL ORDER BY date ASC LIMIT 1")
    return c.fetchone()

def fetch_open_close_return(symbol: str, date_iso: str):
    """Open->close % return for `symbol` on `date_iso`, via Yahoo Finance.

    Returns None if the day isn't present yet (e.g. data not posted) or the
    response can't be parsed.
    """
    url = YAHOO_CHART.format(symbol=symbol)
    r = requests.get(
        url,
        params={"range": "3mo", "interval": "1d"},
        headers=YAHOO_HEADERS,
        timeout=30,
    )
    r.raise_for_status()

    try:
        result = r.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        opens = quote["open"]
        closes = quote["close"]
    except (KeyError, IndexError, TypeError):
        return None

    target = datetime.fromisoformat(date_iso).date()

    for ts, o, c in zip(timestamps, opens, closes):
        # Daily bars are timestamped at the exchange open; for US markets that
        # always falls on the same calendar day in UTC.
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if d == target and o and c:
            return (c - o) / o * 100.0

    return None

def judge_outcome(bias: str, spx_ret: float, ndx_ret: float) -> str:
    THRESH = 0.15

    def direction(x: float) -> str:
        if x > THRESH:
            return "bullish"
        if x < -THRESH:
            return "bearish"
        return "flat"

    spx_dir = direction(spx_ret)
    ndx_dir = direction(ndx_ret)

    if spx_dir == "flat" and ndx_dir == "flat":
        return "no_signal"

    if bias == "bullish" and spx_dir == "bullish" and ndx_dir == "bullish":
        return "correct"
    if bias == "bearish" and spx_dir == "bearish" and ndx_dir == "bearish":
        return "correct"

    return "incorrect"

def main():
    print("✅ run_evaluation.py started", flush=True)
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = get_last_unscored_day(conn)

    if not row:
        msg = "ℹ️ Evaluation complete\nNo unscored days found."
        print(msg)
        send_telegram(msg)
        conn.close()
        return

    date_iso, bias_raw, signals_json = row
    bias = (bias_raw or "").strip().lower()

    analysis = json.loads(signals_json)
    signals = analysis.get("signals", {})

    spy_ret = fetch_open_close_return("SPY", date_iso)
    qqq_ret = fetch_open_close_return("QQQ", date_iso)

    if spy_ret is None or qqq_ret is None:
        c = conn.cursor()

        # Get current attempts
        c.execute("SELECT eval_attempts FROM log WHERE date=?", (date_iso,))
        row_attempts = c.fetchone()
        attempts = row_attempts[0] if row_attempts and row_attempts[0] is not None else 0

        attempts += 1

        if attempts < MAX_EVAL_ATTEMPTS:
            # Still retrying: bump the counter and leave the day unscored.
            c.execute("UPDATE log SET eval_attempts=? WHERE date=?", (attempts, date_iso))
            conn.commit()
            conn.close()
            msg = (
                f"ℹ️ Evaluation delayed\n\n"
                f"Date: {date_iso}\n"
                f"Attempt: {attempts}/{MAX_EVAL_ATTEMPTS}\n"
                f"Reason: SPY/QQQ data not available yet.\n"
                f"Will retry automatically."
            )
        else:
            # Give up: mark the day "skipped" so it stops blocking the queue.
            # Skipped days never update weights (only correct/incorrect do).
            c.execute(
                "UPDATE log SET eval_attempts=?, outcome='skipped' WHERE date=?",
                (attempts, date_iso),
            )
            conn.commit()
            conn.close()
            msg = (
                f"🚨 Evaluation SKIPPED after retries\n\n"
                f"Date: {date_iso}\n"
                f"Attempts: {attempts}\n\n"
                f"SPY/QQQ data still unavailable (likely too old to fetch).\n"
                f"Marked as skipped so newer days can be evaluated."
            )

        print(msg)
        send_telegram(msg)
        return

    spx_ret = spy_ret
    ndx_ret = qqq_ret

    outcome = judge_outcome(bias, spx_ret, ndx_ret)

    c = conn.cursor()
    c.execute("""
        UPDATE log
        SET spx_close_return=?, ndx_close_return=?, outcome=?
        WHERE date=?
    """, (spx_ret, ndx_ret, outcome, date_iso))
    conn.commit()
    conn.close()

    if outcome in ("correct", "incorrect"):
        update_weights(signals, correct=(outcome == "correct"))
        
        c.execute("""
            UPDATE log
            SET eval_attempts=0
            WHERE date=?
        """, (date_iso,))
        conn.commit()

    msg = (
        f"✅ Evaluation (NY cash proxy)\n\n"
        f"Date: {date_iso}\n"
        f"Bias: {bias}\n"
        f"Outcome: {outcome}\n\n"
        f"SPY (O->C): {spx_ret:.2f}%\n"
        f"QQQ (O->C): {ndx_ret:.2f}%"
    )
    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    main()

    












