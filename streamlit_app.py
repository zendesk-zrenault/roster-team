"""Monthly Team Roster builder.

Wizard:
  1. Setup       — pick the target month/year.
  2. Workday     — pull the Advocacy roster from Snowflake (or upload the XLS).
  3. Playvox     — upload + filter the Playvox users CSV.
  4. Build       — assemble the roster (email union, lookups, dedup).
  5. Review      — handle departed/absent and unresolved rows.
  6. Export      — download the Google-Sheets-ready .xlsx.

Workday data replaces the old manual XLS paste + IMPORTRANGE; the departed-agent
check uses Workday `_FIVETRAN_DELETED` instead of Slack. The exported roster keeps
live Google formulas with refs rewritten to the new month's tabs.
"""

import datetime

import streamlit as st

from core import config, lookups, refs
from services import basis, export_xlsx, roster_builder, zendesk_names
from services.playvox import load_playvox_csv
from services.workday_file import load_workday_file
from services.workday_snowflake import fetch_workday_roster, test_connection
from ui import components

st.set_page_config(page_title="Team Roster Builder", page_icon="📋", layout="wide")

# --- State ---
today = datetime.date.today()
st.session_state.setdefault("month", today.month)
st.session_state.setdefault("year", today.year)
st.session_state.setdefault("workday_df", None)
st.session_state.setdefault("workday_source", None)
st.session_state.setdefault("playvox", None)
st.session_state.setdefault("roster", None)

st.title("📋 Monthly Team Roster Builder")
st.caption(
    "Workday (Snowflake) + Playvox → a Google-Sheets-ready roster. "
    "Live formulas preserved; departed agents flagged from Workday."
)

# === Step 1: Setup ===========================================================
st.header("1 · Target month")
c1, c2 = st.columns(2)
with c1:
    st.session_state.month = st.selectbox(
        "Month",
        list(range(1, 13)),
        index=st.session_state.month - 1,
        format_func=refs.month_name,
    )
with c2:
    st.session_state.year = st.number_input(
        "Year", min_value=2024, max_value=2100, value=st.session_state.year, step=1
    )

month, year = st.session_state.month, int(st.session_state.year)
tabs = refs.tab_names(month, year)
st.info(
    f"Will produce tabs **{tabs['roster']}**, **{tabs['workday']}**, **{tabs['playvox']}** "
    f"— with formulas referencing **{tabs['prior_roster']}** for carry-forward."
)

# === Step 2: Workday =========================================================
st.header("2 · Workday roster")
source = st.radio(
    "Source",
    ["Snowflake (recommended)", "Upload Workday XLS (fallback)"],
    horizontal=True,
)

if source.startswith("Snowflake"):
    if st.button("Query Workday from Snowflake", type="primary"):
        ok, msg = test_connection()
        if not ok:
            st.error(f"Snowflake connection failed: {msg}")
            st.info("Configure `.streamlit/secrets.toml` or use the XLS upload fallback.")
        else:
            df = fetch_workday_roster(include_deleted=False)
            st.session_state.workday_df = df
            st.session_state.workday_source = "snowflake"
else:
    uploaded = st.file_uploader("Workday headcount export (.xlsx)", type=["xlsx", "xls"])
    if uploaded is not None:
        try:
            st.session_state.workday_df = load_workday_file(uploaded)
            st.session_state.workday_source = "file"
            st.caption("⚠️ File mode: Region in Workday (col B) will be blank — the table provides it, the file does not.")
        except ValueError as exc:
            st.error(str(exc))

if st.session_state.workday_df is not None:
    wd = st.session_state.workday_df
    st.success(f"Workday roster loaded: {len(wd):,} active advocates ({st.session_state.workday_source}).")
    cc = wd["COST_CENTER"].value_counts().rename_axis("Cost Center").reset_index(name="Count")
    st.dataframe(cc, hide_index=True, width="content")

# === Step 3: Playvox =========================================================
st.header("3 · Playvox roles")
pv_file = st.file_uploader("Playvox users export (.csv)", type=["csv"])
if pv_file is not None:
    try:
        st.session_state.playvox = load_playvox_csv(pv_file)
    except ValueError as exc:
        st.error(str(exc))

