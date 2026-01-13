import os
import json
import time
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

# Load environment variables
load_dotenv()

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Signals we care about
SIGNALS = [
    "fed_tone",
    "yields",
    "earnings",
    "risk_sentiment",
    "macro_data"
]

def extract_signals(news_text: str) -> dict:
    prompt = f"""
Extract ONLY these signals:
{SIGNALS}

Each must be one of: bullish, bearish, neutral.
If unclear, use neutral.

Return JSON with exactly these keys and string values.
"""

    print("🚀 CALLING OPENAI API NOW")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return only valid JSON. No markdown. No extra text."},
            {"role": "user", "content": prompt + "\n\nNEWS:\n" + news_text}
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    data = json.loads(resp.choices[0].message.content)

    # Ensure all keys exist; fill missing with neutral
    return {k: data.get(k, "neutral") for k in SIGNALS}


    # Try up to 3 times (handles rate limits gracefully)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            return json.loads(resp.choices[0].message.content)

        except RateLimitError:
            print("⚠️ OpenAI rate limit hit. Retrying...")
            time.sleep(5)

        except json.JSONDecodeError:
            print("⚠️ Invalid JSON from model. Retrying...")
            time.sleep(2)

    # Fallback if all retries fail
    print("⚠️ Using fallback neutral signals.")
    return {signal: "neutral" for signal in SIGNALS}
