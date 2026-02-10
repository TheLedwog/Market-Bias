import json

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

def bias_from_score(score: float) -> tuple[str, float]:
    """
    Returns bias + confidence %
    """
    if score > 0:
        bias = "Bullish"
    elif score < 0:
        bias = "Bearish"
    else:
        bias = "No Trade"

    # Simple confidence mapping
    conf = min(0.99, abs(score) / 2)  # tune as you like
    return bias, conf * 100.0



