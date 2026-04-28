from export_map_data import export_to_kmz, export_to_map_csv
from process_documents import process_all_attachments
from process_events_documents import process_all_events
from download_emails import list_emails, NOTICE_DIR, PUBLIC_DIR, EVENTS_DIR
from upload_gdrive import upload_kmz_layers

if __name__ == "__main__":
    # list the hubspot emails
    list_emails()

    # extract info from noticeboard attachments
    notice_data = process_all_attachments(NOTICE_DIR)

    # extract info from public participation attachments
    public_data = process_all_attachments(PUBLIC_DIR)

    # extract info from events emails (parsed from subject line, no AI)
    events_data = process_all_events(EVENTS_DIR)

    # export each category as a separate KMZ layer
    notice_kmz, public_kmz, events_kmz = export_to_kmz(notice_data, public_data, events_data)

    # upload KMZ layers to Drive (overwrites same file ID so embedded URLs stay stable)
    upload_kmz_layers(notice_kmz, public_kmz, events_kmz)

    # also export individual CSVs
    export_to_map_csv("notice", notice_data)
    export_to_map_csv("public", public_data)
    export_to_map_csv("events", events_data)
