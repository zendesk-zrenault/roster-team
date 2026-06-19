"""Apply a manager-corrected roster back into the carry-forward basis.

After a month is finalized, a manager may edit the roster: add a new agent, or
change a value in a column (most relevantly Region in Explore (C) or Foreign
Language (M) — the two carry-forward columns). Uploading that corrected file
here writes those values back so they carry forward into next month's build.

Also picks up any Z2 display names (col E) present in the corrected file and
adds them to the Z2 cache.

Only the carry-forward columns are persisted — the Workday/Playvox-backed
columns (name, manager, job title, role) are re-derived from source each month
and are not stored.
"""

import pandas as pd

from core import config, lookups
from services import basis

EMAIL_COL = config.ROSTER_COLUMNS["F"]            # "Advocate Email"
REGION_EXPLORE_COL = config.ROSTER_COLUMNS["C"]   # "Region in Explore (Shift)"
LANGUAGE_COL = config.ROSTER_COLUMNS["M"]         # "Foreign Language Advocate"
Z2_COL = config.ROSTER_COLUMNS["E"]               # "Advocate Z2 name ..."


def load_corrected_roster(file) -> pd.DataFrame:
    """Read a corrected roster (.csv or .xlsx) into a DataFrame keyed by email.

    Tolerates the live-sheet layout where headers sit on row 6 (data from row 7):
    if the expected columns aren't found on the first row, re-reads with the
    header on row 6. Emails are lowercased/stripped.
    """
    name = getattr(file, "name", str(file)).lower()

    def _read(header):
        if name.endswith(".csv"):
            return pd.read_csv(file, dtype=str, header=header)
        return pd.read_excel(file, dtype=str, header=header)

    df = _read(0)
    df.columns = [str(c).strip() for c in df.columns]

    # If the email column isn't where we expect, the file likely has the live
    # sheet's banner rows — retry with the header on row 6 (0-indexed 5).
    if EMAIL_COL not in df.columns:
        if hasattr(file, "seek"):
            file.seek(0)
        df = _read(config.ROSTER_HEADER_ROW - 1)
        df.columns = [str(c).strip() for c in df.columns]

    if EMAIL_COL not in df.columns:
        raise ValueError(
            f"Couldn't find an '{EMAIL_COL}' column in the uploaded file. "
            f"Found: {list(df.columns)[:15]}"
        )

    df[EMAIL_COL] = df[EMAIL_COL].astype("string").str.strip().str.lower()
    df = df[df[EMAIL_COL].notna() & (df[EMAIL_COL] != "")]
    return df.reset_index(drop=True)


def apply_corrections(corrected_df: pd.DataFrame) -> dict[str, int]:
    """Write corrected carry-forward values back to the basis + Z2 cache.

    Returns counts: {basis_inserted, basis_updated, z2_added}.
    """
    have = basis.known_emails()

    entries = []
    for _, row in corrected_df.iterrows():
        email = str(row.get(EMAIL_COL, "")).strip().lower()
        if not email:
            continue
        region = str(row.get(REGION_EXPLORE_COL, "") or "").strip()
        language = str(row.get(LANGUAGE_COL, "") or "").strip()
        # Skip rows with neither carry-forward value to set.
        if not region and not language:
            continue
        entries.append({"email": email, "region": region, "language": language})

    inserted = sum(1 for e in entries if e["email"] not in have)
    updated = sum(1 for e in entries if e["email"] in have)
    basis.upsert_entries(entries)

    # Z2 display names, if the corrected file carries column E.
    z2_added = 0
    if Z2_COL in corrected_df.columns:
        pairs = {
            str(r[EMAIL_COL]).strip().lower(): str(r[Z2_COL]).strip()
            for _, r in corrected_df.iterrows()
            if str(r.get(Z2_COL, "") or "").strip()
        }
        z2_added = lookups.append_z2_names(pairs)

    return {"basis_inserted": inserted, "basis_updated": updated, "z2_added": z2_added}
