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
FALLBACK_MODEL = "gemini-3.5-flash-lite"
# System instruction to define the model's persona and primary task
SYSTEM_INSTRUCTION = (
    "Summarize the provided text in at most two sentences. Be concise, impersonal, and objective. "
    "Use passive voice. Start directly with the main action or purpose. "
    "No commentary, no em dashes, no extra formatting or punctuation."
    "Do not state that an application has been submitted or that permissions are sought — every text "
    "describes an application, so this is redundant. Do not mention the Heritage Protection Overlay Zone, "
    "heritage overlay status, or any heritage-related permission — every application is already within one, "
    "so this is also redundant. Focus only on the specific proposed works and variances."
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

class DailyQuotaExceeded(Exception):
    """Raised when a model's per-day free-tier quota is exhausted."""
    pass

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
            response_text = response.text
            if response_text:
                return response_text.strip()
        except Exception as e:
            e_str = str(e)
            is_rate_limited = "429" in e_str or "RESOURCE_EXHAUSTED" in e_str
            is_daily_cap = "PerDay" in e_str  # matches GenerateRequestsPerDayPerProjectPerModel-FreeTier

            if is_rate_limited and is_daily_cap:
                raise DailyQuotaExceeded(f"Daily quota exhausted for {model}") from e
            elif is_rate_limited and attempt < retries - 1:
                wait = (3 ** attempt) + random.uniform(0, 1)
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
    except DailyQuotaExceeded:
        print(f"Daily cap reached for {MODEL}, retrying with {FALLBACK_MODEL}...")
        try:
            summary = _call_model(FALLBACK_MODEL, text)
        except DailyQuotaExceeded:
            print(f"Daily cap also reached for {FALLBACK_MODEL}")
            return None
        except Exception as fallback_e:
            print(f"Fallback model also failed for {description_id}: {fallback_e}")
            return None
    except Exception as e:
        e_str = str(e)
        if "429" in e_str or "RESOURCE_EXHAUSTED" in e_str or "503" in e_str or "UNAVAILABLE" in e_str:
            print(f"Model unavailable for {description_id}, retrying with gemini-2.0-flash-lite...")
            try:
                summary = _call_model(FALLBACK_MODEL, text)
            except Exception as fallback_e:
                print(f"Fallback model also failed for {description_id}: {fallback_e}")
                return None
        else:
            print(f"An error occurred during API call for text {description_id}: {e}")
            return None

    cache[str(description_id)] = summary
    save_cache(cache)
    return summary
