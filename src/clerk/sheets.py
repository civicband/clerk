from collections import defaultdict
from typing import Any

import click
from ezsheets import Spreadsheet

from clerk.db import civic_db_connection, get_all_sites


@click.group()
def sheets():
    pass


@sheets.command()
@click.option("-d", "--doc-url", help="URL for Google Sheet to Work on")
@click.option(
    "-s", "--sheet-name", default="Consolidated", help="Name of the sheet to consolidate into"
)
def consolidate(doc_url, sheet_name):
    import ezsheets

    sites_raw: defaultdict[Any, list[Any]] = defaultdict(list)
    sites: defaultdict[Any, dict[Any, Any]] = defaultdict(dict)
    doc: Spreadsheet = ezsheets.Spreadsheet(doc_url)

    with civic_db_connection() as conn:
        db_sites = get_all_sites(conn)
        for site in db_sites:
            sites_raw[site["subdomain"]].append(
                {
                    "name": site["name"],
                    "kind": site["kind"],
                    "scraper": site["scraper"],
                    "extra": site["extra"],
                    "state": site["state"],
                    "country": site["country"],
                    "lat_lng": f"{site['lat']},{site['lng']}",
                    "in_civicband": "TRUE",
                    "start_year": site["start_year"],
                    "link": "",
                    "notes": "",
                    "source": "db",
                }
            )

    consolidated = doc.sheets[0]
    rows = consolidated.getRows()
    for i, row in enumerate(rows):
        if i == 0:
            continue
        sites_raw[row[0]].append(
            {
                "name": row[1],
                "state": row[2],
                "country": row[3],
                "kind": row[4],
                "lat_lng": row[5],
                "in_civicband": row[6],
                "start_year": row[7],
                "scraper": row[8],
                "extra": row[9],
                "link": row[10],
                "notes": row[11],
                "source": "consolidated",
            }
        )

    rows = [
        [
            "Subdomain",
            "Name",
            "State/Province",
            "Country",
            "Kind",
            "Lat,Lng",
            "In CivicBand",
            "Start Year",
            "Scraper",
            "Extra",
            "Link",
            "Notes",
        ]
    ]
    for subdomain, possibles in sites_raw.items():
        to_append = {}
        if len(possibles) == 1:
            to_append = possibles[0]
        else:
            for possible in possibles:
                if possible["source"] == "db":
                    to_append = possible
                    break
                if possible["source"] == "consolidated":
                    to_append = possible
                    break
                if not to_append and possible["source"] == "agendacenter":
                    to_append = possible
                    continue
                if to_append:
                    to_append["lat_lng"] = possible.get("lat_lng", "")
                else:
                    to_append = possible

        rows.append(
            [  # pyright: ignore[reportArgumentType]
                subdomain,
                to_append.get("name"),
                to_append.get("state"),
                to_append.get("country"),
                to_append.get("kind", ""),
                to_append.get("lat_lng", ""),
                to_append.get("in_civicband", "FALSE"),
                to_append.get("start_year", ""),
                to_append.get("scraper", ""),
                to_append.get("extra", ""),
                to_append.get("link", ""),
                to_append.get("notes", ""),
            ]
        )
    sheet = doc.sheets[0]
    sheet.updateRows(rows)
