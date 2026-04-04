"""Use gemini api to summarize the application description"""

import os
import time
import random
from google import genai
from google.genai import types
import json

# --- Configuration ---
# The client automatically picks up the GEMINI_API_KEY environment variable.
try:
    client = genai.Client()
except Exception as e:
    print(f"Error initializing Gemini client: {e}")
    print("Please ensure you have set the GEMINI_API_KEY environment variable.")
    exit()

# Define the model to use
MODEL = "gemini-2.5-flash"
# System instruction to define the model's persona and primary task
SYSTEM_INSTRUCTION = (
    "Summarize the provided text in at most two sentences. Be concise, impersonal, and objective. "
    "Use passive voice. Start directly with the main action or purpose. "
    "No commentary, no em dashes, no extra formatting or punctuation."
)
MAX_INPUT_CHARS = 2000
CACHE_FILE = "summaries.json"


def load_cache():
    """Load previously generated descriptions"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}


def save_cache(cache):
    """Save the descriptions"""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _call_model(model: str, text: str, retries: int = 4) -> str:
    truncated = text[:MAX_INPUT_CHARS]
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[truncated],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
            return response.text.strip()
        except Exception as e:
            if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"Rate limited on {model}, retrying in {wait:.1f}s (attempt {attempt + 1}/{retries})...")
                time.sleep(wait)
            else:
                raise


def ai_summarise_text(text: str, description_id):
    """Uses the Gemini API to summarize a single block of text."""
    cache = load_cache()
    if str(description_id) in cache:
        return cache[str(description_id)]

    try:
        summary = _call_model(MODEL, text)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            print(f"Quota exceeded for {description_id}, retrying with gemini-2.0-flash-lite...")
            try:
                summary = _call_model("gemini-2.0-flash-lite", text)
            except Exception as fallback_e:
                print(f"Fallback model also failed for {description_id}: {fallback_e}")
                return None
        else:
            print(f"An error occurred during API call for text {description_id}: {e}")
            return None

    cache[str(description_id)] = summary
    save_cache(cache)
    return summary