if st.session_state.playvox is not None:
    pv = st.session_state.playvox
    st.success(
        f"Playvox: kept **{pv.kept_count}** of {pv.total_rows} "
        f"(dropped {pv.blank_role_dropped} blank, {pv.no_keyword_dropped} non-Premier/Support)."
    )

# === Step 4: Build ===========================================================
st.header("4 · Build roster")
ready = st.session_state.workday_df is not None and st.session_state.playvox is not None
if not ready:
    st.info("Load both the Workday roster and the Playvox CSV to build.")
elif st.button("Build roster", type="primary"):
    wd = st.session_state.workday_df
    pv = st.session_state.playvox

    emails = sorted(set(wd["EMAIL"].dropna()) | set(pv.kept["Email address"].dropna()))
    z2_map, appended = zendesk_names.resolve_display_names(emails)
    if appended:
        st.toast(f"Added {appended} new name(s) to the Z2 cache.")

    # Region in Explore (C) and Language (M) carry forward from the basis file.
    st.session_state.roster = roster_builder.build_roster(
        wd, pv, z2_map=z2_map,
        region_map=basis.region_map(),
        language_map=basis.language_map(),
    )

# === Step 5 & 6: Review + Export ============================================
if st.session_state.roster is not None:
    roster = st.session_state.roster
    wd = st.session_state.workday_df
    active_emails = set(wd["EMAIL"].dropna())

    present, departed = roster_builder.split_departed(roster, active_emails)
    unresolved = roster_builder.find_unresolved(roster)
    # Only confirm agents present in the Agyle/Playvox roster (valid business role).
    playvox_emails = set(st.session_state.playvox.kept["Email address"].dropna())
    new_agents = basis.find_new_agents(roster, eligible_emails=playvox_emails)

    st.header("5 · Review")
    components.summary_metrics(roster, len(present), len(departed), len(unresolved))

    st.subheader("New agents — confirm Region in Explore + Language")
    new_result = components.collect_new_agent_basis(
        new_agents,
        region_options=basis.existing_regions(),
        language_options=basis.existing_languages(),
        key="new_agents_editor",
    )
    validated = new_result["validated"]
    disregarded = new_result["disregarded"]
    if st.button(
        f"💾 Save {len(validated)} validated entry(ies) to the basis file",
        disabled=not validated,
    ):
        added = basis.append_entries(validated)
        st.success(f"Saved {added} new agent(s) to the basis. Rebuild to apply.")

    st.subheader("Departed / absent agents")
    to_delete = components.review_departed(departed, key="departed_editor")

    st.subheader("Unresolved rows")
    components.review_unresolved(unresolved, key="unresolved_editor")

    # Apply this session's validated new-agent region/language to the in-memory
    # roster so the preview/export reflect them even before a rebuild.
    region_col = config.ROSTER_COLUMNS["C"]
    language_col = config.ROSTER_COLUMNS["M"]
    overrides = {e["email"]: e for e in validated}
    if overrides:
        emask = roster[components.EMAIL_COL].isin(overrides)
        roster.loc[emask, region_col] = roster.loc[emask, components.EMAIL_COL].map(
            lambda e: overrides[e]["region"]
        )
        roster.loc[emask, language_col] = roster.loc[emask, components.EMAIL_COL].map(
            lambda e: overrides[e]["language"]
        )

    # Remove departed/absent (ticked above) AND disregarded new agents (e.g. now
    # a manager) from the final roster.
    drop_emails = set(to_delete) | disregarded
    final = roster[~roster[components.EMAIL_COL].isin(drop_emails)].reset_index(drop=True)

    st.header("6 · Export")
    st.write(
        f"Final roster: **{len(final):,}** rows "
        f"(removed {len(to_delete)} departed/absent, {len(disregarded)} disregarded)."
    )
    data = export_xlsx.build_workbook(final, wd, st.session_state.playvox, month, year)
    st.download_button(
        "⬇️ Download roster .xlsx",
        data=data,
        file_name=export_xlsx.output_filename(month, year),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    with st.expander("Final roster preview"):
        st.dataframe(final, hide_index=True)

st.divider()
try:
    st.caption(f"Z2 name cache: {len(lookups.load_z2_cache()):,} email→name pairs.")
except Exception:
    pass
st.caption("App last updated: 2026-06-19 18:12 UTC")
st.caption("For more information contact zrenault@zendesk.com")
