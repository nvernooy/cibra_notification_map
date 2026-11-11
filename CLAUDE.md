# CIBRA Notification Map

Pulls City of Cape Town notification emails from HubSpot, extracts address, description and closing date from the attachments, uploads the source docs to Google Drive, and exports CSVs that are imported manually into Google MyMaps.

## Rules
- Files matched by `.gitignore` are off-limits: don't read, edit, create or delete them without asking first. That covers secrets (`.env`, `credentials.json`, `*service-account*.json`, `token.pickle`), the JSON caches, the email download dirs and the generated CSV/KMZ output.
- Don't run `main.py`, `cibra_notification_map.sh` or any module that calls external APIs. A run hits HubSpot, Gemini, Google Drive and TinyURL, writes to the caches, and deletes expired email dirs. Give the user the command to run instead.
- Don't merge or push. The user handles both.

## Pipeline (`main.py`)
1. `download_emails.list_emails`: fetches HubSpot emails newer than the hardcoded `cuttoff_*` date and sorts them by subject regex into `emails/` (noticeboard), `public_part_emails/` and `events_emails/`, one dir per email ID. Dirs that already exist are skipped.
2. `process_documents.process_all_attachments`: parses PDFs with pdfplumber (OCR fallback via pytesseract) and falls back to the email subject and body. Gemini is used for summaries (`ai_summarise_descriptions`) and as a fallback for addresses (`ai_extract_address`). Email dirs whose closing date has passed are deleted (`delete_if_expired`). Source files are uploaded to one Drive folder per email (tagged with the email ID in `appProperties`) under `NOTICE_FOLDER_ID`, `PUBLIC_FOLDER_ID` or `EVENTS_FOLDER_ID` depending on the local dir, and the link is shortened with TinyURL. `PARENT_FOLDER_ID` is the old shared folder; existing folders in it are reused and left in place.
3. `process_events_documents.process_all_events`: events are parsed from the subject line only. Venues map to addresses through `VENUE_LOOKUP`.
4. `export_map_data.export_to_map_csv`: writes `{notice,public,events}_<date>.csv`.

KMZ export and upload to Drive (`export_to_kmz`, `upload_kmz_layers`) is disabled in `main.py`. Automating the MyMaps upload didn't work, so the CSVs are uploaded by hand.

## Caches (gitignored, persist between runs)
- `email_subject.json`: email ID to subject.
- `addresses.json`, `summaries.json`: Gemini results.
- `folder_links.json`, `short_links.json`: Drive folders and short links.

## Environment
- `.env` is sourced by `cibra_notification_map.sh`. See `.env.example` for keys.
- Google Drive uses OAuth desktop credentials (`credentials.json`, which produces `token.pickle`). The first auth needs a browser.
- Python venv in `venv/`. Dependencies are in `requirements.txt`.
