"""Build the main "All Teams <Month> <Year>" roster.

Inputs:
  * workday_df    — normalized Workday roster (config.WORKDAY_COLUMNS), active workers
  * playvox       — PlayvoxResult (filtered Business Roles)
  * z2_map        — {email: zendesk/z2 display name} for column E
  * prior_month_df (optional) — previous roster, for carry-forward of columns C and M

Output: a DataFrame with the roster's A..N headers (config.ROSTER_COLUMNS),
all values resolved in Python. This drives dedup, error detection, and the
departed-agent review *before* export. The export step (export_xlsx) decides
which columns are written as values vs. live formulas.

Row set = union of advocate emails from Workday (active Advocacy set) and the
filtered Playvox roster — matching the manual "copy all unique agent emails from
both tabs" step.
"""

import pandas as pd

from core import config, role_rules
from services.playvox import PlayvoxResult, role_by_email

# Marker used internally when a Workday lookup misses (no active record for the
# email). Surfaced to the review UI; never written to the final export.
UNRESOLVED = ""

ROSTER_HEADERS = list(config.ROSTER_COLUMNS.values())


def _prior_lookup(prior_month_df: pd.DataFrame | None, email_header: str, value_header: str):
    """Build {email: value} from a prior-month roster for carry-forward columns."""
    if prior_month_df is None or email_header not in prior_month_df.columns:
        return {}
    if value_header not in prior_month_df.columns:
        return {}
    sub = prior_month_df[[email_header, value_header]].dropna(subset=[email_header])
    emails = sub[email_header].astype("string").str.strip().str.lower()
    return dict(zip(emails, sub[value_header], strict=False))


def build_roster(
    workday_df: pd.DataFrame,
    playvox: PlayvoxResult,
    z2_map: dict[str, str] | None = None,
    prior_month_df: pd.DataFrame | None = None,
    region_map: dict[str, str] | None = None,
    language_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Assemble the A..N roster with all values resolved in Python.

    Columns C (Region in Explore) and M (Foreign Language) carry forward from
    the basis: pass `region_map`/`language_map` ({email: value}) directly, or a
    `prior_month_df` to derive them. Explicit maps win. Fallbacks: Workday region
    for C, config.DEFAULT_FOREIGN_LANGUAGE for M.
    """
    z2_map = z2_map or {}

    # --- Workday lookups keyed by email ---
    wd = workday_df.copy()
    wd["EMAIL"] = wd["EMAIL"].astype("string").str.strip().str.lower()
    wd = wd.drop_duplicates(subset="EMAIL", keep="first").set_index("EMAIL")

    def wd_get(email: str, col: str):
        if email in wd.index:
            val = wd.at[email, col]
            return "" if pd.isna(val) else val
        return UNRESOLVED

    role_map = role_by_email(playvox)  # email -> Business Roles string (col L)

    # Carry-forward maps for columns C and M. Explicit maps (from the basis file)
    # take precedence; otherwise derive from a prior-month roster DataFrame.
    email_h = config.ROSTER_COLUMNS["F"]
    region_explore_prev = region_map or _prior_lookup(
        prior_month_df, email_h, config.ROSTER_COLUMNS["C"]
    )
    language_prev = language_map or _prior_lookup(
        prior_month_df, email_h, config.ROSTER_COLUMNS["M"]
    )

    # --- Row set: union of Workday + Playvox emails ---
    emails = sorted(set(wd.index.dropna()) | set(role_map.keys()))

    rows = []
    for email in emails:
        if not email:
            continue

        role_validation = role_map.get(email, "")  # L
        region_workday = wd_get(email, "REGION")    # B (blank in XLS-fallback mode)

        row = {
            config.ROSTER_COLUMNS["A"]: role_rules.classify_team(role_validation),
            config.ROSTER_COLUMNS["B"]: region_workday,
            config.ROSTER_COLUMNS["C"]: region_explore_prev.get(email, region_workday),
            config.ROSTER_COLUMNS["D"]: wd_get(email, "FULL_NAME"),
            config.ROSTER_COLUMNS["E"]: z2_map.get(email, ""),
            config.ROSTER_COLUMNS["F"]: email,
            config.ROSTER_COLUMNS["G"]: wd_get(email, "JOB_TITLE"),
            config.ROSTER_COLUMNS["H"]: wd_get(email, "HIRE_DATE"),
            config.ROSTER_COLUMNS["I"]: wd_get(email, "WORKER_MANAGER"),
            config.ROSTER_COLUMNS["J"]: wd_get(email, "C_STAFF_6"),
            config.ROSTER_COLUMNS["K"]: role_rules.classify_role(role_validation),
            config.ROSTER_COLUMNS["L"]: role_validation,
            config.ROSTER_COLUMNS["M"]: language_prev.get(email, config.DEFAULT_FOREIGN_LANGUAGE),
            config.ROSTER_COLUMNS["N"]: "",
        }
        rows.append(row)

    roster = pd.DataFrame(rows, columns=ROSTER_HEADERS)
    return _dedupe_keep_densest(roster)


def _dedupe_keep_densest(roster: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate emails, keeping the row with the most non-empty cells.

    Mirrors the manual "remove duplicates, keep the line with the most data".
    """
    if roster.empty:
        return roster

    email_h = config.ROSTER_COLUMNS["F"]
    density = (roster.replace("", pd.NA).notna()).sum(axis=1)
    roster = roster.assign(_density=density)
    roster = (
        roster.sort_values("_density", ascending=False)
        .drop_duplicates(subset=email_h, keep="first")
        .drop(columns="_density")
        .sort_values(email_h)
        .reset_index(drop=True)
    )
    return roster


# --- Error / review helpers --------------------------------------------------

# Columns that come from the Workday lookup; if blank, the email had no active
# Workday record (the formula would be #N/A in the sheet).
WORKDAY_BACKED_COLUMNS = ["D", "G", "H", "I"]


def find_unresolved(roster: pd.DataFrame) -> pd.DataFrame:
    """Rows whose Workday-backed fields are empty (no active Workday match)."""
    if roster.empty:
        return roster
    cols = [config.ROSTER_COLUMNS[c] for c in WORKDAY_BACKED_COLUMNS]
    blank = roster[cols].replace("", pd.NA).isna().all(axis=1)
    return roster[blank].copy()


def split_departed(roster: pd.DataFrame, active_emails: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition the roster into (present_in_active_workday, departed).

    `active_emails` is the set of emails in the active (non-deleted) Workday set.
    Emails absent from it are candidates for deletion (departed per Workday).
    Playvox-only rows naturally fall into 'departed' and surface for review.
    """
    email_h = config.ROSTER_COLUMNS["F"]
    active_norm = {e.strip().lower() for e in active_emails if e}
    is_active = roster[email_h].isin(active_norm)
    return roster[is_active].copy(), roster[~is_active].copy()
