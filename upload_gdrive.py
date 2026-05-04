"""Upload all the files in a folder to google gdrive with a folder name and return the link"""

import os
import pickle
import json
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2 import service_account
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
import pathlib
import requests
from datetime import datetime

# folder to create new folders under
PARENT_FOLDER_ID = os.environ.get("PARENT_FOLDER_ID")
# folder to store the KMZ map layers (stable file IDs for embedding)
KMZ_FOLDER_ID = os.environ.get("KMZ_FOLDER_ID")
SCOPES = ["https://www.googleapis.com/auth/drive"]
SHORT_LINKS_CACHE_FILE = "short_links.json"
FOLDER_CACHE_FILE = "folder_links.json"


def authenticate():
    """Authenticate using OAuth (works with token file for headless)."""
    creds = None
    # token.pickle stores the user's access and refresh tokens
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # If there are no valid credentials, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                with open("token.pickle", "wb") as token:
                    pickle.dump(creds, token)
            except RefreshError as e:
                print(f"Token expired - please rerun the script and log in again")
                os.remove("token.pickle")
                raise
            except Exception as e:
                print(f"Error refreshing token: {e}")
                os.remove("token.pickle")
                raise
        else:
            # This requires a browser
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open("token.pickle", "wb") as token:
                pickle.dump(creds, token)

    return build("drive", "v3", credentials=creds)


def create_folder(service, folder_name, parent_id=None):
    """Create a folder in Google Drive if it doesn't already exist."""
    escaped_name = folder_name.replace("\\", "\\\\").replace("'", "\\'")
    query = f"name = '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])

    if folders:
        folder_id = folders[0]["id"]
        return folder_id
    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        file_metadata["parents"] = [parent_id]

    folder = service.files().create(body=file_metadata, fields="id, name").execute()
    return folder.get("id")


def make_public_link(service, folder_id, role="reader"):
    """
    Make the folder accessible to anyone with the link.

    Args:
        service: Google Drive service instance
        folder_id: ID of the folder to share
        role: 'reader' (view only) or 'writer' (can edit)
    """

    permission = {"type": "anyone", "role": role}
    service.permissions().create(
        fileId=folder_id, body=permission, fields="id"
    ).execute()

    link = f"https://drive.google.com/drive/folders/{folder_id}"
    public_link = shorten_link(link)
    # return the generated link
    return public_link


def upload_file(service, file_path, folder_id):
    """Upload a file to Google Drive if it doesn't already exist in the folder."""

    file_name = os.path.basename(file_path)
    escaped_name = file_name.replace("\\", "\\\\").replace("'", "\\'")
    # Check if file already exists in folder
    query = f"name = '{escaped_name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    # exist early
    if files:
        return

    file_metadata = {"name": file_name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, resumable=True)

    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name")
        .execute()
    )

    return file.get("id")


def load_cache(cache_file):
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache, cache_file):
    with open(cache_file, "w") as f:
        json.dump(cache, f, indent=2)


def shorten_link(link):
    """Shorten the link to the gdive folder using tinyurl"""

    # free tier only allows 100 urls a month
    cache = load_cache(SHORT_LINKS_CACHE_FILE)
    if link in cache:
        return cache[link]

    api_key = os.environ["TINY_URL_TOKEN"]
    url = "https://api.tinyurl.com/create"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"url": link, "domain": "tinyurl.com"}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    short_url = response.json()["data"]["tiny_url"]

    cache[link] = short_url
    save_cache(cache, SHORT_LINKS_CACHE_FILE)

    return short_url


def upsert_kmz_layer(service, file_path, upload_name, folder_id):
    """Upload a KMZ file to Drive, overwriting if it already exists (keeps same file ID/URL)."""
    query = f"name = '{upload_name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    media = MediaFileUpload(file_path, mimetype="application/vnd.google-earth.kmz", resumable=True)

    if files:
        file_id = files[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"Updated {upload_name} (id: {file_id})")
        return file_id
    else:
        file_metadata = {"name": upload_name, "parents": [folder_id]}
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        file_id = file.get("id")
        # make publicly readable so KmlLayer can fetch it
        service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"}, fields="id"
        ).execute()
        print(f"Created {upload_name} (id: {file_id})")
        return file_id


def upload_kmz_layers(notice_kmz, public_kmz, events_kmz):
    """Upsert all three KMZ layers to the stable Drive folder."""
    if not KMZ_FOLDER_ID:
        print("KMZ_FOLDER_ID not set — skipping KMZ upload")
        return

    service = authenticate()
    for file_path, name in [
        (notice_kmz, "notice.kmz"),
        (public_kmz, "public.kmz"),
        (events_kmz, "events.kmz"),
    ]:
        upsert_kmz_layer(service, file_path, name, KMZ_FOLDER_ID)


def upload_files(local_folder_path, pdf_file, address):
    """Create a folder in Google Drive and upload all files from local folder."""

    # build the google drive folder name
    title = pdf_file
    suburb = ""
    address_parts = address.split(",") if address else []
    if address_parts:
        title = address_parts[0].strip()
    if len(address_parts) > 1:
        suburb = address_parts[1].strip()

    today = datetime.now().strftime("(%d%b%y)")
    folder_name = f"{title} {today}"
    if suburb:
        folder_name = f"{suburb} - {folder_name}"

    cache = load_cache(FOLDER_CACHE_FILE)
    if folder_name in cache:
        return cache[folder_name]

    # Authenticate
    service = authenticate()

    # Create folder in Google Drive
    folder_id = create_folder(service, folder_name, PARENT_FOLDER_ID)

    # Upload all files from local folder
    if not os.path.exists(local_folder_path):
        print(f"Error: Local folder '{local_folder_path}' does not exist.")
        return

    files = [
        f
        for f in os.listdir(local_folder_path)
        if os.path.isfile(os.path.join(local_folder_path, f))
    ]

    if not files:
        print(f"No files found in '{local_folder_path}'")
        return

    print(f"Uploading {len(files)} files... ", end="")
    for file_name in files:
        file_path = os.path.join(local_folder_path, file_name)
        try:
            resp = upload_file(service, file_path, folder_id)
            # file exists or other error, continue
            if not resp:
                break
        except Exception as e:
            print(f"Error uploading {file_name}: {str(e)}")

    print(f"Done {local_folder_path}")
    link = make_public_link(service, folder_id)
    cache[folder_name] = link
    save_cache(cache, FOLDER_CACHE_FILE)
    return link
