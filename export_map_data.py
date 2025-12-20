"""Export map json data to kml or csv format for google my maps"""

import csv
from address_to_pin import get_coordinates
from datetime import date
from xml.sax.saxutils import escape

kml_header = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>map_points_2025-10-19.kml</name>
    <Style id="icon-1502-0F9D58-normal">
      <IconStyle>
        <color>ff589d0f</color>
        <scale>1</scale>
        <Icon>
          <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>0</scale>
      </LabelStyle>
    </Style>
    <Style id="icon-1502-0F9D58-highlight">
      <IconStyle>
        <color>ff589d0f</color>
        <scale>1</scale>
        <Icon>
          <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>1</scale>
      </LabelStyle>
    </Style>
    <StyleMap id="icon-1502-0F9D58">
      <Pair>
        <key>normal</key>
        <styleUrl>#icon-1502-0F9D58-normal</styleUrl>
      </Pair>
      <Pair>
        <key>highlight</key>
        <styleUrl>#icon-1502-0F9D58-highlight</styleUrl>
      </Pair>
    </StyleMap>
"""

kml_footer = "</Document>\n</kml>"


def export_to_map1_kml():
    """Export map data in kml format"""
    document_data = process_all_attachments()
    map_data = []
    kml_filename = f"map_points_{date.today().isoformat()}.kml"

    with open(kml_filename, "w", encoding="utf-8") as f:
        f.write(kml_header)

        for item in document_data:
            if not item.get("address"):
                # do not process emails without address
                print("ERROR no address", item)
                continue
            # Format description with newline between items and clickable link
            description_lines = [
                escape(item.get("description", "")),
                f"Close date: {escape(item.get('closing_date', ''))}",
                f'<a href="{escape(item.get("file_link", ""))}">View Application</a>',
            ]
            description_html = "<br/>".join(description_lines)

            extended_description = (
                f'{escape(item.get("description", ""))}\n'
                f'Close date: {escape(item.get("closing_date", ""))}\n'
                f'View Application: {escape(item.get("file_link", ""))}'
            )

            kml_entry = f"""
                    <Placemark>
                    <name>{item['title']}</name>
                    <address>{escape(item['address'])}</address>
                    <description><![CDATA[{description_html}<br>address: {escape(item['address'])}]]></description>
                    <styleUrl>#icon-1502-0F9D58</styleUrl> 
                    <ExtendedData>
                        <Data name="description">
                        <value><![CDATA[{extended_description}]]></value>
                        </Data>
                        <Data name="address">
                        <value>{escape(item['address'])}</value>
                        </Data>
                    </ExtendedData>
                    </Placemark>
                """

            f.write(kml_entry)
        f.write(kml_footer)

    print(f"Map saved to {kml_filename}")


def export_to_map_csv(filename, document_data):
    """Export map data as csv"""

    csv_filename = f"{filename}_{date.today().isoformat()}.csv"
    # Define the CSV headers.
    csv_headers = ["Address", "Title", "Description", "Closing Date", "View Application"]

    with open(csv_filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)

        for item in document_data:
            if not item.get("address"):
                # do not process points without addresses
                print("ERROR no address", item)
                continue

            title = item.get("title", "")
            address = item.get("address", "")
            description = item.get("description", "")
            closing_date = item.get("closing_date", "")
            view_application_link = item.get("file_link", "")

            # Write the row to the CSV file
            writer.writerow([address, title, description, closing_date, view_application_link])

    print(f"Map data saved to {csv_filename}")
