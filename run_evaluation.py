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

# Try a day once, then retry on failure up to this many attempts total. After
# that, give up and mark the day "skipped" so it stops blocking newer days (the
# queue always processes the OLDEST unscored day, so one permanently-unfetchable
# day would otherwise wedge everything behind it).
MAX_EVAL_ATTEMPTS = 3

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
    
def get_unscored_days(conn):
    """All unscored days, oldest first, so one run can drain the whole queue."""
    c = conn.cursor()
    c.execute("SELECT date, bias, signals FROM log WHERE outcome IS NULL ORDER BY date ASC")
    return c.fetchall()


# Per-run cache of the daily-bars series, keyed by symbol. Draining the queue
# means looking up many dates; without this we'd re-download the same 3mo series
# once per (day, symbol) pair.
_series_cache = {}


def _get_series(symbol: str):
    """Fetch & cache `symbol`'s daily bars once per run as {date_iso: (open, close)}.

    Lets network/HTTP errors propagate (the cron slot fails and retries later),
    but returns {} if the payload is present-but-unparseable.
    """
    if symbol in _series_cache:
        return _series_cache[symbol]

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
        _series_cache[symbol] = {}
        return {}

    series = {}
    for ts, o, c in zip(timestamps, opens, closes):
        # Daily bars are timestamped at the exchange open; for US markets that
        # always falls on the same calendar day in UTC.
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        series[d] = (o, c)

    _series_cache[symbol] = series
    return series


def fetch_open_close_return(symbol: str, date_iso: str):
    """Open->close % return for `symbol` on `date_iso`, via Yahoo Finance.

    Returns None if the day isn't present yet (e.g. data not posted) or the
    response can't be parsed.
    """
    bar = _get_series(symbol).get(date_iso)
    if not bar:
        return None
    o, c = bar
    if o and c:
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
    c = conn.cursor()

    rows = get_unscored_days(conn)
    if not rows:
        # No-op run (everything already scored) -- log it but stay silent so the
        # fallback cron slots don't spam Telegram on a normal night.
        print("ℹ️ Evaluation complete: no unscored days found.")
        conn.close()
        return

    # Drain the whole queue in one run. Each day is independent: a day whose data
    # isn't ready yet (e.g. today, before the US close) goes to retry/skip without
    # blocking the older days behind it. The single connection stays open across
    # the loop (the old code closed it before resetting eval_attempts, which would
    # have raised on a decisive outcome).
    scored = []   # (date, bias, outcome, spy_ret, qqq_ret)
    delayed = []  # (date, attempts)
    skipped = []  # (date, attempts)

    for date_iso, bias_raw, signals_json in rows:
        bias = (bias_raw or "").strip().lower()

        try:
            analysis = json.loads(signals_json) if signals_json else {}
        except (TypeError, ValueError):
            analysis = {}
        signals = analysis.get("signals", {})

        spy_ret = fetch_open_close_return("SPY", date_iso)
        qqq_ret = fetch_open_close_return("QQQ", date_iso)

        if spy_ret is None or qqq_ret is None:
            c.execute("SELECT eval_attempts FROM log WHERE date=?", (date_iso,))
            row_attempts = c.fetchone()
            attempts = row_attempts[0] if row_attempts and row_attempts[0] is not None else 0
            attempts += 1

            if attempts < MAX_EVAL_ATTEMPTS:
                # Still retrying: bump the counter and leave the day unscored.
                c.execute("UPDATE log SET eval_attempts=? WHERE date=?", (attempts, date_iso))
                delayed.append((date_iso, attempts))
            else:
                # Give up: mark "skipped" so it stops blocking the queue.
                # Skipped days never update weights (only correct/incorrect do).
                c.execute(
                    "UPDATE log SET eval_attempts=?, outcome='skipped' WHERE date=?",
                    (attempts, date_iso),
                )
                skipped.append((date_iso, attempts))
            conn.commit()
            continue

        outcome = judge_outcome(bias, spy_ret, qqq_ret)
        c.execute("""
            UPDATE log
            SET spx_close_return=?, ndx_close_return=?, outcome=?
            WHERE date=?
        """, (spy_ret, qqq_ret, outcome, date_iso))

        if outcome in ("correct", "incorrect"):
            update_weights(signals, correct=(outcome == "correct"))
            c.execute("UPDATE log SET eval_attempts=0 WHERE date=?", (date_iso,))

        conn.commit()
        scored.append((date_iso, bias, outcome, spy_ret, qqq_ret))

    conn.close()

    # One summary message instead of spamming a Telegram per day.
    lines = ["✅ Evaluation run (NY cash proxy)"]
    if scored:
        lines.append("\nScored:")
        for d, b, o, s, q in scored:
            lines.append(f"• {d} {b} → {o} (SPY {s:+.2f}%, QQQ {q:+.2f}%)")
    if delayed:
        lines.append("\nDelayed (data not ready, will retry):")
        for d, a in delayed:
            lines.append(f"• {d} (attempt {a}/{MAX_EVAL_ATTEMPTS})")
    if skipped:
        lines.append("\nSkipped (gave up after retries):")
        for d, a in skipped:
            lines.append(f"• {d} (attempts {a})")

    msg = "\n".join(lines)
    print(msg)

    # Only notify when something meaningful happened: a day was scored, or a day
    # was finally given up on. A run that only bumped still-retrying "delayed"
    # days stays silent, so late-data fallback slots don't ping every night.
    if scored or skipped:
        send_telegram(msg)

if __name__ == "__main__":
    main()

    












