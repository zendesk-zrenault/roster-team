"""Job-title classification: which Workday job titles bear tickets.

Only ticket-bearing agents belong on the roster. Non-Ticket Bearing titles
(directors, analysts, trainers, …) AND management titles ("Ticket Bearing Mgmt")
are dropped — per the user's rule, anything management-level is treated as
non-ticket-bearing.

Backed by the Snowflake table JOB_TITLE_CLASSIFICATION (seeded from the repo CSV
data/job_title_classification.csv). When a roster carries a job title not yet in
the table, the review step asks the user to classify it, and the answer is saved
so it is known next month.

Comparison is case-insensitive and whitespace-normalised so minor Workday drift
("Sr." spacing, trailing spaces) doesn't create phantom "new" titles.
"""

import pandas as pd
import streamlit as st

from core import config

JOB_TITLE_COL = config.ROSTER_COLUMNS["G"]  # "Job title"


def _norm(title) -> str:
    """Normalise a title for matching: trimmed, collapsed spaces, lowercased."""
    if title is None or (not isinstance(title, str) and pd.isna(title)):
        return ""
    return " ".join(str(title).split()).strip().lower()


@st.cache_data(ttl=600, show_spinner=False)
def load_classification() -> pd.DataFrame:
    """Return the classification table as [JOB_TITLE, TICKET_BEARING(bool)].

    Reads the Snowflake table; if unavailable, falls back to the repo CSV seed so
    the app still filters correctly (e.g. local dev before setup_snowflake.py).
    """
    from services.workday_snowflake import get_session

    try:
        session = get_session()
        df = session.sql(
            f"SELECT JOB_TITLE, TICKET_BEARING FROM {config.JOB_TITLE_TABLE}"
        ).to_pandas()
        if not df.empty:
            df["TICKET_BEARING"] = df["TICKET_BEARING"].astype(bool)
            return df
    except Exception:
        pass

    # Fallback: the version-controlled seed CSV.
    try:
        df = pd.read_csv(config.JOB_TITLE_CSV, dtype=str)
        df["TICKET_BEARING"] = (
            df["TICKET_BEARING"].astype(str).str.strip().str.upper() == "TRUE"
        )
        return df[["JOB_TITLE", "TICKET_BEARING"]]
    except Exception:
        return pd.DataFrame(columns=["JOB_TITLE", "TICKET_BEARING"])


def _ticket_bearing_map() -> dict[str, bool]:
    """{normalised job title: is_ticket_bearing}."""
    df = load_classification()
    return {_norm(t): bool(b) for t, b in zip(df["JOB_TITLE"], df["TICKET_BEARING"], strict=False)}


def unclassified_titles(roster: pd.DataFrame) -> list[str]:
    """Distinct roster job titles NOT present in the classification table.

    Returns the original-cased titles (first seen) so the user classifies them
    exactly as Workday spells them.
    """
    known = set(_ticket_bearing_map())
    seen: dict[str, str] = {}
    for title in roster.get(JOB_TITLE_COL, pd.Series(dtype=str)):
        n = _norm(title)
        if n and n not in known and n not in seen:
            seen[n] = str(title).strip()
    return list(seen.values())


def split_by_ticket_bearing(roster: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition the roster into (ticket_bearing, non_ticket_bearing).

    Titles not in the classification table are treated as NON-ticket-bearing here
    (kept out of the roster) — the review step surfaces them for the user to
    classify. Only titles explicitly marked ticket-bearing are kept.
    """
    mapping = _ticket_bearing_map()
    keep = roster[JOB_TITLE_COL].map(lambda t: mapping.get(_norm(t), False))
    return roster[keep].reset_index(drop=True), roster[~keep].reset_index(drop=True)


def add_classifications(entries: list[dict]) -> int:
    """Persist new title classifications to the Snowflake table (MERGE upsert).

    `entries` items: {"title": str, "ticket_bearing": bool}. Returns rows written.
    """
    rows = [
        (e["title"].strip(), bool(e["ticket_bearing"]))
        for e in entries
        if e.get("title") and e["title"].strip()
    ]
    if not rows:
        return 0

    from services.workday_snowflake import get_session

    def _q(s: str) -> str:
        return str(s).replace("'", "''")

    values = ", ".join(f"('{_q(t)}', {str(b).upper()})" for t, b in rows)
    try:
        session = get_session()
        session.sql(
            f"MERGE INTO {config.JOB_TITLE_TABLE} t "
            f"USING (VALUES {values}) AS v(JOB_TITLE, TICKET_BEARING) "
            f"ON LOWER(TRIM(t.JOB_TITLE)) = LOWER(TRIM(v.JOB_TITLE)) "
            f"WHEN MATCHED THEN UPDATE SET TICKET_BEARING = v.TICKET_BEARING "
            f"WHEN NOT MATCHED THEN INSERT (JOB_TITLE, TICKET_BEARING) "
            f"  VALUES (v.JOB_TITLE, v.TICKET_BEARING)"
        ).collect()
        load_classification.clear()
    except Exception:
        return 0

    # Also rewrite the repo CSV seed so validated titles persist in version
    # control. Best-effort: only works where the file is writable (local dev, not
    # the read-only deployed container) — failure is silently ignored.
    _rewrite_csv_seed(rows)
    return len(rows)


def _rewrite_csv_seed(new_rows: list[tuple[str, bool]]) -> None:
    """Merge new (title, ticket_bearing) rows into the repo CSV seed and rewrite it.

    Existing titles (case-insensitive) are updated; new ones appended. No-op if
    the file can't be written (e.g. read-only deployed filesystem).
    """
    import csv
    from pathlib import Path

    path = Path(config.JOB_TITLE_CSV)
    try:
        existing: dict[str, tuple[str, bool]] = {}
        if path.exists():
            with path.open(newline="") as f:
                for r in csv.DictReader(f):
                    title = (r.get("JOB_TITLE") or "").strip()
                    if title:
                        tb = str(r.get("TICKET_BEARING", "")).strip().upper() == "TRUE"
                        existing[title.lower()] = (title, tb)
        for title, tb in new_rows:
            existing[title.strip().lower()] = (title.strip(), tb)

        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["JOB_TITLE", "TICKET_BEARING"])
            for title, tb in sorted(existing.values()):
                w.writerow([title, "TRUE" if tb else "FALSE"])
    except Exception:
        pass
