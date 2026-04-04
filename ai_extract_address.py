""" Use gemini api to get the address from a subject line """

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
    "Extract all street names or addresses from the text. Return only the extracted names, nothing else. If none found, return nothing."
)
MAX_INPUT_CHARS = 2000
CACHE_FILE = "addresses.json"


def load_cache():
    """Load previously generated texts"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}


def save_cache(cache):
    """Save the texts"""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _call_model(model: str, text: str, retries: int = 4):
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
        except Exception as e:
            if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"Rate limited on {model}, retrying in {wait:.1f}s (attempt {attempt + 1}/{retries})...")
                time.sleep(wait)
                continue
            raise

        if response is None:
            raise RuntimeError("Empty response from model")

        if not getattr(response, "text", None):
            finish_reason = None
            safety = None
            if getattr(response, "candidates", None):
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, "finish_reason", None)
                safety = getattr(candidate, "safety_ratings", None)
            raise RuntimeError(f"No text returned. finish_reason={finish_reason} safety={safety}")

        return response.text.strip()


def ai_extract_address(text: str, text_id):
    """Uses the Gemini API to extract street names or addresses from text."""
    cache = load_cache()
    if str(text_id) in cache:
        return cache[str(text_id)]

    try:
        result = _call_model(MODEL, text)
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            print(f"Quota exceeded for {text_id}, retrying with gemini-2.0-flash-lite...")
            try:
                result = _call_model("gemini-2.0-flash-lite", text)
            except Exception as fallback_e:
                print(f"Fallback model also failed for {text_id}: {fallback_e}")
                return ""
        else:
            status_code = getattr(e, "status_code", None)
            response_body = getattr(e, "response", None)
            print(f"An error occurred during API call for text {text_id}: {status_code} {e} {response_body}")
            return ""

    cache[str(text_id)] = result
    save_cache(cache)
    return result
