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


def _clean_str(value) -> str:
    """Return a trimmed string, treating NaN/None/'nan' as empty.

    pd.isna catches float NaN and None; the literal 'nan'/'none' guard catches
    values already stringified upstream. Prevents a blank cell from being stored
    as the text "nan".
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def load_corrected_roster(file) -> pd.DataFrame:
    """Read a corrected roster (.csv or .xlsx) into a DataFrame keyed by email.

    Tolerates the live-sheet layout where headers sit on row 6 (data from row 7):
    if the expected columns aren't found on the first row, re-reads with the
    header on row 6. Emails are lowercased/stripped.
    """
    name = getattr(file, "name", str(file)).lower()

    def _read(header):
        if hasattr(file, "seek"):
            file.seek(0)
        if name.endswith(".csv"):
            # skip_blank_lines=False so the banner rows keep their positions and
            # the header lands where expected (row 6 = 0-indexed 5).
            return pd.read_csv(file, dtype=str, header=header, skip_blank_lines=False)
        return pd.read_excel(file, dtype=str, header=header)

    # Try the header on row 1 first, then on row 6 (the live-sheet banner layout).
    # A blank leading row makes header=0 raise EmptyDataError, so guard both.
    df = None
    for header in (0, config.ROSTER_HEADER_ROW - 1):
        try:
            candidate = _read(header)
        except pd.errors.EmptyDataError:
            continue
        candidate.columns = [str(c).strip() for c in candidate.columns]
        if EMAIL_COL in candidate.columns:
            df = candidate
            break

    if df is None:
        raise ValueError(
            f"Couldn't find an '{EMAIL_COL}' column in the uploaded file "
            "(looked for the header on row 1 and row 6)."
        )

    df[EMAIL_COL] = df[EMAIL_COL].astype("string").str.strip().str.lower()
    df = df[df[EMAIL_COL].notna() & (df[EMAIL_COL] != "")]
    return df.reset_index(drop=True)


def apply_corrections(corrected_df: pd.DataFrame) -> dict[str, int]:
    """Write corrected carry-forward values back to the basis + Z2 cache.

    Compares each uploaded row against the CURRENT basis and reports what
    actually changed (not just rows touched). Returns:
      * new_agents      — emails not previously in the basis
      * region_changed  — existing agents whose Region in Explore differs
      * language_changed— existing agents whose Language differs
      * unchanged        — existing agents with no change to either column
      * z2_added         — new Z2 display names added to the cache
    """
    # Snapshot the basis as it is *before* we write, to diff against.
    prior = basis.load_basis()
    prior_region = dict(
        zip(prior[EMAIL_COL], prior[REGION_EXPLORE_COL].fillna("").astype(str).str.strip(),
            strict=False)
    )
    prior_language = dict(
        zip(prior[EMAIL_COL], prior[LANGUAGE_COL].fillna("").astype(str).str.strip(),
            strict=False)
    )
    have = set(prior[EMAIL_COL])

    entries = []
    new_agents = region_changed = language_changed = unchanged = 0
    for _, row in corrected_df.iterrows():
        email = _clean_str(row.get(EMAIL_COL, "")).lower()
        if not email:
            continue
        region = _clean_str(row.get(REGION_EXPLORE_COL, ""))
        language = _clean_str(row.get(LANGUAGE_COL, ""))
        # Skip rows with neither carry-forward value to set.
        if not region and not language:
            continue
        entries.append({"email": email, "region": region, "language": language})

        if email not in have:
            new_agents += 1
            continue
        r_diff = bool(region) and region != prior_region.get(email, "")
        l_diff = bool(language) and language != prior_language.get(email, "")
        if r_diff:
            region_changed += 1
        if l_diff:
            language_changed += 1
        if not r_diff and not l_diff:
            unchanged += 1

    basis.upsert_entries(entries)

    # Z2 display names, if the corrected file carries column E. Only keep rows
    # with a real name — blank/NaN cells must NOT be stored as the text "nan".
    z2_added = 0
    if Z2_COL in corrected_df.columns:
        pairs = {}
        for _, r in corrected_df.iterrows():
            email = _clean_str(r.get(EMAIL_COL, "")).lower()
            name = _clean_str(r.get(Z2_COL, ""))
            if email and name:
                pairs[email] = name
        z2_added = lookups.append_z2_names(pairs)

    return {
        "new_agents": new_agents,
        "region_changed": region_changed,
        "language_changed": language_changed,
        "unchanged": unchanged,
        "z2_added": z2_added,
    }
