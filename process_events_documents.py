"""Parse event permit emails from subject lines only — no AI calls."""

import re
import os
import json
import unicodedata
from download_emails import CACHE_FILE
from process_documents import format_address
from upload_gdrive import upload_files

# Well-known Cape Town venues → canonical address
VENUE_LOOKUP = {
    "cticc 2": "Corner Heerengracht And Rua Bartholomeu Dias, Foreshore, Cape Town",
    "cticc": "1 Lower Long Street, Foreshore, Cape Town",
    "castle of good hope": "Buitenkant Street, Foreshore, Cape Town",
    "dhl stadium": "Fritz Sonnenberg Road, Green Point, Cape Town",
    "battery park": "Port Road, V&A Waterfront, Cape Town",
    "grand africa café & beach": "1 Haul Road, V&A Waterfront, Cape Town",
    "grand africa cafe & beach": "1 Haul Road, V&A Waterfront, Cape Town",
    "grand africa beach & cafe": "1 Haul Road, V&A Waterfront, Cape Town",
    "grande africa cafe & beach": "1 Haul Road, V&A Waterfront, Cape Town",
    "cabo beach club": "12 South Arm Road, V&A Waterfront, Cape Town",
    "makers landing": "The Cruise Terminal, V&A Waterfront, Cape Town",
    "grand parade": "Darling Street, Cape Town",
    "greenmarket square": "Greenmarket Square, Cape Town",
    "green market square": "Greenmarket Square, Cape Town",
    "oranjezicht city farmers market": "Breakwater Boulevard, V&A Waterfront, Cape Town",
    "zeitz mocaa": "South Arm Road, Silo District, V&A Waterfront, Cape Town",
    "v&a waterfront": "V&A Waterfront, Cape Town",
    "cape town city hall": "Darling Street, Cape Town",
    "mount nelson hotel": "76 Orange Street, Gardens, Cape Town",
}

# Matches the start of a date expression, e.g. "13-15 April 2026", "5th January 2026"
_DATE_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?(?:\s*[-–—]\s*\d{1,2}(?:st|nd|rd|th)?)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{4})?",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumeric runs to a single space."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


# Pre-normalise the lookup keys once
_NORMALISED_LOOKUP = {_normalise(k): v for k, v in VENUE_LOOKUP.items()}


def _resolve_address(venue_text: str) -> str:
    """Return a geocodeable address for a venue string.

    Normalises both the lookup keys and venue_text (strips accents, punctuation,
    collapses whitespace) before matching, so variants like "Grand Africa Café"
    and "Grande Africa Cafe" both hit the same entry.
    Tries the lookup table first; falls back to formatting the raw text.
    """
    normalised = _normalise(venue_text)
    for key, addr in _NORMALISED_LOOKUP.items():
        if key in normalised:
            return addr
    return format_address(venue_text)


