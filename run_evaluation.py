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


def fetch_stooq_open_close_return(symbol: str, date_iso: str) -> float:
    """
    Fetch RTH open-to-close % return for the trading day on/after date_iso.
    Using Stooq daily bars for US ETFs:
      SPY = S&P 500 ETF (RTH)
      QQQ = Nasdaq 100 ETF (RTH)
    """
    url = STOOQ_CSV.format(symbol=symbol.lower())  # stooq uses lowercase
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    lines = r.text.strip().splitlines()
    # header: Date,Open,High,Low,Close,Volume
    rows = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        d = parts[0]
        o = float(parts[1])
        c = float(parts[4])
        rows.append((d, o, c))

    if len(rows) < 1:
        raise RuntimeError(f"Not enough data from Stooq for {symbol}")

    target = datetime.fromisoformat(date_iso).date()

    # rows are ascending by date in stooq download
    idx = None
    for i, (d, o, c) in enumerate(rows):
        d_date = datetime.fromisoformat(d).date()
        if d_date >= target:
            idx = i
            break

    if idx is None:
        raise RuntimeError(f"No suitable date found for {symbol} around {date_iso}")

    open_px = rows[idx][1]
    close_px = rows[idx][2]

    return (close_px - open_px) / open_px * 100.0


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
    conn = sqlite3.connect(DB_PATH)
    row = get_last_unscored_day(conn)

    if not row:
        print("No unscored days found.")
        return

    date_iso, bias, signals_json = row
    bias = (bias or "").strip().lower()

    
    analysis = json.loads(signals_json)
    signals = analysis.get("signals", {})


    spx_ret = fetch_stooq_open_close_return("SPY", date_iso)
    ndx_ret = fetch_stooq_open_close_return("QQQ", date_iso)


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


    print(f"{date_iso} | Bias={bias} | SPY(RTH)={spx_ret:.2f}% | QQQ(RTH)={ndx_ret:.2f}% | Outcome={outcome}")
    send_telegram(
        f"✅ Evaluation (NY RTH proxy)\n"
        f"{date_iso} | Outcome: {outcome}\n"
        f"SPY (O->C): {spx_ret:.2f}% | QQQ (O->C): {ndx_ret:.2f}%"
    )

if __name__ == "__main__":
    main()
    





