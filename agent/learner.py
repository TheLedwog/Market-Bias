import json

WEIGHT_FILE = "config/signal_weights.json"

def update_weights(signals: dict, correct: bool):
    """
    Adjust signal weights based on outcome.
    Reinforces signals that were correct and penalises those that were wrong.
    """

    with open(WEIGHT_FILE, "r") as f:
        weights = json.load(f)

    for signal, direction in signals.items():
        # Ignore neutral signals
        if direction == "neutral":
            continue

        if correct:
            weights[signal] *= 1.02
        else:
            weights[signal] *= 0.95

    # Normalise weights so weights sum to 1
    total = sum(weights.values())
    for k in weights:
        weights[k] = weights[k] / total

    with open(WEIGHT_FILE, "w") as f:
        json.dump(weights, f, indent=2)
