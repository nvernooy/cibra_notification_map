from export_map_data import export_to_map_csv
from download_emails import list_emails

if __name__ == "__main__":
    # list the hubspot emails
    list_emails()
    # export email data to csv map data
    export_to_map_csv()
