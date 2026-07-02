"""Persisted Z2 (Zendesk display name) cache — backed by Snowflake.

Replaces the local data/z2_names_list.csv. The table
STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.Z2_NAMES_CACHE holds all previously
resolved email→name pairs and is readable/writable by the app session.
"""

import pandas as pd
import streamlit as st

from core import config


def _read_z2_table() -> pd.DataFrame:
    """Raw read of the Snowflake Z2 table (columns Email, Z2 Name)."""
    from services.workday_snowflake import get_session

    session = get_session()
    df = session.sql(
        f"SELECT EMAIL, Z2_NAME FROM {config.Z2_TABLE} ORDER BY EMAIL"
    ).to_pandas()
    df.columns = ["Email", "Z2 Name"]
    return df


@st.cache_data(ttl=600, show_spinner=False)
def load_z2_cache() -> pd.DataFrame:
    """Return the Z2 cache as a DataFrame with columns Email, Z2 Name.

    Emails are normalised to lowercase. Empty frame if the table doesn't exist yet.

    Self-healing: like the basis, the Z2 table has intermittently corrupted to
    all-NULL. If detected, auto-re-seed from the local seed CSV (present only in
    local dev, gitignored PII) and re-read. On the deployed app the file is
    absent, so it just returns whatever is there (column E falls back to blank).
    """
    try:
        df = _read_z2_table()
    except Exception:
        return pd.DataFrame(columns=["Email", "Z2 Name"])

    # All-NULL detection: rows present but no usable email.
    if len(df) > 0 and df["Email"].notna().sum() == 0:
        if _reseed_z2_from_local_file():
            try:
                df = _read_z2_table()
            except Exception:
                pass

    df["Email"] = df["Email"].astype("string").str.strip().str.lower()
    df["Z2 Name"] = df["Z2 Name"].fillna("").astype(str).str.strip()
    df = df[df["Email"].notna() & (df["Email"] != "")]
    return df.drop_duplicates(subset="Email", keep="last").reset_index(drop=True)


def _reseed_z2_from_local_file() -> bool:
    """Re-seed the Snowflake Z2 table from the local seed CSV (local dev only)."""
    from pathlib import Path

    seed = Path("data/z2_names_list.csv")  # gitignored PII seed, local dev only
    if not seed.exists():
        return False
    try:
        from snowflake.connector.pandas_tools import write_pandas

        from services.workday_snowflake import get_session

        z = pd.read_csv(seed, dtype=str).fillna("")
        z.columns = [str(c).strip() for c in z.columns]
        z = z[["Email", "Z2 Name"]].copy()
        z.columns = ["EMAIL", "Z2_NAME"]
        z["EMAIL"] = z["EMAIL"].str.strip().str.lower()
        z = z[z["EMAIL"] != ""].drop_duplicates(subset="EMAIL", keep="last")

        session = get_session()
        session.sql(
            f"CREATE OR REPLACE TABLE {config.Z2_TABLE} (EMAIL VARCHAR, Z2_NAME VARCHAR)"
        ).collect()
        write_pandas(
            session._conn._conn, z, "Z2_NAMES_CACHE",
            schema=config.PERSIST_SCHEMA, database=config.PERSIST_DATABASE,
            quote_identifiers=False,
        )
        return True
    except Exception:
        return False


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

    def _clean(v) -> str:
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return ""
        s = str(v).strip()
        return "" if s.lower() in ("nan", "none", "nat") else s

    have = set(load_z2_cache()["Email"])
    rows = []
    for email, name in new_pairs.items():
        e = _clean(email).lower()
        n = _clean(name)
        # Skip blank names — a missing Z2 name must never be stored as "nan".
        if e and n and e not in have:
            rows.append((e, n))
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
