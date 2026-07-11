import pdfplumber
import re
import os
import json
from pathlib import Path
from upload_gdrive import upload_files
from collections import defaultdict
from ai_summarise_descriptions import ai_summarise_text
from ai_extract_address import ai_extract_address
from datetime import datetime, timedelta
import signal
import shutil
from download_emails import CACHE_FILE

# Regex patterns
address_pattern = re.compile(
    r"Description and physical address\s*\n([\d\w\s,]+)", re.IGNORECASE
)
description_pattern = re.compile(
    r"Purpose of the application\s*\n(.*?)\nThe following applications", re.IGNORECASE | re.DOTALL
)
close_date_pattern = re.compile(
    r"Closing date for objections, comments or representations\s*\n([\d\w\s]+)", re.IGNORECASE
)

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException()

def process_documents(path):
    """ Open the public participation notice and extract the data """
    documents_path = Path(path)
    document_data = []

    pdf_files = documents_path.glob("*.pdf")
    if next(pdf_files, None) is None:
        print(f"{path}: WARNING NO PDF ATTACHEMENTS - falling back to subject")
        return process_subject_fallback(path)

    for pdf_file in pdf_files:
        # only match the Notice or Advertising Notice pdfs
        file_name = pdf_file.name.lower()
        if not (file_name.startswith("notice") or "advertising" in file_name or "public" in file_name):
            continue
        with pdfplumber.open(pdf_file) as pdf:
            pages = pdf.pages
            if pages:
                # extract closing date
                closing_date = extract_closing_date(pages)
                if not closing_date:
                    print(f"\n{pdf_file.name}: WARNING NO DATE")
                    continue
                elif expired_date(closing_date):
                    # check if closing date far in the past
                    print(f"\n{pdf_file.name}: DELETING - closing date {closing_date} expired")
                    shutil.rmtree(documents_path)
                    return []

                # Extract address
                address = extract_address(pages)
                if not address:
                    print(f"\n{pdf_file.name}: WARNING NO ADDRESS")
                    address = ai_extract_address(pdf_file.name, path)
                    address = format_address(address)
                # title is just street location
                title = address.split(",")[0].strip()
                # extract description
                description = extract_description(pages, path)

                # upload all the attachments from the email to the google drive
                file_link = upload_files(path, pdf_file, address)

                document_data.append({
                    "filename": pdf_file.name,
                    "address": address,
                    "title": title,
                    "description": description,
                    "closing_date": closing_date,
                    "file_link": file_link
                })
                print(f"\n{path}{pdf_file.name}:")
                print(f"    Title:       {title}")
                print(f"    Description: {description}")
                break

    return document_data


def get_email_subject(path):
    """Return the cached subject line for an email directory, or ''."""
    try:
        with open(CACHE_FILE, "r") as f:
            subject_list = json.load(f)
    except (OSError, json.JSONDecodeError):
        subject_list = {}
    email_id = os.path.basename(path.rstrip("/"))
    return subject_list.get(email_id, "").strip()


def delete_if_expired(path, date_str):
    """Delete the email dir and return True if date_str is an expired closing date."""
    if not date_str:
        return False
    try:
        if expired_date(date_str):
            print(f"\n{os.path.basename(path.rstrip('/'))}: DELETING - date {date_str} expired")
            shutil.rmtree(path)
            return True
    except Exception as e:
        print(f"\n{os.path.basename(path.rstrip('/'))}: WARNING - could not check expiry for '{date_str}': {e}")
    return False


