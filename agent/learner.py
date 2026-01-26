import json
import os

WEIGHTS_PATH = os.path.join("config", "signal_weights.json")

def update_weights(signals: dict, correct: bool, lr: float = 0.03) -> None:
    """
    If correct => slightly increase weights for aligned signals.
    If incorrect => slightly decrease weights for aligned signals.
    """
    try:
        with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
            weights = json.load(f)
    except Exception:
        weights = {}

    direction = 1.0 if correct else -1.0

    for k, v in (signals or {}).items():
        vv = (v or "").strip().lower()
        if vv not in ("bullish", "bearish"):
            continue

        cur = float(weights.get(k, 0.0))
        # adjust magnitude only
        weights[k] = max(0.0, cur + lr * direction)

    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)

