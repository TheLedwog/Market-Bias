import os
import json
import time
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SIGNALS = ["fed_tone", "yields", "earnings", "risk_sentiment", "macro_data"]

def extract_analysis(news_text: str) -> dict:
    """
    Returns a dict with:
      - signals: dict of SIGNALS -> bullish/bearish/neutral
      - drivers: list[str] (3 short bullets)
      - key_risk: str (1 short line)
      - index_tilt: dict { "ES": bullish/bearish/neutral, "NQ": bullish/bearish/neutral }
    """

    prompt = f"""
You are a professional US index futures trader.

From the NEWS below, produce STRICT JSON with exactly these keys:
- "signals": object with keys {SIGNALS} and values only "bullish", "bearish", or "neutral"
- "drivers": array of exactly 3 short bullet-style strings (no numbering, no emojis)
- "key_risk": one short, SPECIFIC line describing the most likely condition that would INVALIDATE the bias today. 
  This should be concrete (e.g. yields, Fed speakers, index behaviour) and not generic.
  Avoid vague phrasing like "unexpected data" or "sentiment shift".
- "index_tilt": object with keys "ES" and "NQ", each "bullish"/"bearish"/"neutral"

Rules:
- If unclear, use "neutral".
- Keep drivers specific to the news (not generic).
- Return JSON only. No markdown. No extra text.

NEWS:
{news_text}
"""

    for _ in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)

            # Defensive defaults
            signals = data.get("signals", {})
            signals = {k: signals.get(k, "neutral") for k in SIGNALS}

            drivers = data.get("drivers", [])
            if not isinstance(drivers, list):
                drivers = []
            drivers = [str(x).strip() for x in drivers if str(x).strip()][:3]
            while len(drivers) < 3:
                drivers.append("No clear additional driver from headlines.")

            key_risk = str(data.get("key_risk", "Key risk: unexpected macro/earnings surprise.")).strip()

            index_tilt = data.get("index_tilt", {})
            if not isinstance(index_tilt, dict):
                index_tilt = {}
            index_tilt = {
                "ES": index_tilt.get("ES", "neutral"),
                "NQ": index_tilt.get("NQ", "neutral"),
            }

            return {
                "signals": signals,
                "drivers": drivers,
                "key_risk": key_risk,
                "index_tilt": index_tilt,
            }

        except RateLimitError:
            time.sleep(5)
        except Exception:
            time.sleep(2)

    # Fallback
    return {
        "signals": {k: "neutral" for k in SIGNALS},
        "drivers": ["Fallback: no analysis available."] * 3,
        "key_risk": "Fallback: model unavailable or quota limited.",
        "index_tilt": {"ES": "neutral", "NQ": "neutral"},
    }
