import os
import json
from openai import OpenAI

def extract_signals(news_text: str) -> dict:
    """
    Returns:
      {
        "signals": { "macro_risk_off": "bearish", ... },
        "drivers": ["...", "..."],
        "key_risk": "..."
      }
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # No API key => fallback
        return {
            "signals": {},
            "drivers": ["OpenAI API key not set; using fallback."],
            "key_risk": "No model inference ran."
        }

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are a futures day-trading assistant for US indices (ES/NQ).
From the news below, extract trading-relevant signals.

Output STRICT JSON ONLY with this shape:
{{
  "signals": {{
    "macro_risk_off": "bullish|bearish|neutral",
    "macro_risk_on": "bullish|bearish|neutral",
    "inflation_hot": "bullish|bearish|neutral",
    "inflation_cooling": "bullish|bearish|neutral",
    "fed_hawkish": "bullish|bearish|neutral",
    "fed_dovish": "bullish|bearish|neutral",
    "earnings_positive": "bullish|bearish|neutral",
    "earnings_negative": "bullish|bearish|neutral",
    "geopolitics_risk": "bullish|bearish|neutral",
    "liquidity_stress": "bullish|bearish|neutral"
  }},
  "drivers": ["<short bullets, max 5>"],
  "key_risk": "<one sentence risk that could invalidate the bias>"
}}

News:
{news_text[:12000]}
"""

    for _ in range(3):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content.strip()
        try:
            return json.loads(resp.choices[0].message.content)
        except Exception:
            continue

    return {
        "signals": {},
        "drivers": ["Model did not return valid JSON; using fallback."],
        "key_risk": "No model inference ran."
    }

