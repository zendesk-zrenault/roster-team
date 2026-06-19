"""Basis table for the two carry-forward roster columns that exist in no upload:
   C "Region in Explore (Shift)" and M "Foreign Language Advocate".

Backed by STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.ROSTER_BASIS in Snowflake
(seeded from data/basis_region_language.xlsx by scripts/setup_snowflake.py).

Each month the app:
  * carries C and M forward from the table for known emails,
  * detects roster emails NOT in the table (new agents),
  * after the user supplies region+language, appends those rows so they are
    known next month.

Fallbacks when an email is absent and no value is supplied: the Workday region
for C, and config.DEFAULT_FOREIGN_LANGUAGE for M.
"""

import pandas as pd
import streamlit as st

from core import config

EMAIL_COL = config.ROSTER_COLUMNS["F"]            # "Advocate Email"
REGION_EXPLORE_COL = config.ROSTER_COLUMNS["C"]   # "Region in Explore (Shift)"
LANGUAGE_COL = config.ROSTER_COLUMNS["M"]         # "Foreign Language Advocate"


@st.cache_data(ttl=600, show_spinner=False)
def load_basis() -> pd.DataFrame:
    """Return the basis as a DataFrame [Advocate Email, Region in Explore, Language].

    Emails are lowercased/stripped. Empty frame if the table is missing or empty.
    """
    from services.workday_snowflake import get_session

    try:
        session = get_session()
        df = session.sql(
            f"SELECT EMAIL, REGION_EXPLORE, LANGUAGE FROM {config.BASIS_TABLE} ORDER BY EMAIL"
        ).to_pandas()
        df.columns = [EMAIL_COL, REGION_EXPLORE_COL, LANGUAGE_COL]
        df[EMAIL_COL] = df[EMAIL_COL].astype("string").str.strip().str.lower()
        df = df[df[EMAIL_COL].notna() & (df[EMAIL_COL] != "")]
        return df.drop_duplicates(subset=EMAIL_COL, keep="last").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=[EMAIL_COL, REGION_EXPLORE_COL, LANGUAGE_COL])


def region_map() -> dict[str, str]:
    """{email: Region in Explore} from the basis (blanks dropped)."""
    df = load_basis()
    return {
        email: str(region).strip()
        for email, region in zip(df[EMAIL_COL], df[REGION_EXPLORE_COL], strict=False)
        if email and pd.notna(region) and str(region).strip()
    }


def language_map() -> dict[str, str]:
    """{email: Foreign Language} from the basis (blanks dropped)."""
    df = load_basis()
    return {
        email: str(lang).strip()
        for email, lang in zip(df[EMAIL_COL], df[LANGUAGE_COL], strict=False)
        if email and pd.notna(lang) and str(lang).strip()
    }


def known_emails() -> set[str]:
    return set(load_basis()[EMAIL_COL])


def existing_regions() -> list[str]:
    """Distinct region values already in the basis (for dropdown hints)."""
    return sorted({v for v in region_map().values()})


def existing_languages() -> list[str]:
    """Distinct language values already in the basis (for dropdown hints)."""
    return sorted({v for v in language_map().values()})


def find_new_agents(
    roster: pd.DataFrame, eligible_emails: set[str] | None = None
) -> pd.DataFrame:
    """Roster rows whose email is NOT in the basis — these need region+language.

    Only agents whose email is in `eligible_emails` are returned (pass the
    Playvox/Agyle kept emails, i.e. agents present there with a valid business
    role). Workday-only agents are not prompted; they just take the fallbacks.

    Returns [Advocate Email, Advocate, Region in Workday].
    """
    have = known_emails()
    mask = ~roster[EMAIL_COL].isin(have)
    if eligible_emails is not None:
        eligible = {e.strip().lower() for e in eligible_emails if e}
        mask &= roster[EMAIL_COL].isin(eligible)
    cols = [EMAIL_COL, config.ROSTER_COLUMNS["D"], config.ROSTER_COLUMNS["B"]]
    return roster.loc[mask, cols].reset_index(drop=True)


def append_entries(entries: list[dict]) -> int:
    """Append new agent rows to the Snowflake basis table.

    `entries` items: {"email": str, "region": str, "language": str}.
    Existing emails are skipped (idempotent). Returns the number of rows added.
    """
    if not entries:
        return 0

    have = known_emails()
    new = [
        e for e in entries
        if e.get("email") and e["email"].strip().lower() not in have
    ]
    if not new:
        return 0

    from services.workday_snowflake import get_session

    def _q(s: str) -> str:
        return str(s).replace("'", "''")

    values = ", ".join(
        f"('{_q(e['email'].strip().lower())}', '{_q(e.get('region',''))}', '{_q(e.get('language',''))}')"
        for e in new
    )
    try:
        session = get_session()
        session.sql(
            f"INSERT INTO {config.BASIS_TABLE} (EMAIL, REGION_EXPLORE, LANGUAGE) "
            f"SELECT v.EMAIL, v.REGION_EXPLORE, v.LANGUAGE "
            f"FROM (VALUES {values}) AS v(EMAIL, REGION_EXPLORE, LANGUAGE) "
            f"WHERE NOT EXISTS (SELECT 1 FROM {config.BASIS_TABLE} t WHERE t.EMAIL = v.EMAIL)"
        ).collect()
        load_basis.clear()
        return len(new)
    except Exception:
        return 0


def upsert_entries(entries: list[dict]) -> int:
    """Insert new emails and UPDATE existing ones (for manager corrections).

    `entries` items: {"email": str, "region": str, "language": str}. Blank
    region/language values do NOT overwrite an existing non-blank value. Returns
    the number of rows written (inserted + updated).
    """
    rows = [
        (
            e["email"].strip().lower(),
            str(e.get("region", "") or "").strip(),
            str(e.get("language", "") or "").strip(),
        )
        for e in entries
        if e.get("email")
    ]
    if not rows:
        return 0

    from services.workday_snowflake import get_session

    def _q(s: str) -> str:
        return str(s).replace("'", "''")

    values = ", ".join(f"('{_q(e)}', '{_q(r)}', '{_q(lang)}')" for e, r, lang in rows)
    try:
        session = get_session()
        # MERGE: update existing rows (keeping a prior value when the incoming one
        # is blank), insert brand-new emails.
        session.sql(
            f"MERGE INTO {config.BASIS_TABLE} t "
            f"USING (VALUES {values}) AS v(EMAIL, REGION_EXPLORE, LANGUAGE) "
            f"ON t.EMAIL = v.EMAIL "
            f"WHEN MATCHED THEN UPDATE SET "
            f"  REGION_EXPLORE = IFF(v.REGION_EXPLORE = '', t.REGION_EXPLORE, v.REGION_EXPLORE), "
            f"  LANGUAGE = IFF(v.LANGUAGE = '', t.LANGUAGE, v.LANGUAGE) "
            f"WHEN NOT MATCHED THEN INSERT (EMAIL, REGION_EXPLORE, LANGUAGE) "
            f"  VALUES (v.EMAIL, v.REGION_EXPLORE, v.LANGUAGE)"
        ).collect()
        load_basis.clear()
        return len(rows)
    except Exception:
        return 0
