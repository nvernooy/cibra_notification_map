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
import pathlib
import requests
from datetime import datetime

# folder to create new folders under
PARENT_FOLDER_ID = os.environ.get("PARENT_FOLDER_ID")
SCOPES = ["https://www.googleapis.com/auth/drive"]
CACHE_FILE = "short_links.json"


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
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
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
    # Check if file already exists in folder
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        file_id = files[0]["id"]
        return file_id

    file_metadata = {"name": file_name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, resumable=True)

    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name")
        .execute()
    )

    return file.get("id")


def load_cache():
    """Load the generated tinyurl links for folders"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    """Save the generated tinyurl links for folders"""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def shorten_link(link):
    """Shorten the link to the gdive folder using tinyurl"""

    # free tier only allows 100 urls a month
    cache = load_cache()
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
    save_cache(cache)

    return short_url


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
    # Authenticate
    service = authenticate()

    # Create folder in Google Drive
    folder_id = create_folder(service, folder_name)

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

    print(f"\nUploading {len(files)} files... ", end="")
    for file_name in files:
        file_path = os.path.join(local_folder_path, file_name)
        try:
            upload_file(service, file_path, folder_id)
        except Exception as e:
            print(f"Error uploading {file_name}: {str(e)}")

    print(f"Done {local_folder_path}")
    return make_public_link(service, folder_id)
