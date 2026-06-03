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
        return "n/a"
    return f"{rate:.0f}% ({correct}/{n})"


def week_label(iso_year, iso_week):
    """Human-readable Mon–Fri range for an ISO week, e.g. '2–6 Jun 2026'."""
    mon = date.fromisocalendar(iso_year, iso_week, 1)
    fri = date.fromisocalendar(iso_year, iso_week, 5)
    if mon.month == fri.month:
        return f"{mon.day}–{fri.day} {fri:%b %Y}"
    return f"{mon.day} {mon:%b} – {fri.day} {fri:%b %Y}"


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
        lean = "Mixed"

    last10 = [r for r in reversed(rows) if (r[2] or "") in DECISIVE][:10]
    r10c = sum(1 for r in last10 if r[2] == "correct")
    recent_rate = (r10c / len(last10) * 100.0) if last10 else None

    bull_rate = fmt_rate(bull_c, bull_n, (bull_c / bull_n * 100) if bull_n else None)
    bear_rate = fmt_rate(bear_c, bear_n, (bear_c / bear_n * 100) if bear_n else None)

    lines = [
        "📊 <b>Weekly Bias Report</b>",
        week_label(iso_year, iso_week),
        "",
        "<b>Win rate</b>",
        f"This week — {fmt_rate(wc, wn, wr)}",
        f"All-time — {fmt_rate(oc, on, orate)}",
    ]

    ungraded = []
    if week_nosig:
        ungraded.append(f"{week_nosig} no-signal")
    if week_skip:
        ungraded.append(f"{week_skip} skipped")
    if week_pending:
        ungraded.append(f"{week_pending} pending")
    if ungraded:
        lines.append(f"Ungraded — {', '.join(ungraded)}")

    lines += [
        "",
        "<b>By call</b> (all-time)",
        f"Bullish — {bull_rate}",
        f"Bearish — {bear_rate}",
        f"Streak — {streak_txt}",
        "",
        f"🔮 <b>Next week: {lean}</b>",
    ]

    if lean == "Mixed":
        lines.append(f"No clear lean · last 5 calls {bull5} bull / {bear5} bear")
    else:
        detail = f"Low confidence · last 5 calls {bull5} bull / {bear5} bear"
        if recent_rate is not None:
            detail += f" · recent form {recent_rate:.0f}%"
        lines.append(detail)

    lines += [
        "",
        "<i>Weak heuristic, not a forecast — the bot reacts to each morning's news.</i>",
    ]

    msg = "\n".join(lines)
    print(msg)
    send_telegram(msg, parse_mode="HTML")


if __name__ == "__main__":
    main()