def read_email_body(path):
    """Return the saved email body text, or '' (written by download_emails for no-attachment emails)."""
    body_file = os.path.join(path, "body.txt")
    try:
        with open(body_file, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def extract_website_link(text):
    """Return a participation website link from the body, or '' (e.g. consultant pages like infinityenv.co.za/...)."""
    if not text:
        return ""
    # prefer an explicit "Website:" line, otherwise any URL
    match = re.search(r"Website:\s*(\S+)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"(https?://\S+|www\.\S+)", text, re.IGNORECASE)
    if not match:
        return ""
    link = match.group(1).rstrip(".,);")
    # body may contain a markdown/HTML hyperlink like **[www.example.co.za/path](https://redirect-url)
    # prefer the display text when it looks like a real domain URL
    md_match = re.match(r'\*{0,2}\[([^\]]+)\]', link)
    if md_match:
        display = md_match.group(1).strip("* ")
        if re.match(r'[\w.-]+\.\w{2,}', display):
            link = display
    if link.lower().startswith("www."):
        link = "https://" + link
    return link


def process_subject_fallback(path):
    """Fallback when an email has no PDF attachments: derive the data from the subject line (and body)."""
    document_data = []

    email_id = os.path.basename(path.rstrip("/"))
    subject = get_email_subject(path)
    if not subject:
        print(f"\n{email_id}: no subject found in cache")
        return document_data

    body = read_email_body(path)

    # closing date from the subject, else the body
    closing_date = extract_closing_date_from_text(subject) or extract_closing_date_from_text(body)
    if delete_if_expired(path, closing_date):
        return []

    # address from the subject, falling back to the body
    address = ai_extract_address(f"{subject}\n{body}".strip(), path)
    address = format_address(address)
    title = address.split(",")[0].strip()
    if not title:
        # no address extracted — derive title from the subject by stripping common preambles
        title = re.sub(r'^(notification of public participation[:\s\-]*|w77\s*\|\s*)', '', subject, flags=re.IGNORECASE).strip()
        title = title[:100]

    # description: summarise the subject for context
    description = ai_summarise_text(subject, email_id) if subject else subject

    # prefer a participation website link from the body; otherwise upload any real attachments
    website = extract_website_link(body)
    if website:
        file_link = website
    else:
        attachments = [
            f for f in os.listdir(path)
            if os.path.isfile(os.path.join(path, f)) and f != "body.txt"
        ]
        file_link = upload_files(path, "Notice", address) if attachments else ""

    document_data.append({
        "filename": subject,
        "address": address,
        "title": title,
        "description": description,
        "closing_date": closing_date,
        "file_link": file_link,
    })
    print(f"\n{subject}:")
    print(f"    Title:       {title}")
    print(f"    Address:     {address}")
    print(f"    Description: {description}")
    print(f"    Link:        {file_link}")

    return document_data


def extract_closing_date_from_text(text):
    """Find a '<day> <Month> <year>' date in free text, return camel-cased or ''."""
    date_pattern = re.compile(
        r'\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{4})\b',
        re.IGNORECASE,
    )
    match = date_pattern.search(text)
    return camel_case_word(match.group(1)) if match else ""


def expired_date(date_str: str, days=10) -> bool:
    """ Check if the string date is more than 10 days in the past """
    formats_with_year = ["%d %b %Y", "%d %B %Y"]
    formats_without_year = ["%d %b", "%d %B"]

    date = None
    for fmt in formats_with_year:
        try:
            date = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue

    if date is None:
        for fmt in formats_without_year:
            try:
                date = datetime.strptime(date_str, fmt).replace(year=datetime.now().year)
                break
            except ValueError:
                continue

    if date is None:
        raise ValueError(f"Invalid date format: {date_str}")

    return datetime.now() - date > timedelta(days=days)


def extract_address(pages, attempt=0):
    """
    Get the address from the pdf page.
    Usually in the format 'Description and physical address', but some documents
    (e.g. billboard/signage applications) instead embed it in a heading like:
    'APPLICATION TO ERECT ... AT ERF: 148638, 7 ADDERLEY STREET, FORESHORE'
    """
    if attempt >= len(pages):
        return ""

    first_page = pages[attempt]
    words = first_page.extract_words()

    # Group words by top coordinate (lines)
    lines = defaultdict(list)
    for w in words:
        top = round(w["top"], 1)
        lines[top].append((w["x0"], w["text"]))
    sorted_tops = sorted(lines.keys())

    line_texts = {top: " ".join(text for _, text in sorted(lines[top])) for top in sorted_tops}

    # --- Attempt 1: labelled "physical address" style ---
    label_top = None
    for top in sorted_tops:
        line_text = line_texts[top].lower()
        if "and" in line_text and "physical" in line_text and "address" in line_text:
            label_top = top
            break

    if label_top is not None:
        address_lines = []
        for top in sorted_tops:
            if top > label_top:
                line_text = line_texts[top]
                if line_text.strip():
                    address_lines.append(line_text)
                    if any(c.isdigit() for c in line_text):
                        break
        if address_lines:
            return format_address(" ".join(address_lines))

    # --- Attempt 2: "AT ERF: <number>, <address>" embedded in a heading line ---
    erf_start_pattern = re.compile(r'\bAT\s+ERF:?\s*\d+\s*,', re.IGNORECASE)

    for idx, top in enumerate(sorted_tops):
        text = line_texts[top]
        if erf_start_pattern.search(text):
            # Join this line with subsequent lines until we hit a new field/heading
            # (e.g. "APPLICANT:") or run out of lines, to capture wrapped address text
            combined = text
            for next_top in sorted_tops[idx + 1:]:
                next_text = line_texts[next_top]
                # Stop if it looks like a new labelled field (e.g. "APPLICANT:")
                if re.match(r'^[A-Z ]+:', next_text.strip()):
                    break
                # Stop if we've already reached a blank-ish gap (heading ended)
                if not next_text.strip():
                    break
                combined += " " + next_text
                # Stop once we have letters after the erf number (address text found)
                if re.search(r'\bAT\s+ERF:?\s*\d+\s*,\s*[^,]*[A-Za-z]', combined, re.IGNORECASE):
                    break

            match = re.search(r'\bAT\s+ERF:?\s*\d+\s*,\s*(.+)', combined, re.IGNORECASE)
            if match:
                return format_address(match.group(1).strip())

    # --- Try next page if nothing found on this one ---
    if attempt + 1 < len(pages):
        return extract_address(pages, attempt + 1)

    return ""


def format_address(address):
    if not address:
        address = ""
    address = re.sub(r"\(.*?\)", "", address).strip()

    # patch weird formats
    def _patch_addresss(raw_address):
        new_address = re.sub(r'\b(?:AND|&)\b', ',', raw_address, flags=re.IGNORECASE)
        new_address = re.sub(r'\s*\([^)]*\)', '', raw_address)
        new_address = re.sub(r'\s*,\s*', ', ', new_address)
        new_address = re.sub(r'\s+', ' ', new_address).strip()
        match = re.match(r'(\d+)', new_address)
        if match:
            number = match.group(1)
            # Remove numbers before the street that are not part of a range
            new_address = re.sub(r'^[\d,\s]+', number + ' ', new_address)

        parts = new_address.split(', ')
        parts = [camel_case_word(part) for part in parts]
        # add cape town if missing
        if parts[len(parts)-1] != "Cape Town":
            parts.append("Cape Town")
        new_address = ', '.join(parts)

        return new_address

    return _patch_addresss(address)

def extract_description(pages, description_id):
    # Extract description
    # Find top coordinate of "Purpose of the application" up until "Enquiries"
    raw_text = ""
    capture = False

    # multi page descriptions
    for i, page in enumerate(pages):
        # dont go through too many pages
        if i >= 6:
            break
        words = []
        try:
            # Set a 30-second timeout for pdfplumber corrupted pages
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(30)
            
            words = page.extract_words()
            # Cancel the alarm
            signal.alarm(0)
            
        except (TimeoutException, Exception) as e:
            print(f"Error processing {description_id}: {e}")
            continue
            
        page_text = ""
        purpose_top = 0
        for i, w in enumerate(words):
            text = w["text"]

            # Start capture from title format 'Purpose of the application'
            if not capture and text == "Purpose" and i + 3 < len(words):
                next_words = " ".join(w2["text"].lower() for w2 in words[i:i+4])
                if "purpose of the application" in next_words.lower():
                    capture = True
                    purpose_top = w["top"]
                    continue

            # Stop capture at Enquiries
            if capture and text == "Enquiries":
                enquiries_top = w["top"]
                x0, x1 = 50, 500
                y0 = purpose_top + 10
                y1 = enquiries_top - 5
                area = page.within_bbox((x0, y0, x1, y1))
                page_text = area.extract_text() or ""
                raw_text += "\n" + page_text
                capture = False
                break

        # If still capturing and not found "Enquiries", grab whole lower part and end
        if capture:
            x0, x1 = 50, 500
            y0 = purpose_top + 10
            y1 = page.height
            area = page.within_bbox((x0, y0, x1, y1))
            page_text = area.extract_text() or ""
            raw_text += "\n" + page_text
            purpose_top = 0  # reset top for next page

    # clean up
    # Remove newlines
    raw_text = raw_text.replace('\n', '. ')
    raw_text = re.sub(r'“.*?”', '', raw_text, flags=re.DOTALL)
    raw_text = raw_text.replace(':.', ':')
    raw_text = re.sub(r'Viewing of Application Documents.*', '', raw_text, flags=re.DOTALL)

    # Remove everything in round () and square [] brackets
    description = re.sub(r'\[.*?\]|\(.*?\)', '', raw_text)
    # remove urls
    description = re.sub(r'\bwww\.\S+', '', description, flags=re.IGNORECASE)
    description = re.sub(r'No\.T\d+/\d+', '', description)

    # Collapse multiple spaces
    description = re.sub(r'\s+', ' ', description).strip()
    description = description.replace(". progress possible. T", "")
    description = description.replace(". Making progress possible. T", "")
    description = description.replace(". .", ".")
    description = description.replace(". .", ".")
    description = description.replace("..", ".")
    description = description.replace("..", ".")

    if description:
        # ai summary
        description = ai_summarise_text(description, description_id)

    return description

def extract_closing_date(pages):
    date_pattern = re.compile(
        r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b',
        re.IGNORECASE
    )
    on_or_before_pattern = re.compile(
        r'on\s+or\s+before\s+(' + date_pattern.pattern + r')',
        re.IGNORECASE
    )
    working_days_pattern = re.compile(
        r'(\d+)\s+working\s+days',
        re.IGNORECASE
    )

    for page in pages:
        words = page.extract_words()

        # Find the top coordinate of "Closing date"
        closing_top = None
        for i, w in enumerate(words):
            if w['text'] == "Closing":
                if i + 1 < len(words) and words[i + 1]['text'] == "date":
                    closing_top = w['top']
                    break

        if closing_top is None:
            continue

        # Collect all words in a wider band below "Closing date" (up to ~80px)
        # This handles multi-line labels before the actual date value
        nearby_words = [w for w in words if closing_top + 10 < w['top'] < closing_top + 80]

        # Group nearby words by line (words within 5px vertically = same line)
        lines = []
        for w in nearby_words:
            placed = False
            for line in lines:
                if abs(line[0]['top'] - w['top']) < 5:
                    line.append(w)
                    placed = True
                    break
            if not placed:
                lines.append([w])

        # Find the first line that looks like a date
        for line in lines:
            line_text = " ".join(w['text'] for w in line).strip()
            if date_pattern.search(line_text):
                return camel_case_word(line_text)

    # Fallback: scan full page text for "on or before <date>" (memo-style documents)
    for page in pages:
        text = page.extract_text() or ""
        match = on_or_before_pattern.search(text)
        if match:
            return camel_case_word(match.group(1))

    # Fallback 2: no explicit closing date — compute from header "Date:" + N working days
    for page in pages:
        text = page.extract_text() or ""
        wd_match = working_days_pattern.search(text)
        if wd_match:
            num_days = int(wd_match.group(1))
            header_date = extract_header_date(pages, date_pattern)
            if header_date:
                closing = add_working_days(header_date, num_days)
                return camel_case_word(closing.strftime("%d %B %Y"))


def extract_header_date(pages, date_pattern):
    """
    Look for a labelled 'Date:' field near the top of the first page
    (e.g. 'Date: 10 July 2026') and return it as a datetime object.
    """
    labelled_date_pattern = re.compile(
        r'Date\s*:?\s*(' + date_pattern.pattern + r')',
        re.IGNORECASE
    )

    if not pages:
        return None

    first_page = pages[0]
    text = first_page.extract_text() or ""

    match = labelled_date_pattern.search(text)
    if match:
        day, month, year = match.group(2), match.group(3), match.group(4)
        try:
            return datetime.strptime(f"{day} {month} {year}", "%d %B %Y")
        except ValueError:
            return None
    return None


def add_working_days(start_date, num_days):
    """Add N working days (Mon-Fri) to a date, excluding weekends only."""
    current = start_date
    added = 0
    while added < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    return current


def camel_case_word(words):
    """ Camel case the words """
    return ' '.join(w.capitalize() for w in words.lower().split())


def process_all_attachments(directory):
    """ loop through the emails in the directory and extract the information from the files """

    data = []
    for email_id in os.listdir(directory):
        full_path = os.path.join(directory, email_id)
        if os.path.isdir(full_path):
            result = process_documents(full_path)
            data.extend(result)

    print(f"Got {len(data)} {directory} items")
    return data