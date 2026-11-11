"""Fallback: fetch email attachments from Gmail when the HubSpot download fails"""

import os
import base64
import datetime
from upload_gdrive import authenticate

_service = None


def _gmail():
    global _service
    if _service is None:
        _service = authenticate("gmail", "v1")
    return _service


def _find_message(service, subject, timestamp):
    """Return the id of the Gmail message with this subject closest in time to the HubSpot timestamp."""
    window = datetime.timedelta(days=1)
    query = (
        f'subject:"{subject.replace(chr(34), "")}" has:attachment '
        f"after:{int((timestamp - window).timestamp())} before:{int((timestamp + window).timestamp())}"
    )
    messages = service.users().messages().list(userId="me", q=query, maxResults=10).execute().get("messages", [])

    best = None
    for m in messages:
        meta = service.users().messages().get(userId="me", id=m["id"], format="minimal").execute()
        delta = abs(int(meta["internalDate"]) / 1000 - timestamp.timestamp())
        if best is None or delta < best[0]:
            best = (delta, m["id"])
    return best[1] if best else None


def _attachment_parts(part):
    headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    # skip signature logos etc.
    inline = headers.get("content-disposition", "").lower().startswith("inline")
    if part.get("filename") and not inline:
        yield part
    for p in part.get("parts", []):
        yield from _attachment_parts(p)


def download_gmail_attachments(subject, timestamp, email_dir):
    """Save attachments of the matching Gmail message that are missing from email_dir, return all its attachment paths."""
    service = _gmail()
    msg_id = _find_message(service, subject, timestamp)
    if not msg_id:
        print(f"  → Gmail: no message found for '{subject}'")
        return []

    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    os.makedirs(email_dir, exist_ok=True)
    paths = []
    for part in _attachment_parts(msg["payload"]):
        path = os.path.join(email_dir, os.path.basename(part["filename"]))
        paths.append(path)
        if os.path.exists(path):
            continue
        data = part["body"].get("data")
        if not data:
            data = service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=part["body"]["attachmentId"]
            ).execute()["data"]
        with open(path, "wb") as out:
            out.write(base64.urlsafe_b64decode(data))
        print(f"  → Gmail: downloaded {path}")
    return paths
