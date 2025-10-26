"""Use gemini api to summarize the application description"""

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
    "You are an expert editorial assistant. Your task is to analyze the provided "
    "text and generate a concise, professional summary. The summary should be two sentences "
    "long at most, capturing the main points and keeping an impersonal and objective tone. Use the passive voice."
    " Start the summary directly with the main action or purpose of the proposal/application."
    " Do not add any commentary, just provide the summary. Do not use any em dashes or other complicated formatting, "
    " in fact remove any extraneous formatting or punctuation, return a cleanly edited text. "
    "You are a professional providing a summary of the technical text provided"
)
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


def summarize_text(text: str, description_id):
    """
    Uses the Gemini API to summarize a single block of text.
    """

    # Load cache
    cache = load_cache()
    # Return cached summary if it exists
    if str(description_id) in cache:
        return cache[str(description_id)]

    # Construct the user prompt
    user_prompt = f"Please summarize the following text:\n\n---\n{text}\n---"
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
        cache[str(description_id)] = summary
        save_cache(cache)

        return summary

    except Exception as e:
        print(f"An error occurred during API call for text {description_id}: {e}")
