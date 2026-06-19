"""Reusable Streamlit UI pieces for the roster review step.

Keeps the main app file focused on flow; the editable-table + highlighting
logic lives here.
"""

import pandas as pd
import streamlit as st

from core import config

EMAIL_COL = config.ROSTER_COLUMNS["F"]


def summary_metrics(roster: pd.DataFrame, n_present: int, n_departed: int, n_unresolved: int) -> None:
    """Top-line counts for the built roster, plus a one-line team breakdown."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Roster rows", f"{len(roster):,}")
    c2.metric("Active in Workday", f"{n_present:,}")
    c3.metric("Departed / absent", f"{n_departed:,}", delta_color="inverse")
    c4.metric("Unresolved", f"{n_unresolved:,}", delta_color="inverse")

    teams = roster[config.ROSTER_COLUMNS["A"]].value_counts()
    st.caption("Teams: " + " · ".join(f"{team} {n}" for team, n in teams.items()))


def review_departed(departed: pd.DataFrame, key: str) -> set[str]:
    """Show departed/absent agents and let the user choose which to delete.

    Returns the set of emails the user marked for deletion. These agents are
    not in the active Workday set (likely terminated, or Playvox-only) — the
    Workday-based replacement for the old Slack deactivation check.
    """
    if departed.empty:
        st.success("No departed or absent agents — every roster email is in the active Workday set.")
        return set()

    st.warning(
        f"{len(departed)} agent(s) are **not** in the active Workday set "
        "(departed per Workday `_FIVETRAN_DELETED`, or present only in Playvox). "
        "Tick the ones to remove from the roster."
    )

    view = departed[[EMAIL_COL, config.ROSTER_COLUMNS["D"], config.ROSTER_COLUMNS["K"],
                     config.ROSTER_COLUMNS["L"]]].copy()
    view.insert(0, "Delete", True)  # default to delete; user can untick to keep

    edited = st.data_editor(
        view,
        key=key,
        hide_index=True,
        disabled=[EMAIL_COL, config.ROSTER_COLUMNS["D"], config.ROSTER_COLUMNS["K"],
                  config.ROSTER_COLUMNS["L"]],
        column_config={"Delete": st.column_config.CheckboxColumn("Delete", default=True)},
    )
    return set(edited.loc[edited["Delete"], EMAIL_COL])


def collect_new_agent_basis(
    new_agents: pd.DataFrame,
    region_options: list[str],
    language_options: list[str],
    key: str,
) -> list[dict]:
    """Prompt for Region in Explore + Language for Playvox agents new to the basis.

    `new_agents` has [Advocate Email, Advocate, Region in Workday]. Each row is
    pre-filled (Region = Workday region, Language = English) and fully editable as
    free text. Per row the user can:
      * tick **Validate** → save to the basis (and keep in the roster), or
      * tick **Disregard** → drop the agent from the roster entirely (e.g. now a
        manager); not written to the basis.

    Returns {"validated": [{email, region, language}], "disregarded": {emails}}.
    """
    if new_agents.empty:
        st.success(
            "No new agents to confirm — every Agyle/Playvox agent is already in "
            "the region/language basis."
        )
        return {"validated": [], "disregarded": set()}

    region_col = config.ROSTER_COLUMNS["C"]
    language_col = config.ROSTER_COLUMNS["M"]
    workday_region_col = config.ROSTER_COLUMNS["B"]
    advocate_col = config.ROSTER_COLUMNS["D"]

    st.warning(
        f"{len(new_agents)} Agyle/Playvox agent(s) are **not** in the basis. "
        "Check each row's Region in Explore and Foreign Language (pre-filled with "
        "the Workday region and English — overwrite as needed), then tick "
        "**Validate** to save it to the basis, or **Disregard** to drop the agent "
        "from the roster (e.g. they're now a manager)."
    )

    # Validate/Disregard default off so nothing happens until the user confirms.
    editor_df = pd.DataFrame({
        "Validate": False,
        "Disregard": False,
        EMAIL_COL: new_agents[EMAIL_COL].values,
        advocate_col: new_agents[advocate_col].values,
        region_col: new_agents[workday_region_col].replace("", pd.NA).fillna(""),
        language_col: config.DEFAULT_FOREIGN_LANGUAGE,
    })

    edited = st.data_editor(
        editor_df,
        key=key,
        hide_index=True,
        disabled=[EMAIL_COL, advocate_col],  # Region/Language remain free-text editable
        column_config={
            "Validate": st.column_config.CheckboxColumn(
                "Validate", default=False, help="Tick to write this row to the basis"
            ),
            "Disregard": st.column_config.CheckboxColumn(
                "Disregard", default=False, help="Tick to drop this agent from the roster"
            ),
            region_col: st.column_config.TextColumn(region_col, required=True),
            language_col: st.column_config.TextColumn(language_col, required=True),
        },
    )

    disregarded = {
        str(r[EMAIL_COL]).strip().lower()
        for _, r in edited.iterrows()
        if r["Disregard"]
    }
    validated = [
        {
            "email": r[EMAIL_COL],
            "region": str(r[region_col]).strip(),
            "language": str(r[language_col]).strip(),
        }
        for _, r in edited.iterrows()
        # A disregarded row is dropped, not saved — even if also ticked Validate.
        if r["Validate"] and not r["Disregard"]
    ]
    return {"validated": validated, "disregarded": disregarded}


def review_unresolved(unresolved: pd.DataFrame, key: str) -> pd.DataFrame:
    """Let the user inline-edit rows whose Workday lookup found nothing.

    Returns the edited frame so corrections flow into the final roster.
    """
    if unresolved.empty:
        st.success("No unresolved rows — every roster email matched a Workday record.")
        return unresolved

    st.warning(
        f"{len(unresolved)} row(s) had no Workday match (e.g. Playvox-only emails). "
        "Their Workday-backed columns (Advocate, Job title, Start Date, Manager) are blank. "
        "Fix inline if needed, or delete them in the step above."
    )
    return st.data_editor(unresolved, key=key, hide_index=True, num_rows="fixed")
