"""Persisted Z2 (Zendesk display name) cache — backed by Snowflake.

Replaces the local data/z2_names_list.csv. The table
STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.Z2_NAMES_CACHE holds all previously
resolved email→name pairs and is readable/writable by the app session.
"""

import pandas as pd
import streamlit as st

from core import config


@st.cache_data(ttl=600, show_spinner=False)
def load_z2_cache() -> pd.DataFrame:
    """Return the Z2 cache as a DataFrame with columns Email, Z2 Name.

    Emails are normalised to lowercase. Returns an empty frame if the table
    doesn't exist yet (before first setup_snowflake.py run).
    """
    from services.workday_snowflake import get_session

    try:
        session = get_session()
        df = session.sql(
            f"SELECT EMAIL, Z2_NAME FROM {config.Z2_TABLE} ORDER BY EMAIL"
        ).to_pandas()
        df.columns = ["Email", "Z2 Name"]
        df["Email"] = df["Email"].str.strip().str.lower()
        df["Z2 Name"] = df["Z2 Name"].fillna("").str.strip()
        return df.drop_duplicates(subset="Email", keep="last").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["Email", "Z2 Name"])


def z2_name_map() -> dict[str, str]:
    """{email_lower: z2_name} for fast lookups."""
    df = load_z2_cache()
    return dict(zip(df["Email"], df["Z2 Name"], strict=False))


def append_z2_names(new_pairs: dict[str, str]) -> int:
    """Append newly-resolved email→name pairs to the Snowflake Z2 table.

    Existing emails are not overwritten (INSERT ... IF NOT EXISTS pattern).
    Returns the number of rows added.
    """
    if not new_pairs:
        return 0

    have = set(load_z2_cache()["Email"])
    rows = [
        (email.strip().lower(), str(name).strip())
        for email, name in new_pairs.items()
        if email and name and email.strip().lower() not in have
    ]
    if not rows:
        return 0

    from services.workday_snowflake import get_session

    try:
        session = get_session()
        values = ", ".join(
            f"('{e.replace(chr(39), chr(39)*2)}', '{n.replace(chr(39), chr(39)*2)}')"
            for e, n in rows
        )
        session.sql(
            f"INSERT INTO {config.Z2_TABLE} (EMAIL, Z2_NAME) "
            f"SELECT v.EMAIL, v.Z2_NAME FROM (VALUES {values}) AS v(EMAIL, Z2_NAME) "
            f"WHERE NOT EXISTS (SELECT 1 FROM {config.Z2_TABLE} t WHERE t.EMAIL = v.EMAIL)"
        ).collect()
        load_z2_cache.clear()
        return len(rows)
    except Exception:
        return 0
