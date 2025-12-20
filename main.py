from export_map_data import export_to_map_csv
from process_documents import process_documents, process_all_attachments
from download_emails import list_emails, NOTICE_DIR, PUBLIC_DIR

if __name__ == "__main__":
    # list the hubspot emails
    list_emails()

    # extract info from noticeboard attachments
    document_data = process_all_attachments(NOTICE_DIR)
    # export email data to csv map data
    export_to_map_csv("notice", document_data)

    # extract info from public participation attachments
    document_data = process_all_attachments(PUBLIC_DIR)
    # export email data to csv map data
    export_to_map_csv("public", document_data)
