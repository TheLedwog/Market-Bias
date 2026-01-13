import json

DIRECTION_MAP = {
    "bullish": 1,
    "neutral": 0,
    "bearish": -1
}

def load_weights():
    with open("config/signal_weights.json", "r") as f:
        return json.load(f)

def compute_bias(signals: dict):
    weights = load_weights()
    score = 0

    for signal, direction in signals.items():
        score += weights[signal] * DIRECTION_MAP.get(direction, 0)

    # Always output bullish/bearish
    bias = "Bullish" if score >= 0 else "Bearish"

    # Confidence: stronger magnitude = higher confidence
    confidence = min(abs(score) / 0.8, 1.0) * 100

    # If score is extremely close to 0, cap confidence low (avoid fake certainty)
    if abs(score) < 0.10:
        confidence = max(confidence, 15.0)

    return bias, round(confidence, 1), score
