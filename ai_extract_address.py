""" Use gemini api to get the address from a subject line """

import os
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
    "Extract the street address from the provided text. Return only the address. Do not include extra information, formatting, or conversational responses."
)
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


def ai_extract_address(text: str, text_id):
    """
    Uses the Gemini API to summarize a single block of text.
    """

    # Load cache
    cache = load_cache()
    # Return cached summary if it exists
    if str(text_id) in cache:
        return cache[str(text_id)]

    # Construct the user prompt
    user_prompt = f"Please extract the street address - if no address exists, return absolutely nothing - from the following text:\n\n---\n{text}\n---"
    try:
        # Generate the content with the system instruction and user prompt
        response = client.models.generate_content(
            model=MODEL,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
            ),
        )
        summary = response.text.strip()
        # Save to cache
        cache[str(text_id)] = summary
        save_cache(cache)

        return summary

    except Exception as e:
        print(f"An error occurred during API call for text {text_id}: {e}")
