import sqlite3
import json
import requests
from datetime import datetime, timedelta

from agent.learner import update_weights
from delivery.telegram import send_telegram

print("✅ run_evaluation.py started", flush=True)


DB_PATH = "memory/daily_log.db"

STOOQ_CSV = "https://stooq.com/q/d/l/?s={symbol}&i=d"  # daily bars CSV

def get_last_unscored_day(conn):
    c = conn.cursor()
    c.execute("SELECT date, bias, signals FROM log WHERE outcome IS NULL ORDER BY date ASC LIMIT 1")
    return c.fetchone()

def fetch_stooq_open_close_return(symbol: str, date_iso: str):
    url = STOOQ_CSV.format(symbol=symbol.lower())
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        return None

    target = datetime.fromisoformat(date_iso).date()

    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        d = datetime.fromisoformat(parts[0]).date()
        if d == target:
            o = float(parts[1])
            c = float(parts[4])
            return (c - o) / o * 100.0

    return None

def judge_outcome(bias: str, spx_ret: float, ndx_ret: float) -> str:
    THRESH = 0.25

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

    spy_ret = fetch_stooq_open_close_return("SPY.US", date_iso)
    qqq_ret = fetch_stooq_open_close_return("QQQ.US", date_iso)

    if spy_ret is None or qqq_ret is None:
        outcome = "no_cash_session"
        c = conn.cursor()
        c.execute("""
            UPDATE log
            SET spx_close_return=?, ndx_close_return=?, outcome=?
            WHERE date=?
        """, (spy_ret, qqq_ret, outcome, date_iso))
        conn.commit()
        conn.close()

        msg = (
            f"ℹ️ Evaluation skipped\n\n"
            f"Date: {date_iso}\n"
            f"Reason: no SPY/QQQ cash-session bar available (holiday/weekend or data not posted yet)."
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

    











