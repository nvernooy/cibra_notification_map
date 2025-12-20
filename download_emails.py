"""Fetch emails from hubspot and download attachments"""

import os
import re
import requests
import datetime
import zipfile

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_APP_TOKEN")
NOTICE_DIR = "emails"
os.makedirs(NOTICE_DIR, exist_ok=True)
PUBLIC_DIR = "public_part_emails"
os.makedirs(PUBLIC_DIR, exist_ok=True)

# date from when to find emails
cuttoff_year = 2025
cuttoff_month = 10
cuttoff_day = 25

url = "https://api.hubapi.com/crm/v3/objects/emails"

headers = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}


def list_emails():
    """Use hubspot api to find emails matching filters"""
    emails = []
    cutoff = datetime.datetime(
        cuttoff_year, cuttoff_month, cuttoff_day, tzinfo=datetime.timezone.utc
    )
    cutoff_ts = int(cutoff.timestamp() * 1000)
    after = None

    while True:
        # Use filterGroups to only fetch emails after the cutoff date
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hs_timestamp",
                            "operator": "GTE",
                            "value": str(cutoff_ts),
                        },
                    ]
                }
            ],
            "limit": 100,
            "properties": [
                "hs_email_subject",
                "hs_email_text",
                "hs_email_from",
                "hs_email_sender_email",
                "hs_timestamp",
                "hs_attachment_ids",
                "hs_email_to_email",
                "hs_email_html",
            ],  # properties set data to return
            "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}],
        }
        if after:
            payload["after"] = after

        r = requests.post(url + "/search", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

        for e in data.get("results", []):
            ts = datetime.datetime.fromisoformat(
                e["properties"]["hs_timestamp"].replace("Z", "+00:00")
            )
            emails.append(e)

        if "paging" not in data or "next" not in data["paging"]:
            break

        # next page
        after = data["paging"]["next"]["after"]

    # further filter emails to match on subject
    for email in emails:
        props = email["properties"]
        subject = props.get("hs_email_subject", "") or ""
        subject = subject.strip()
        reciever = props.get("hs_email_to_email")
        sender = props.get("hs_email_sender_email") or ""

        if (
            "fwd" in subject.lower()
            or "fw:" in subject.lower()
            or "re:" in subject.lower()
            or "automatic reply" in subject.lower()
            or "panel application" in subject.lower()
            or subject.lower().startswith("form")
        ):
            continue
        # TODO send events to lisa
        if re.search(r"^E[A-Z]?\d+-\d+\b", subject):
            continue
        # TODO send panel to panel
        if reciever == "panel@cibra.co.za":
            continue

        # hs_email_sender_email is forwarding email
        # if "capetown.gov.za" not in sender.lower():
        #     print(f"skipping sender: {sender}, subject: {subject}")
        #     continue

        # public participation emails - process seperately
        if (re.search(r"public\s+participation|consultation", subject, re.IGNORECASE) or re.search(r"W77", subject, re.IGNORECASE)):
            download_public_participation(email, subject)
            continue

        # city notice emails for noticeboard
        has_notice = re.search(r"notice", subject, re.IGNORECASE) 
        has_erf = re.search(r"erf\s+\d+", subject, re.IGNORECASE)
        has_case = re.search(r"case\s+\d+", subject, re.IGNORECASE)
        has_land_use = re.search(r"land\s+use", subject, re.IGNORECASE)
        if not (has_notice or has_land_use or (has_erf and has_case)):
            # print(f"\tskipping: {subject}")
            continue

        download_notices(email, subject)


def download_public_participation(email, subject):
    email_id = email["id"]
    print(f"Matched Participation Email {email_id}: {subject}")

    try:
        # download the attachments
        extract_urls(email, PUBLIC_DIR)
    except Exception as e:
        print(f"Error downloading from {subject}")
        import traceback
        traceback.print_exc()


def download_notices(email, subject):
    email_id = email["id"]
    print(f"Matched Notice Email {email_id}: {subject}")

    try:
        # download the attachments
        extract_urls(email, NOTICE_DIR)
    except Exception as e:
        print(f"Error downloading from {subject}", e)


def extract_urls(email, directory):
    """Get the attachment urls from the email body or the attachment files"""
    email_text = email["properties"].get("hs_email_text")
    if not email_text:
        email_text = email["properties"].get("hs_email_html") or ""
    email_id = email["id"]
    email_dir = os.path.join(directory, email_id)

    # Check if directory already exists - dont download again
    if os.path.exists(email_dir):
        return

    # Extract only the BigFilesAccess download URL if it exists in the text
    zip_url_match = re.search(
        r"https://web1\.capetown\.gov\.za/web1/BigFilesAccess/DownloadBigFile\.aspx\?file=[a-f0-9\-]+",
        email_text,
    )
    if zip_url_match:
        url = zip_url_match.group(0)
        try:
            file_res = requests.get(url)
            file_res.raise_for_status()

            os.makedirs(email_dir, exist_ok=True)
            # download zip file
            filename = os.path.join(email_dir, f"attachments.zip")

            with open(filename, "wb") as out:
                out.write(file_res.content)
            print(f"  → Downloaded {filename}")
            # extract zip file
            unzip_files(f"{email_dir}/attachments.zip")
            return
        except Exception as e:
            print(f"  → Failed to download {url}: {e}")
    
    # fallback - try downloading attachments on email
    if email["properties"].get("hs_attachment_ids"):
        attachment_ids = email["properties"]["hs_attachment_ids"].split(";")

        for fid in attachment_ids:
            file_id = fid.strip()
            if not file_id:
                continue

            # Get file metadata and signed URL
            try:
                res = requests.get(
                    f"https://api.hubapi.com/files/v3/files/{file_id}/signed-url",
                    headers=headers,
                )
                res.raise_for_status()
                data = res.json()
                url = data.get("url")
                name = data.get("name", f"file_{file_id}")
                filename = f'{name}.{data.get("extension", "pdf")}'

                if not url:
                    print(f"  → No signed URL for {file_id}")
                    continue

                # Download file
                f_res = requests.get(url)
                f_res.raise_for_status()
                # Create email-specific directory
                os.makedirs(email_dir, exist_ok=True)
                filename = os.path.join(email_dir, filename)

                with open(filename, "wb") as out:
                    out.write(f_res.content)
                print(f"  → Downloaded {name}")
            except requests.exceptions.HTTPError as err:
                print(f"  → Failed to download file {file_id}: {err}")
                continue


def unzip_files(filename):
    """Unzip downloaded zip file"""
    if not os.path.exists(filename):
        return

    extract_dir = os.path.dirname(filename)
    with zipfile.ZipFile(filename, "r") as z:
        members = [m for m in z.namelist() if m and m.strip()]
        if not members:
            return

        # Determine if the archive has a single top-level directory
        first_components = {m.split("/", 1)[0] for m in members}
        strip_top_level = False
        top_level = None
        if len(first_components) == 1:
            top_level = next(iter(first_components))
            # if the top_level entry corresponds to a bare file (no '/'), don't strip
            # we only strip when members are inside that top-level dir (i.e., contain '/')
            if any("/" in m for m in members):
                strip_top_level = True

        # Build list of target paths (after optional stripping) and check if already present
        targets = []
        for m in members:
            target_rel = m
            if strip_top_level:
                # remove leading "top_level/" prefix
                if m.startswith(top_level + "/"):
                    target_rel = m[len(top_level) + 1 :]
                else:
                    # unexpected - keep as-is
                    target_rel = m
            if not target_rel:
                continue
            target_path = os.path.normpath(os.path.join(extract_dir, target_rel))
            targets.append(target_path)

        # If any of the targets already exist, assume archive already extracted -> do nothing
        if any(os.path.exists(t) for t in targets):
            return

        # Safe extraction: avoid zip-slip by validating final path starts with extract_dir
        for zi in z.infolist():
            m = zi.filename
            if not m or not m.strip():
                continue

            if strip_top_level and m.startswith(top_level + "/"):
                m_rel = m[len(top_level) + 1 :]
            else:
                m_rel = m

            if not m_rel:
                # this was the top-level directory entry; skip
                continue

            dest_path = os.path.normpath(os.path.join(extract_dir, m_rel))
            if not dest_path.startswith(
                os.path.normpath(extract_dir) + os.sep
            ) and dest_path != os.path.normpath(extract_dir):
                # unsafe path (zip-slip) - skip
                continue

            if zi.is_dir():
                os.makedirs(dest_path, exist_ok=True)
                continue

            # ensure parent dir exists
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            # write file from archive to destination
            with z.open(zi, "r") as src, open(dest_path, "wb") as dst:
                while True:
                    chunk = src.read(8192)
                    if not chunk:
                        break
                    dst.write(chunk)


if __name__ == "__main__":
    list_emails()
