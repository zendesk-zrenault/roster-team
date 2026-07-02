"""Job-title classification: which Workday job titles bear tickets.

Only ticket-bearing agents belong on the roster. Non-Ticket Bearing titles
(directors, analysts, trainers, …) AND management titles ("Ticket Bearing Mgmt")
are dropped — per the rule that anything management-level is non-ticket-bearing.

Source of truth = the version-controlled CSV `data/job_title_classification.csv`,
bundled into the deployed app. BOTH apps read this file, so they always compare
the roster against the same list.

Two app modes (see config.IS_DEPLOYED):
  * LOCAL app  — writable repo. Validating new titles updates the CSV, appends an
    audit-log entry, and auto commits + pushes to GitHub `main`. The next deploy
    picks the new titles up.
  * DEPLOYED app (Streamlit in Snowflake) — read-only container. Validating new
    titles applies for the CURRENT session/month only; nothing is persisted. The
    UI says so. New titles become permanent once added via the local app + redeploy.

Comparison is case-insensitive and whitespace-normalised so minor Workday drift
("Sr." spacing, trailing spaces) doesn't create phantom "new" titles.
"""

import csv
from pathlib import Path

import pandas as pd
import streamlit as st

from core import config

JOB_TITLE_COL = config.ROSTER_COLUMNS["G"]  # "Job title"


def _norm(title) -> str:
    """Normalise a title for matching: trimmed, collapsed spaces, lowercased."""
    if title is None or (not isinstance(title, str) and pd.isna(title)):
        return ""
    return " ".join(str(title).split()).strip().lower()


def is_deployed() -> bool:
    """True when running in the read-only Streamlit-in-Snowflake container.

    The local dev app can write the repo + push to git; the deployed one can't.
    Detected via an active Snowpark session (present only inside SiS).
    """
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return True
    except Exception:
        return False


@st.cache_data(ttl=600, show_spinner=False)
def load_classification() -> pd.DataFrame:
    """Return the classification list as [JOB_TITLE, TICKET_BEARING(bool)].

    Reads the bundled CSV — the single source of truth for both apps.
    """
    try:
        df = pd.read_csv(config.JOB_TITLE_CSV, dtype=str)
        df["TICKET_BEARING"] = (
            df["TICKET_BEARING"].astype(str).str.strip().str.upper() == "TRUE"
        )
        df = df[df["JOB_TITLE"].notna() & (df["JOB_TITLE"].astype(str).str.strip() != "")]
        return df[["JOB_TITLE", "TICKET_BEARING"]].reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["JOB_TITLE", "TICKET_BEARING"])


def _ticket_bearing_map() -> dict[str, bool]:
    """{normalised job title: is_ticket_bearing}."""
    df = load_classification()
    return {_norm(t): bool(b) for t, b in zip(df["JOB_TITLE"], df["TICKET_BEARING"], strict=False)}


def unclassified_titles(roster: pd.DataFrame) -> list[str]:
    """Distinct roster job titles NOT present in the classification list.

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


def split_by_ticket_bearing(
    roster: pd.DataFrame, extra_ticket_bearing: set[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition the roster into (ticket_bearing, non_ticket_bearing).

    Titles not in the list are treated as NON-ticket-bearing (kept out of the
    roster) — the review step surfaces them to classify. `extra_ticket_bearing`
    is a set of normalised titles the user marked ticket-bearing this session
    (used by the deployed app, where the choice isn't persisted to the CSV).
    """
    mapping = _ticket_bearing_map()
    extra = extra_ticket_bearing or set()

    def _keep(title) -> bool:
        n = _norm(title)
        return mapping.get(n, False) or n in extra

    keep = roster[JOB_TITLE_COL].map(_keep)
    return roster[keep].reset_index(drop=True), roster[~keep].reset_index(drop=True)


