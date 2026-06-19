"""Resolve roster column E — the Zendesk/Z2 account display name — by email.

Resolution order for each advocate email:
  1. Snowflake Zendesk-users table, IF configured (config.ZENDESK_USERS_TABLE or
     st.secrets["zendesk"]). Discovery during build found no such table
     accessible from the premier_metrics connection, so this is opt-in.
  2. The local Z2 Names List cache (data/z2_names_list.csv) — same source roster
     column E used before via VLOOKUP against the 'Z2 Names List' tab.

Names newly resolved from Snowflake are appended back into the Z2 cache so it
stays current and the fallback keeps improving month over month.
"""

import streamlit as st

from core import config, lookups


def _zendesk_table_config() -> tuple[str, str, str] | None:
    """Return (table, email_col, name_col) if a Snowflake source is configured."""
    table = config.ZENDESK_USERS_TABLE
    email_col = config.ZENDESK_USERS_EMAIL_COL
    name_col = config.ZENDESK_USERS_NAME_COL

    # st.secrets overrides config defaults when present.
    try:
        sec = st.secrets.get("zendesk", {})
        table = sec.get("users_table", table)
        email_col = sec.get("email_col", email_col)
        name_col = sec.get("name_col", name_col)
    except Exception:
        pass

    if table:
        return table, email_col, name_col
    return None


@st.cache_data(ttl=3600, show_spinner="Looking up Zendesk display names…")
def _fetch_names_from_snowflake(emails: tuple[str, ...]) -> dict[str, str]:
    """Query the configured Zendesk-users table for email -> display name.

    `emails` is a tuple (hashable for caching). Returns {} if no table is
    configured or the query fails (caller falls back to the Z2 cache).
    """
    cfg = _zendesk_table_config()
    if not cfg or not emails:
        return {}
    table, email_col, name_col = cfg

    from services.workday_snowflake import get_session

    try:
        session = get_session()
        in_list = ", ".join("'" + e.replace("'", "''") + "'" for e in emails)
        query = (
            f"SELECT LOWER({email_col}) AS EMAIL, {name_col} AS NAME "
            f"FROM {table} "
            f"WHERE LOWER({email_col}) IN ({in_list})"
        )
        df = session.sql(query).to_pandas()
        return {
            str(r.EMAIL).strip().lower(): str(r.NAME).strip()
            for r in df.itertuples()
            if r.EMAIL and r.NAME
        }
    except Exception:
        return {}


def resolve_display_names(emails: list[str]) -> tuple[dict[str, str], int]:
    """Resolve display names for a list of emails.

    Returns (email -> name map, n_appended_to_cache). Snowflake (if configured)
    wins; gaps are filled from the Z2 cache. Newly Snowflake-resolved names are
    appended to the cache.
    """
    norm = sorted({e.strip().lower() for e in emails if e})
    if not norm:
        return {}, 0

    cache_map = lookups.z2_name_map()
    sf_map = _fetch_names_from_snowflake(tuple(norm))

    # Persist Snowflake-resolved names not already cached.
    appended = lookups.append_z2_names({e: n for e, n in sf_map.items() if e not in cache_map})

    resolved = {}
    for email in norm:
        if email in sf_map:
            resolved[email] = sf_map[email]
        elif email in cache_map:
            resolved[email] = cache_map[email]
    return resolved, appended
