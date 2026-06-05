import json
import sqlite3

def load_weights(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def score_signals(signals: dict, weights: dict) -> float:
    """
    Map: bullish=+1, bearish=-1, neutral/unknown=0
    Weighted sum.
    """
    total = 0.0
    for k, v in signals.items():
        w = float(weights.get(k, 0.0))
        vv = (v or "").strip().lower()
        if vv == "bullish":
            total += w
        elif vv == "bearish":
            total -= w
    return total

# --- Confidence calibration (history-based) -------------------------------
# Confidence is no longer a fixed formula of |score|. Instead it is the
# historical hit-rate of past calls whose |score| was similar to today's,
# i.e. "when the bot has been this convinced before, how often was it right?".
# This only changes the confidence NUMBER -- the bias direction above is
# untouched. See CLAUDE.md notes on the learning loop.

# Tunables. Kept conservative so a couple of lucky days can't spike the number.
PRIOR_SCALE = 3.0   # |score| at which the cold-start magnitude prior reaches ~99%
CAL_WINDOW = 0.75   # half-width of the |score| neighbourhood used to pool history
CAL_ALPHA = 6.0     # shrinkage pseudo-count: ~this many decisive days before
                    # the empirical hit-rate outweighs the prior


def _magnitude_prior(abs_score: float) -> float:
    """Cold-start belief, used until real outcomes exist for this score band.

    A bigger |score| means more signals lined up, so the prior leans more
    confident -- but never below 50% (a decisive score is at least a coin-flip
    lean) and capped near certainty. As history accumulates the empirical
    hit-rate pulls this toward (and can drop it below) 50% for bands that
    actually underperform.
    """
    return 0.5 + 0.5 * min(1.0, abs_score / PRIOR_SCALE)


def load_outcome_history(db_path: str) -> list[tuple[float, float]]:
    """Return [(abs_score, is_correct)] for every decisively-judged past day.

    Only 'correct'/'incorrect' rows count -- 'no_signal'/'skipped'/unscored
    days are excluded (same rule the weekly win-rate uses). Returns [] if the
    DB or table isn't there yet, so callers degrade to the prior.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT score, outcome FROM log "
                "WHERE outcome IN ('correct','incorrect') AND score IS NOT NULL"
            )
            rows = c.fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []

    out = []
    for score, outcome in rows:
        try:
            out.append((abs(float(score)), 1.0 if outcome == "correct" else 0.0))
        except (TypeError, ValueError):
            continue
    return out


def calibrated_confidence(score: float, history: list[tuple[float, float]]) -> float:
    """Confidence % = shrunk historical hit-rate for this |score| band.

    Pools past decisive days within CAL_WINDOW of today's |score| and blends
    their hit-rate with the magnitude prior via CAL_ALPHA pseudo-counts, so the
    number is humble when evidence is thin and earns boldness as it grows.
    """
    a = abs(score)
    prior = _magnitude_prior(a)

    near = [is_correct for (s, is_correct) in history if abs(s - a) <= CAL_WINDOW]
    n = len(near)
    correct = sum(near)

    # Beta-binomial posterior mean: prior gets CAL_ALPHA pseudo-observations.
    p = (correct + CAL_ALPHA * prior) / (n + CAL_ALPHA)

    p = max(0.01, min(0.99, p))
    return p * 100.0


def bias_from_score(score: float, history: list[tuple[float, float]] | None = None) -> tuple[str, float]:
    """
    Returns bias + confidence %.

    `history` is the list from load_outcome_history(); when provided, confidence
    is calibrated against past hit-rates. When None, falls back to the legacy
    magnitude formula (keeps the function usable without a DB).
    """
    if score > 0:
        bias = "Bullish"
    elif score < 0:
        bias = "Bearish"
    else:
        bias = "No Trade"

    if history is None:
        conf = min(0.99, abs(score) / 2.75) * 100.0  # legacy fallback
    else:
        conf = calibrated_confidence(score, history)
    return bias, conf




