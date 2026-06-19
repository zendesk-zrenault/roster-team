"""Workday roster data sourced live from Snowflake.

Queries the SCD2 table for the *current* record of every advocate in the
Advocacy cost centers. Returns a normalized DataFrame whose columns match
config.WORKDAY_COLUMNS (the same schema the XLS fallback produces), so the
roster builder is agnostic to which source was used.

Departure signal: _FIVETRAN_DELETED. By default we keep only active
(non-deleted) workers, but callers can fetch the deleted set too (for the
review step that flags departed agents still present in the roster).
"""

import streamlit as st

from core import config


@st.cache_resource
def get_session():
    """Cached Snowflake Snowpark session.

    Uses the active session when running in Streamlit-in-Snowflake; otherwise
    builds one from a named CLI connection (~/.snowflake/connections.toml),
    matching the starter-kit pattern.
    """
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        from snowflake.snowpark import Session

        # Cloud deployment: explicit credentials in secrets.toml take priority.
        try:
            sf = st.secrets.get("snowflake", {})
            if sf.get("account"):
                params = {
                    "account": sf["account"],
                    "user": sf["user"],
                    "password": sf.get("password", ""),
                    "warehouse": sf.get("warehouse", ""),
                    "role": sf.get("role", ""),
                    "database": sf.get("database", ""),
                    "schema": sf.get("schema", ""),
                }
                return Session.builder.configs(
                    {k: v for k, v in params.items() if v}
                ).create()
        except Exception:
            pass

        # Local dev: named CLI connection from ~/.snowflake/connections.toml.
        connection_name = config.DEFAULT_CONNECTION_NAME
        try:
            connection_name = st.secrets.get("dev", {}).get(
                "connection_name", config.DEFAULT_CONNECTION_NAME
            )
        except Exception:
            pass
        return Session.builder.config("connection_name", connection_name).create()


def _cost_center_predicate() -> str:
    """SQL OR-clause matching the Advocacy cost-center numeric prefixes."""
    clauses = [f"COST_CENTER LIKE '{p}%'" for p in config.ADVOCACY_COST_CENTER_PREFIXES]
    return "(" + " OR ".join(clauses) + ")"


def _build_query(include_deleted: bool) -> str:
    cols = ", ".join(config.WORKDAY_COLUMNS)
    where = [
        f"VALID_TO_TIMESTAMP = '{config.SCD2_CURRENT_SENTINEL}'",
        _cost_center_predicate(),
    ]
    if not include_deleted:
        where.append("_FIVETRAN_DELETED = FALSE")
    return (
        f"SELECT {cols}\n"
        f"FROM {config.WORKDAY_TABLE}\n"
        f"WHERE {' AND '.join(where)}"
    )


@st.cache_data(ttl=3600, show_spinner="Querying Workday roster from Snowflake…")
def fetch_workday_roster(include_deleted: bool = False):
    """Return the current Advocacy roster from Snowflake as a pandas DataFrame.

    Columns are config.WORKDAY_COLUMNS. EMAIL is lowercased/stripped for joins.
    With include_deleted=True, rows carry _FIVETRAN_DELETED so departed workers
    can be separated downstream.
    """
    session = get_session()
    df = session.sql(_build_query(include_deleted)).to_pandas()

    if "EMAIL" in df.columns:
        df["EMAIL"] = df["EMAIL"].astype("string").str.strip().str.lower()
    return df


def test_connection() -> tuple[bool, str]:
    """Lightweight connectivity check for the UI. Returns (ok, message)."""
    try:
        session = get_session()
        session.sql("SELECT 1").collect()
        return True, "Connected to Snowflake."
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return False, str(exc)