def add_classifications(entries: list[dict]) -> dict:
    """Persist new title classifications.

    `entries` items: {"title": str, "ticket_bearing": bool}.

    LOCAL app: update the CSV, append an audit-log row, and git commit + push.
    DEPLOYED app: no-op on disk (read-only) — the caller keeps the ticket-bearing
    picks in session state for the current month instead.

    Returns {"written": int, "pushed": bool, "deployed": bool, "message": str}.
    """
    rows = [
        (e["title"].strip(), bool(e["ticket_bearing"]))
        for e in entries
        if e.get("title") and e["title"].strip()
    ]
    if not rows:
        return {"written": 0, "pushed": False, "deployed": is_deployed(), "message": "Nothing to save."}

    if is_deployed():
        # Read-only container: can't persist. Caller applies for this session only.
        return {
            "written": 0,
            "pushed": False,
            "deployed": True,
            "message": (
                "Deployed app: this classification applies to **this month only** "
                "and is not saved. To make it permanent, add it in the local app "
                "(which updates the shared list on GitHub) and redeploy."
            ),
        }

    # --- Local app: update CSV + audit log, then commit & push. ---
    _rewrite_csv_seed(rows)
    _append_audit(rows)
    load_classification.clear()
    pushed, msg = _git_commit_push(rows)
    return {
        "written": len(rows),
        "pushed": pushed,
        "deployed": False,
        "message": msg,
    }


def _rewrite_csv_seed(new_rows: list[tuple[str, bool]]) -> None:
    """Merge new (title, ticket_bearing) rows into the CSV and rewrite it sorted."""
    path = Path(config.JOB_TITLE_CSV)
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


def _append_audit(new_rows: list[tuple[str, bool]]) -> None:
    """Append an audit row per classification: when, title, decision, who.

    Timestamps come from the OS clock via a subprocess (the Streamlit runtime
    forbids datetime.now()); best-effort — audit must never block the save.
    """
    path = Path(config.JOB_TITLE_AUDIT_CSV)
    ts = _now_utc()
    who = _git_user()
    header_needed = not path.exists()
    try:
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if header_needed:
                w.writerow(["TIMESTAMP_UTC", "JOB_TITLE", "TICKET_BEARING", "ADDED_BY"])
            for title, tb in new_rows:
                w.writerow([ts, title, "TRUE" if tb else "FALSE", who])
    except Exception:
        pass


def _now_utc() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["date", "-u", "+%Y-%m-%d %H:%M:%S UTC"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def _git_user() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path(config.JOB_TITLE_CSV).resolve().parent.parent),
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _git_commit_push(new_rows: list[tuple[str, bool]]) -> tuple[bool, str]:
    """Commit the CSV + audit log and push to origin/main. Returns (ok, message)."""
    import subprocess

    repo = str(Path(config.JOB_TITLE_CSV).resolve().parent.parent)
    titles = ", ".join(t for t, _ in new_rows)
    n = len(new_rows)
    commit_msg = (
        f"Add {n} job-title classification(s): {titles}\n\n"
        "Auto-committed from the local Roster app after manager validation.\n"
        "See data/job_title_audit_log.csv for the audit trail.\n\n"
        "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    )

    def _run(args):
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60
        )

    try:
        _run(["add", config.JOB_TITLE_CSV, config.JOB_TITLE_AUDIT_CSV])
        commit = _run(["commit", "-m", commit_msg])
        if commit.returncode != 0 and "nothing to commit" in (commit.stdout + commit.stderr).lower():
            return False, "No file change to commit (title may already exist)."
        push = _run(["push", "origin", "HEAD:main"])
        if push.returncode == 0:
            return True, (
                f"Saved {n} title(s), updated the shared list, and pushed to GitHub. "
                "Redeploy to apply them in the deployed app."
            )
        return False, (
            f"Saved {n} title(s) locally and committed, but the push failed:\n"
            f"{push.stderr.strip()[:300]}\nRun `git push` manually."
        )
    except Exception as exc:  # noqa: BLE001 - surface to the UI
        return False, f"Saved locally, but git automation failed: {exc}"
