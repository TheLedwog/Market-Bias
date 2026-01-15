import sqlite3
import json
import requests
from datetime import datetime, timedelta

from agent.learner import update_weights
from delivery.telegram import send_telegram



DB_PATH = "memory/daily_log.db"

STOOQ_CSV = "https://stooq.com/q/d/l/?s={symbol}&i=d"  # daily bars CSV

def get_last_unscored_day(conn):
    c = conn.cursor()
    c.execute("SELECT date, bias, signals FROM log WHERE outcome IS NULL ORDER BY date ASC LIMIT 1")
    return c.fetchone()

def fetch_stooq_daily_return(symbol: str, date_iso: str) -> float:
    """
    Fetch close-to-close % return for the trading day on/after date_iso.
    Uses Stooq symbols:
      ^spx = S&P 500
      ^ndx = Nasdaq 100
    """
    url = STOOQ_CSV.format(symbol=symbol)
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    lines = r.text.strip().splitlines()
    # header: Date,Open,High,Low,Close,Volume
    rows = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        rows.append((parts[0], float(parts[4])))

    if len(rows) < 2:
        raise RuntimeError(f"Not enough data from Stooq for {symbol}")

    target = datetime.fromisoformat(date_iso).date()

    # find first row with date >= target, then use prior row for prev close
    # rows are ascending by date in stooq download
    idx = None
    for i, (d, close) in enumerate(rows):
        d_date = datetime.fromisoformat(d).date()
        if d_date >= target:
            idx = i
            break

    if idx is None or idx == 0:
        raise RuntimeError(f"No suitable date found for {symbol} around {date_iso}")

    close_today = rows[idx][1]
    close_prev = rows[idx - 1][1]

    return (close_today - close_prev) / close_prev * 100.0

def judge_outcome(bias: str, spx_ret: float, ndx_ret: float) -> str:
    THRESH = 0.25  # treat moves within ±0.25% as "flat/noise"

    def direction(x: float) -> str:
        if x > THRESH:
            return "Bullish"
        if x < -THRESH:
            return "Bearish"
        return "Flat"

    spx_dir = direction(spx_ret)
    ndx_dir = direction(ndx_ret)

    # If both are flat, it's a no-signal day (no learning)
    if spx_dir == "Flat" and ndx_dir == "Flat":
        return "no_signal"

    # Correct only if both confirm the bias
    if bias == "Bullish" and spx_dir == "Bullish" and ndx_dir == "Bullish":
        return "correct"
    if bias == "Bearish" and spx_dir == "Bearish" and ndx_dir == "Bearish":
        return "correct"

    return "incorrect"


def main():
    conn = sqlite3.connect(DB_PATH)
    row = get_last_unscored_day(conn)

    if not row:
        print("No unscored days found.")
        return

    date_iso, bias, signals_json = row
    bias = (bias or "").strip().lower()

    
    analysis = json.loads(signals_json)
    signals = analysis.get("signals", {})


    spx_ret = fetch_stooq_daily_return("^spx", date_iso)
    ndx_ret = fetch_stooq_daily_return("^ndx", date_iso)

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
    else:
        print("No learning applied (flat/no-signal day).")


    print(f"{date_iso} | Bias={bias} | SPX={spx_ret:.2f}% | NDX={ndx_ret:.2f}% | Outcome={outcome}")
    send_telegram(f"✅ Evaluation\n{date_iso} | Outcome: {outcome}\nSPX: {spx_ret:.2f}% | NDX: {ndx_ret:.2f}%")

if __name__ == "__main__":
    main()
    


