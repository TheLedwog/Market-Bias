import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GAMMA = "https://gamma-api.polymarket.com"


def _ny_today():
    return datetime.now(tz=ZoneInfo("America/New_York")).date()


def _coerce_list_field(x):
    """
    Gamma /markets returns outcomes/outcomePrices sometimes as a JSON string.
    This converts them to Python lists safely.
    """
    if x is None:
        return None
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                return json.loads(s)
            except Exception:
                return None
    return None


def get_spx_up_down_probs_for_today() -> dict | None:
    """
    Fetch today's market: "S&P 500 (SPX) Up or Down on <Month Day>?"
    by constructing the event slug and calling:
      GET https://gamma-api.polymarket.com/markets?slug=<slug>
    Returns:
      {"up": 0.xx, "down": 0.xx, "title": "...", "slug": "..."} or None
    """
    ny = _ny_today()
    month = ny.strftime("%B").lower()   # january
    day = ny.day                        # 26
    year = ny.year                      # 2026

    slug = f"spx-up-or-down-on-{month}-{day}-{year}"

    try:
        r = requests.get(
            f"{GAMMA}/markets",
            params={"slug": [slug]},     # slug is an array filter per docs
            timeout=25,
        )
        r.raise_for_status()
        markets = r.json()
    except Exception:
        return None

    if not markets:
        return None

    # If multiple, take highest volume
    def vol(m):
        try:
            return float(m.get("volume") or 0)
        except Exception:
            return 0.0

    m = max(markets, key=vol)

    outcomes = _coerce_list_field(m.get("outcomes"))
    prices = _coerce_list_field(m.get("outcomePrices"))

    if not outcomes or not prices or len(outcomes) != len(prices):
        return None

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
        "title": m.get("question") or m.get("title") or "",
        "slug": slug,
    }
