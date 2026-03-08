import pdfplumber
import re
import os
import json
from pathlib import Path
from upload_gdrive import upload_files
from download_emails import CACHE_FILE
from collections import defaultdict
from ai_summarise_descriptions import ai_summarise_text
from ai_extract_address import ai_extract_address
from datetime import datetime, timedelta
import signal
import shutil

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

    for pdf_file in documents_path.glob("*.pdf"):
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
                elif expired_date(closing_date):
                    # check if closing date far in the past
                    print(f"\n{pdf_file.name}: closing date {closing_date} expired - deleting")
                    shutil.rmtree(documents_path)
                    return []

                # Extract address
                address = extract_address(pages)
                if not address:
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
                print(f"\n{pdf_file.name}:")
                print(f"    Title:       {title}")
                print(f"    Description: {description}")
                break


    # TODO refine
    # if no info found in attachments process the subject line
    if not document_data:
        document_data = process_subject_line(path)

    return document_data


def expired_date(date_str: str, days=10) -> bool:
    """ Check if the string date is more than 10 days in the past """
    formats = ["%d %b %Y", "%d %B %Y"]
    
    for fmt in formats:
        try:
            date = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Invalid date format: {date_str}")

    return datetime.now() - date > timedelta(days=days)


def extract_address(pages, attempt=0):
    """ 
    Get the address from  the pdf page
    Usually in the format 'Description and physical address'
    """
    # check first page and second page
    first_page = pages[attempt]
    words = first_page.extract_words()

    # Group words by top coordinate (lines)
    lines = defaultdict(list)
    for w in words:
        top = round(w["top"], 1)
        lines[top].append((w["x0"], w["text"]))
    sorted_tops = sorted(lines.keys())

    # Find the label line
    label_top = None
    for top in sorted_tops:
        line_text = " ".join(text for _, text in sorted(lines[top]))
        # in format Description and physical address, sometimes just physical address
        if "and" in line_text.lower() and "physical" in line_text.lower() and "address" in line_text.lower():
            label_top = top
            break

    # try the second page
    if label_top is None: 
        if len(pages) < (attempt + 1):
            return extract_address(pages, attempt + 1)
        else:
            return ""

    # Find the next non-empty line(s) below the label
    address_lines = []
    for top in sorted_tops:
        if top > label_top:
            line_text = " ".join(text for _, text in sorted(lines[top]))
            if line_text.strip():
                address_lines.append(line_text)
                # Stop after first line with numbers (street number)
                if any(c.isdigit() for c in line_text):
                    break

    address =  " ".join(address_lines) if address_lines else ""
    return format_address(address)

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
            y0 = purpose_top + 10 if "purpose_top" in locals() else 0
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

    # Extract closing date, can be on any page
    for page in pages:
        words = page.extract_words()
        
        # Find the top coordinate of "Closing"
        closing_top = None
        for i, w in enumerate(words):
            if w['text'] == "Closing":
                # check if next word exists and is "date" (case-insensitive)
                if i + 1 < len(words) and words[i + 1]['text'] == "date":
                    closing_top = w['top']
                    break

        if closing_top:
            # Select words slightly below the "Closing" line
            line_words = [w['text'] for w in words if closing_top + 15 < w['top'] < closing_top + 35]
            close_date = " ".join(line_words)
            close_date = close_date.strip()
            if close_date:
                return camel_case_word(close_date)

    return ""

def camel_case_word(words):
    """ Camel case the words """
    return ' '.join(w.capitalize() for w in words.lower().split())


def process_subject_line(path):
    """ Get info from the email subject line """

    subject_list = {}
    with open(CACHE_FILE, "r") as f:
        subject_list = json.load(f)

    email_id = os.path.basename(path)
    subject = subject_list[email_id]
    address = ai_extract_address(subject, email_id)
    address = format_address(address)
    
    # format description from subject line
    description = re.sub(r'^.*? - |\s*\(.*\)$', '', subject).strip()
    # format title
    title = re.sub(r'\s*-[^-]*$', '', description).strip()

    pattern = r"\b\d{1,2}(?:st|nd|rd|th)?(?:\s?[-–—]\s?\d{1,2}(?:st|nd|rd|th)?)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+\d{4})?\b"
    match = re.search(pattern, subject, re.IGNORECASE)
    closing_date = match and match.group()

    # upload all the attachments from the email to the google drive
    file_link = upload_files(path, "Events Permit", address)
    document_data = []
    document_data.append({
        "filename": subject,
        "address": address,
        "title": title,
        "description": description,
        "closing_date": closing_date,
        "file_link": file_link
    })
    print(f"\n{subject}:")
    print(f"    Title:       {title}")
    print(f"    Description: {description}")
    return document_data


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