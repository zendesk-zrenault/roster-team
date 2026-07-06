"""One-time: create the 'Roster Reference Data' Google Sheet on the user's Drive.

Creates a spreadsheet with three tabs and seeds them from the current reference
data, then prints the spreadsheet ID to record in core/config.py:
  * Job Titles              — JOB_TITLE, TICKET_BEARING   (from data CSV)
  * Z2 Names                — EMAIL, Z2_NAME              (from data CSV)
  * Region & Language Basis — EMAIL, REGION_EXPLORE, LANGUAGE (from data xlsx)

Auth: uses the local gcloud token (`gcloud auth print-access-token`). Local dev
only — this is the human-editable master the local app keeps in sync with
Snowflake. Run once:

    .venv/bin/python scripts/create_reference_sheet.py
"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
TITLE = "Roster Reference Data"

TABS = ["Job Titles", "Z2 Names", "Region & Language Basis"]


def _token() -> str:
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        sys.exit("Not authenticated. Run: gcloud auth login --update-adc --enable-gdrive-access")
    return out.stdout.strip()


def _post(url: str, body: dict, token: str, method: str = "POST") -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _load_job_titles() -> list[list]:
    df = pd.read_csv("data/job_title_classification.csv", dtype=str).fillna("")
    rows = [["JOB_TITLE", "TICKET_BEARING"]]
    rows += df[["JOB_TITLE", "TICKET_BEARING"]].values.tolist()
    return rows


def _load_z2() -> list[list]:
    df = pd.read_csv("data/z2_names_list.csv", dtype=str).fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    rows = [["EMAIL", "Z2_NAME"]]
    rows += df[["Email", "Z2 Name"]].values.tolist()
    return rows


def _load_basis() -> list[list]:
    from core import config

    df = pd.read_excel("data/basis_region_language.xlsx", header=0, dtype=str).fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    e, c, m = config.ROSTER_COLUMNS["F"], config.ROSTER_COLUMNS["C"], config.ROSTER_COLUMNS["M"]
    rows = [["EMAIL", "REGION_EXPLORE", "LANGUAGE"]]
    rows += df[[e, c, m]].values.tolist()
    return rows


def main() -> None:
    token = _token()

    print(f"Creating spreadsheet '{TITLE}' with tabs {TABS}…")
    created = _post(SHEETS, {
        "properties": {"title": TITLE},
        "sheets": [{"properties": {"title": t}} for t in TABS],
    }, token)
    sheet_id = created["spreadsheetId"]
    url = created.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sheet_id}")
    print(f"  ✓ Created: {url}")

    seeders = {
        "Job Titles": _load_job_titles,
        "Z2 Names": _load_z2,
        "Region & Language Basis": _load_basis,
    }
    data = []
    for tab, loader in seeders.items():
        try:
            rows = loader()
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  {tab}: could not load ({exc}) — leaving empty")
            continue
        data.append({"range": f"'{tab}'!A1", "majorDimension": "ROWS", "values": rows})
        print(f"  • {tab}: {len(rows) - 1} rows queued")

    _post(f"{SHEETS}/{sheet_id}/values:batchUpdate", {
        "valueInputOption": "USER_ENTERED", "data": data,
    }, token)
    print("  ✓ Seeded all tabs")

    print("\nDone. Record this in core/config.py:")
    print(f'  REFERENCE_SHEET_ID = "{sheet_id}"')


if __name__ == "__main__":
    main()
