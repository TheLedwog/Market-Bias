import sqlite3
import os
from datetime import date

from delivery.telegram import send_telegram

print("✅ run_weekly.py started", flush=True)

DB_PATH = "memory/daily_log.db"

# Outcomes that count as a graded call. no_signal (flat market) and skipped
# (no data) are NOT wrong calls, so they're excluded from win-rate maths and
# reported separately as context.
DECISIVE = ("correct", "incorrect")


def fetch_rows():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT date, bias, outcome FROM log ORDER BY date ASC")
    rows = c.fetchall()
    conn.close()
    return rows


def win_rate(rows):
    """(#correct, #graded, rate%) over rows with a decisive outcome."""
    graded = [r for r in rows if (r[2] or "") in DECISIVE]
    correct = sum(1 for r in graded if r[2] == "correct")
    n = len(graded)
    rate = (correct / n * 100.0) if n else None
    return correct, n, rate


def fmt_rate(correct, n, rate):
    if rate is None:
        return "n/a (no graded days)"
    return f"{rate:.0f}%  ({correct}/{n})"


def main():
    if not os.path.exists(DB_PATH):
        print("No DB found; nothing to report.")
        return

    rows = fetch_rows()
    if not rows:
        print("Log empty; nothing to report.")
        return

    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()

    def in_this_week(d):
        y, w, _ = date.fromisoformat(d).isocalendar()
        return (y, w) == (iso_year, iso_week)

    week_rows = [r for r in rows if in_this_week(r[0])]

    wc, wn, wr = win_rate(week_rows)
    oc, on, orate = win_rate(rows)

    # Accuracy by call direction (all-time, graded only).
    def split(label):
        d = [r for r in rows
             if (r[1] or "").strip().lower() == label and (r[2] or "") in DECISIVE]
        return sum(1 for r in d if r[2] == "correct"), len(d)

    bull_c, bull_n = split("bullish")
    bear_c, bear_n = split("bearish")

    # Current streak: consecutive same outcome from the most recent graded day.
    graded_desc = [r for r in reversed(rows) if (r[2] or "") in DECISIVE]
    streak, streak_kind = 0, None
    if graded_desc:
        streak_kind = graded_desc[0][2]
        for r in graded_desc:
            if r[2] == streak_kind:
                streak += 1
            else:
                break
    streak_txt = f"{streak} {streak_kind} in a row" if streak_kind else "n/a"

    # Ungraded context for the week.
    week_nosig = sum(1 for r in week_rows if (r[2] or "") == "no_signal")
    week_skip = sum(1 for r in week_rows if (r[2] or "") == "skipped")
    week_pending = sum(1 for r in week_rows if r[2] is None)

    # ---- Low-confidence lean for next week (weak heuristic, NOT a forecast) ----
    last5 = list(reversed(rows))[:5]
    bull5 = sum(1 for r in last5 if (r[1] or "").strip().lower() == "bullish")
    bear5 = sum(1 for r in last5 if (r[1] or "").strip().lower() == "bearish")
    if bull5 > bear5:
        lean = "Bullish"
    elif bear5 > bull5:
        lean = "Bearish"
    else:
        lean = "Mixed / no clear lean"

    last10 = [r for r in reversed(rows) if (r[2] or "") in DECISIVE][:10]
    r10c = sum(1 for r in last10 if r[2] == "correct")
    recent_rate = (r10c / len(last10) * 100.0) if last10 else None

    lines = [
        "📊 Weekly Market-Bias report",
        f"Week of {today.isoformat()} (ISO week {iso_week})",
        "",
        f"This week:  {fmt_rate(wc, wn, wr)}",
        f"All-time:   {fmt_rate(oc, on, orate)}",
        "",
        "Accuracy by call (all-time):",
        f"• Bullish: {fmt_rate(bull_c, bull_n, (bull_c / bull_n * 100) if bull_n else None)}",
        f"• Bearish: {fmt_rate(bear_c, bear_n, (bear_c / bear_n * 100) if bear_n else None)}",
        f"Current streak: {streak_txt}",
    ]

    ungraded = []
    if week_nosig:
        ungraded.append(f"{week_nosig} no-signal")
    if week_skip:
        ungraded.append(f"{week_skip} skipped")
    if week_pending:
        ungraded.append(f"{week_pending} pending")
    if ungraded:
        lines.append(f"This week (ungraded): {', '.join(ungraded)}")

    lines += [
        "",
        "🔮 Lean for next week (weak heuristic — not a forecast):",
        f"• {lean}  (last 5 calls: {bull5} bullish / {bear5} bearish)",
    ]
    if recent_rate is not None:
        lines.append(f"• Recent reliability: {recent_rate:.0f}% over last {len(last10)} graded days")
    lines.append(
        "Treat as low-confidence context — the bot reacts to each morning's news "
        "and does not actually forecast a week ahead."
    )

    msg = "\n".join(lines)
    print(msg)
    send_telegram(msg)


if __name__ == "__main__":
    main()
