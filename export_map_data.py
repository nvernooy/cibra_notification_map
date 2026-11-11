"""Export map json data to kml/kmz or csv format for google my maps"""

import csv
import zipfile
from datetime import date
from pathlib import Path
import re
from xml.sax.saxutils import escape

_SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to"}


def normalise_case(text):
    """Title-case text that's shouted in all caps (often copied from subjects), leave the rest alone."""
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return text

    def fix(match):
        word = match.group()
        # keep codes like W77, EO26-1268, 1A
        if any(c.isdigit() for c in word):
            return word
        word = word.lower()
        return word if word in _SMALL_WORDS and match.start() else word.capitalize()

    return re.sub(r"[A-Za-z0-9']+", fix, text)

KML_STYLES = """  <Style id="icon-1899-0288D1-normal">
    <IconStyle>
      <scale>1</scale>
      <Icon>
        <href>images/icon-1.png</href>
      </Icon>
      <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
    </IconStyle>
    <LabelStyle>
      <scale>0</scale>
    </LabelStyle>
  </Style>
  <Style id="icon-1899-0288D1-highlight">
    <IconStyle>
      <scale>1</scale>
      <Icon>
        <href>images/icon-1.png</href>
      </Icon>
      <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
    </IconStyle>
    <LabelStyle>
      <scale>1</scale>
    </LabelStyle>
  </Style>
  <StyleMap id="icon-1899-0288D1">
    <Pair>
      <key>normal</key>
      <styleUrl>#icon-1899-0288D1-normal</styleUrl>
    </Pair>
    <Pair>
      <key>highlight</key>
      <styleUrl>#icon-1899-0288D1-highlight</styleUrl>
    </Pair>
  </StyleMap>
  <Style id="icon-1899-0F9D58-normal">
    <IconStyle>
      <scale>1</scale>
      <Icon>
        <href>images/icon-2.png</href>
      </Icon>
      <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
    </IconStyle>
    <LabelStyle>
      <scale>0</scale>
    </LabelStyle>
  </Style>
  <Style id="icon-1899-0F9D58-highlight">
    <IconStyle>
      <scale>1</scale>
      <Icon>
        <href>images/icon-2.png</href>
      </Icon>
      <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
    </IconStyle>
    <LabelStyle>
      <scale>1</scale>
    </LabelStyle>
  </Style>
  <StyleMap id="icon-1899-0F9D58">
    <Pair>
      <key>normal</key>
      <styleUrl>#icon-1899-0F9D58-normal</styleUrl>
    </Pair>
    <Pair>
      <key>highlight</key>
      <styleUrl>#icon-1899-0F9D58-highlight</styleUrl>
    </Pair>
  </StyleMap>"""


def _placemark_kml(item, style_id):
    title = escape(item.get("title") or "")
    address = escape(item.get("address") or "")
    description = escape(normalise_case(item.get("description") or ""))
    closing_date = escape(item.get("closing_date") or "")
    file_link = escape(item.get("file_link") or "")
    description_html = (
        f"Address: {address}<br>"
        f"Description: {description}<br>"
        f"Closing Date: {closing_date}<br>"
        f"View Application: {file_link}"
    )
    return f"""      <Placemark>
        <name>{title}</name>
        <address>{address}</address>
        <description><![CDATA[{description_html}]]></description>
        <styleUrl>#{style_id}</styleUrl>
        <ExtendedData>
          <Data name="Address">
            <value>{address}</value>
          </Data>
          <Data name="Description">
            <value>{description}</value>
          </Data>
          <Data name="Closing Date">
            <value>{closing_date}</value>
          </Data>
          <Data name="View Application">
            <value>{file_link}</value>
          </Data>
        </ExtendedData>
      </Placemark>"""


def _folder_kml(name, items, style_id):
    if not items:
        return f"    <Folder>\n      <name>{escape(name)}</name>\n    </Folder>"
    placemarks = "\n".join(
        _placemark_kml(item, style_id)
        for item in items
        if item.get("address")
    )
    return f"    <Folder>\n      <name>{escape(name)}</name>\n{placemarks}\n    </Folder>"



def _write_kmz(filename, layer_name, items, style_id):
    today = date.today().isoformat()
    kmz_filename = f"{filename}_{today}.kmz"
    folder = _folder_kml(layer_name, items, style_id)
    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{escape(layer_name)}</name>
{KML_STYLES}
{folder}
  </Document>
</kml>"""

    icons_dir = Path(__file__).parent / "images"
    with zipfile.ZipFile(kmz_filename, "w", zipfile.ZIP_DEFLATED) as kmz:
        kmz.writestr("doc.kml", kml_content)
        for icon in ["icon-1.png", "icon-2.png"]:
            icon_path = icons_dir / icon
            if icon_path.exists():
                kmz.write(icon_path, f"images/{icon}")

    print(f"KMZ saved to {kmz_filename} ({len(items)} placemarks)")
    return kmz_filename


def export_to_kmz(notice_data, public_data, events_data):
    """Export each category as a separate KMZ layer for Google Maps import"""
    notice_kmz = _write_kmz("notice", "Applications for Comment", notice_data or [], "icon-1899-0288D1")
    public_kmz = _write_kmz("public", "Public Participation", public_data or [], "icon-1899-0288D1")
    events_kmz = _write_kmz("events", "Events", events_data or [], "icon-1899-0F9D58")
    return notice_kmz, public_kmz, events_kmz


def export_to_map_csv(filename, document_data):
    """Export map data as csv"""

    csv_filename = f"{filename}_{date.today().isoformat()}.csv"
    csv_headers = ["Address", "Title", "Description", "Closing Date", "View Application"]

    with open(csv_filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)

        for item in document_data:
            if not item.get("address"):
                print("ERROR no address", item)
                continue

            writer.writerow([
                item.get("address", ""),
                item.get("title", ""),
                normalise_case(item.get("description", "")),
                item.get("closing_date", ""),
                item.get("file_link", ""),
            ])

    print(f"Map data saved to {csv_filename}")
