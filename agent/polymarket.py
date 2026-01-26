import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GAMMA = "https://gamma-api.polymarket.com"

def _ny_today():
    return datetime.now(tz=ZoneInfo("America/New_York")).date()

def find_spx_up_down_probs_for_today() -> dict | None:
    """
    Uses Gamma public-search to find today's SPX Up/Down event and extract outcome probabilities.
    Returns dict like {"up": 0.55, "down": 0.45, "title": "...", "event_slug": "..."} or None.
    """
    ny_date = _ny_today()
    # Polymarket titles usually look like: "S&P 500 (SPX) Up or Down on January 26?"
    date_str = ny_date.strftime("%B %-d") if "%" in "%-" else ny_date.strftime("%B %d").replace(" 0", " ")
    query = f"S&P 500 (SPX) Up or Down on {date_str}"

    try:
        r = requests.get(
            f"{GAMMA}/public-search",
            params={"q": query, "limit_per_type": 25, "search_profiles": False, "search_tags": False},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    events = data.get("events") or []
    if not events:
        return None

    # Choose best matching event by title contains query (case-insensitive), then max volume
    query_lower = query.lower()
    candidates = []
    for ev in events:
        title = (ev.get("title") or "").lower()
        if query_lower in title:
            candidates.append(ev)

    if not candidates:
        candidates = events

    def ev_volume(ev):
        try:
            return float(ev.get("volume") or ev.get("volumeNum") or 0)
        except Exception:
            return 0.0

    best_event = max(candidates, key=ev_volume)

    # The /public-search event object includes nested markets in docs
    markets = best_event.get("markets") or []
    if not markets:
        return None

    # Pick the market that looks like Up/Down with outcomes + prices and max volume
    m_candidates = []
    for m in markets:
        outcomes = m.get("outcomes") or []
        prices = m.get("outcomePrices") or []
        if isinstance(outcomes, str) or isinstance(prices, str):
            # Some responses stringify arrays; ignore for safety
            continue
        out_set = {str(x).strip().lower() for x in outcomes}
        if "up" in out_set and "down" in out_set and len(outcomes) == len(prices) and len(outcomes) >= 2:
            m_candidates.append(m)

    if not m_candidates:
        return None

    def m_volume(m):
        try:
            return float(m.get("volume") or m.get("volumeNum") or 0)
        except Exception:
            return 0.0

    best_m = max(m_candidates, key=m_volume)

    outcomes = best_m.get("outcomes") or []
    prices = best_m.get("outcomePrices") or []

    probs = {}
    for name, px in zip(outcomes, prices):
        try:
            probs[str(name).strip().lower()] = float(px)
        except Exception:
            continue

    up = probs.get("up")
    down = probs.get("down")
    if up is None or down is None:
        return None

    s = up + down
    if s > 0:
        up /= s
        down /= s

    return {
        "up": up,
        "down": down,
        "title": best_event.get("title") or "",
        "event_slug": best_event.get("slug") or ""
    }
