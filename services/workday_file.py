"""Workday roster from an uploaded XLS/XLSX export (fallback when Snowflake is down).

Maps the Workday headcount export's headers onto the same schema as
config.WORKDAY_COLUMNS so the roster builder is source-agnostic.

Caveats vs. the Snowflake source:
  * REGION and COUNTRY are NOT in the file export (the SCD2 table computes them);
    they come back blank here. Roster column B (Region in Workday) is therefore
    empty in fallback mode.
  * _FIVETRAN_DELETED does not exist in a file export; every row is treated as
    active (=False), since a Workday export only contains active headcount.

The export has a title/metadata banner; real headers sit on row 6 (1-indexed).
"""

import pandas as pd

from core import config

HEADER_ROW_INDEX = 5  # 0-indexed -> spreadsheet row 6

# Workday file header  ->  canonical config.WORKDAY_COLUMNS name
FILE_HEADER_MAP = {
    "Email - Primary Work": "EMAIL",
    "Full Name": "FULL_NAME",
    "First Name": "FIRST_NAME",
    "Last Name": "LAST_NAME",
    "Job Title": "JOB_TITLE",
    "Business Title": "BUSINESS_TITLE",
    "Hire Date": "HIRE_DATE",
    "Worker's Manager": "WORKER_MANAGER",
    "Manager ID": "MANAGER_ID",
    "Management Chain - Level 06": "C_STAFF_6",
    "Location": "LOCATION",
    "Cost Center": "COST_CENTER",
    "Employee Type": "EMPLOYEE_TYPE",
    "Worker Type": "WORKER_TYPE",
}

# Present in the table schema but absent from the file export.
MISSING_IN_FILE = ["REGION", "COUNTRY", "_FIVETRAN_DELETED"]


def _matches_advocacy_cost_center(value: object) -> bool:
    text = "" if value is None else str(value).strip()
    return any(text.startswith(p) for p in config.ADVOCACY_COST_CENTER_PREFIXES)


def load_workday_file(file) -> pd.DataFrame:
    """Read an uploaded Workday export and normalize it to WORKDAY_COLUMNS.

    `file` is a path or a file-like object (e.g. st.file_uploader result).
    Filters to the Advocacy cost centers by numeric prefix. Raises ValueError
    if the expected header row / columns aren't found.
    """
    raw = pd.read_excel(file, header=HEADER_ROW_INDEX, dtype=object)
    raw.columns = [str(c).strip() for c in raw.columns]

    missing_headers = [h for h in FILE_HEADER_MAP if h not in raw.columns]
    if missing_headers:
        raise ValueError(
            "Uploaded file is missing expected Workday columns: "
            + ", ".join(missing_headers)
            + f". Found headers on row {HEADER_ROW_INDEX + 1}: {list(raw.columns)[:30]}"
        )

    df = raw.rename(columns=FILE_HEADER_MAP)[list(FILE_HEADER_MAP.values())].copy()

    # Add the columns the file lacks so the schema matches the Snowflake source.
    df["REGION"] = pd.NA
    df["COUNTRY"] = pd.NA
    df["_FIVETRAN_DELETED"] = False

    df = df[config.WORKDAY_COLUMNS]

    # Drop banner/blank rows, then filter to Advocacy cost centers by prefix.
    df = df[df["EMAIL"].notna()]
    df = df[df["COST_CENTER"].apply(_matches_advocacy_cost_center)]

    df["EMAIL"] = df["EMAIL"].astype("string").str.strip().str.lower()
    return df.reset_index(drop=True)
