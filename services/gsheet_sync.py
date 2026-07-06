"""Sync the reference lists to the Google Sheet 'Roster Reference Data'.

The Google Sheet is a human-editable master that mirrors the reference lists
(job titles, Z2 names, Region/Language basis). Authenticated via the local
`gcloud` token — so this only works on the LOCAL app. In the deployed SiS
container there is no gcloud/internet, so every function here is a safe no-op
(gcloud_available() returns False) and the deployed app just uses Snowflake.

Flow: the local app calls write_* after a validation to push the change up, and
sync_all() to overwrite each tab with the current Snowflake state (so deployed
validations, which only hit Snowflake, appear in the sheet on the next local run).
"""

import json
import subprocess
import urllib.parse
import urllib.request

from core import config

_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"


def gcloud_available() -> bool:
    """True if a gcloud access token can be minted (i.e. we're local + authed)."""
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=15,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _token() -> str | None:
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _api(url: str, body: dict, method: str = "POST") -> dict | None:
    token = _token()
    if not token:
        return None
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _overwrite_tab(tab: str, rows: list[list]) -> bool:
    """Clear a tab and write `rows` (including header) starting at A1.

    Returns True on success. No-op → False when gcloud is unavailable.
    """
    if not gcloud_available() or not rows:
        return False
    sid = config.REFERENCE_SHEET_ID
    # A1 ranges contain spaces/!/quotes — URL-encode them for the request path.
    clear_range = urllib.parse.quote(f"'{tab}'!A1:ZZ1000000", safe="")
    write_range = urllib.parse.quote(f"'{tab}'!A1", safe="")
    # Clear existing values first so a shorter list doesn't leave stale trailing rows.
    cleared = _api(f"{_SHEETS}/{sid}/values/{clear_range}:clear", {})
    if cleared is None:
        return False
    written = _api(
        f"{_SHEETS}/{sid}/values/{write_range}?valueInputOption=USER_ENTERED",
        {"range": f"'{tab}'!A1", "majorDimension": "ROWS", "values": rows},
        method="PUT",
    )
    return written is not None


# --- Per-list writers (overwrite the whole tab with current state) -----------

def sync_job_titles(df) -> bool:
    """Overwrite the Job Titles tab from a [JOB_TITLE, TICKET_BEARING] frame."""
    rows = [["JOB_TITLE", "TICKET_BEARING"]]
    rows += [
        [str(t), "TRUE" if bool(b) else "FALSE"]
        for t, b in zip(df["JOB_TITLE"], df["TICKET_BEARING"], strict=False)
    ]
    return _overwrite_tab(config.REFERENCE_SHEET_TABS["job_titles"], rows)


def sync_z2(df) -> bool:
    """Overwrite the Z2 Names tab from an [Email, Z2 Name] frame."""
    rows = [["EMAIL", "Z2_NAME"]]
    rows += [[str(e), str(n)] for e, n in zip(df["Email"], df["Z2 Name"], strict=False)]
    return _overwrite_tab(config.REFERENCE_SHEET_TABS["z2"], rows)


def sync_basis(df) -> bool:
    """Overwrite the basis tab from an [email, region, language] frame.

    Column labels come from config.ROSTER_COLUMNS (F/C/M).
    """
    e = config.ROSTER_COLUMNS["F"]
    c = config.ROSTER_COLUMNS["C"]
    m = config.ROSTER_COLUMNS["M"]
    rows = [["EMAIL", "REGION_EXPLORE", "LANGUAGE"]]
    rows += [
        [str(r[e]), str(r[c]), str(r[m])]
        for _, r in df.iterrows()
    ]
    return _overwrite_tab(config.REFERENCE_SHEET_TABS["basis"], rows)


def sync_all() -> dict:
    """Push all three reference lists (current Snowflake/CSV state) to the sheet.

    Returns {list: ok} per tab. All-False when gcloud is unavailable (deployed).
    """
    if not gcloud_available():
        return {"job_titles": False, "z2": False, "basis": False, "available": False}

    from core import lookups
    from services import basis, job_titles

    result = {"available": True}
    try:
        result["job_titles"] = sync_job_titles(job_titles.load_classification())
    except Exception:
        result["job_titles"] = False
    try:
        result["z2"] = sync_z2(lookups.load_z2_cache())
    except Exception:
        result["z2"] = False
    try:
        result["basis"] = sync_basis(basis.load_basis())
    except Exception:
        result["basis"] = False
    return result