def parse_event_subject(subject: str) -> dict | None:
    """Parse a Cape Town event permit subject line into structured fields.

    Expected (approximate) format:
        EO##-#### - [Title] - [Venue/Address] - [Date range] (External Services)

    Returns a dict with keys: title, venue, address, event_date
    or None when the subject cannot be parsed reliably.
    """
    # Strip trailing qualifiers: (External Services), (External), (Externa Services), etc.
    # Allow a space inside the paren and accept truncated spellings like "Extern".
    clean = re.sub(r"\s*\(\s*[Ee]xtern[^)]*\)\s*$", "", subject).strip()
    # Normalise pipe separators used in some free-concert subjects
    clean = re.sub(r"\s*\|\s*", " - ", clean)

    # Collapse date ranges that use " - " between the two day numbers so they
    # don't get mistaken for field separators, e.g. "9 - 10 February" → "9-10 February"
    _MONTHS = (r"January|February|March|April|May|June|July|August|"
               r"September|October|November|December")
    clean = re.sub(
        rf"(\b\d{{1,2}}(?:st|nd|rd|th)?)\s+-\s+(\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTHS}))",
        r"\1-\2",
        clean,
        flags=re.IGNORECASE,
    )

    # Extract and remove the leading event code (e.g. "EO26-0155", "EP26-0066")
    code_match = re.match(r"^(E[A-Z]?\d+-\d+)\s*-\s*", clean)
    if code_match:
        remainder = clean[code_match.end():].strip()
    else:
        # Fallback: event code embedded in title, e.g. "Hollywoodbets ... (EO25-0750) - date"
        remainder = clean

    # Split remainder on " - "
    parts = re.split(r"\s+-\s+", remainder)

    # Merge any segment that starts with "(" back into the previous one — these
    # are parenthetical clarifications that belong to the preceding venue name,
    # e.g. "DSK - (German School), 28 Bay View Ave" should stay together.
    merged: list[str] = []
    for part in parts:
        if merged and part.lstrip().startswith("("):
            merged[-1] = merged[-1] + " - " + part
        else:
            merged.append(part)
    parts = merged

    # Find the rightmost segment that looks like a date
    date_idx = None
    for i in range(len(parts) - 1, -1, -1):
        if _DATE_RE.search(parts[i]):
            date_idx = i
            break

    # Need at least: title | venue | date  (date_idx must be >= 1 for a venue before it)
    if date_idx is None or date_idx < 1:
        return None

    venue_text = parts[date_idx - 1]

    # If the venue segment is a bare city/area name (no comma, no street number),
    # it's probably a trailing city suffix — merge it with the preceding segment.
    _GENERIC = {"cape town", "cbd", "foreshore", "green point", "waterfront"}
    if _normalise(venue_text) in _GENERIC and date_idx >= 2:
        venue_text = parts[date_idx - 2] + ", " + venue_text
        title_parts = parts[:date_idx - 2]
    else:
        title_parts = parts[:date_idx - 1]

    title = " - ".join(title_parts).strip() if title_parts else venue_text

    # Extract the first date occurrence from the date segment
    date_match = _DATE_RE.search(parts[date_idx])
    event_date = date_match.group().strip() if date_match else parts[date_idx].strip()
    # Capitalise month name
    event_date = re.sub(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)",
        lambda m: m.group(0).capitalize(),
        event_date,
        flags=re.IGNORECASE,
    )

    address = _resolve_address(venue_text)

    return {
        "title": title,
        "venue": venue_text,
        "address": address,
        "event_date": event_date,
    }


def process_events_documents(path: str) -> list[dict]:
    """Extract event data from the subject line of an events email.

    Uses only regex — no AI/API calls.  Returns a list with one item on
    success, or an empty list when the subject cannot be parsed.
    """
    with open(CACHE_FILE, "r") as f:
        subject_list = json.load(f)

    email_id = os.path.basename(path)
    subject = subject_list.get(email_id, "")
    if not subject:
        print(f"\n{email_id}: no subject found in cache")
        return []

    parsed = parse_event_subject(subject)
    if not parsed:
        print(f"\n{email_id}: could not parse subject: {subject}")
        return []

    title = parsed["title"]
    address = parsed["address"]
    event_date = parsed["event_date"]
    # Description: event name + venue for context
    description = f"{title} at {parsed['venue']}"

    file_link = upload_files(path, "Events Permit", address)

    print(f"\n{subject}:")
    print(f"    Title:       {title}")
    print(f"    Venue:       {parsed['venue']}")
    print(f"    Address:     {address}")
    print(f"    Date:        {event_date}")

    return [{
        "filename": subject,
        "address": address,
        "title": title,
        "description": description,
        "closing_date": event_date,
        "file_link": file_link,
    }]


def process_all_events(directory: str) -> list[dict]:
    """Loop through events email directories and extract data from subject lines."""
    data = []
    for email_id in os.listdir(directory):
        full_path = os.path.join(directory, email_id)
        if os.path.isdir(full_path):
            result = process_events_documents(full_path)
            data.extend(result)

    print(f"Got {len(data)} {directory} items")
    return data
