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

import pandas as pd
import streamlit as st

from core import config, lookups, refs
from services import (
    basis,
    corrections,
    export_xlsx,
    job_titles,
    roster_builder,
    zendesk_names,
)
from services.playvox import load_playvox_csv
from services.workday_file import load_workday_file
from services.workday_snowflake import (
    fetch_data_freshness,
    fetch_workday_roster,
    test_connection,
)
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
# New-agent review actions accumulated across reruns (list can be long, so the
# user can process it in several passes). validated_basis: {email: {region, language}}.
st.session_state.setdefault("validated_basis", {})
st.session_state.setdefault("disregarded_emails", set())

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
    # Show how fresh the Snowflake data is so you can judge whether to trust the
    # live pull or upload a more recent Workday XLS instead.
    last_sync = fetch_data_freshness()
    if last_sync is not None:
        # Normalise to tz-naive UTC (LAST_ALTERED is tz-aware; the Fivetran
        # fallback is tz-naive) so the age subtraction always works.
        synced = pd.Timestamp(last_sync)
        synced = synced.tz_convert(None) if synced.tzinfo is not None else synced
        now = pd.Timestamp.utcnow().tz_localize(None)
        age_hours = (now - synced) / pd.Timedelta(hours=1)
        stamp = synced.strftime("%Y-%m-%d %H:%M UTC")
        if age_hours <= 36:
            st.success(f"🟢 Snowflake Workday data last refreshed **{stamp}** (~{age_hours:.0f}h ago).")
        elif age_hours <= 24 * 7:
            st.warning(
                f"🟡 Snowflake Workday data last refreshed **{stamp}** "
                f"(~{age_hours / 24:.1f} days ago). Consider uploading a fresher Workday XLS."
            )
        else:
            st.error(
                f"🔴 Snowflake Workday data is stale — last refreshed **{stamp}** "
                f"(~{age_hours / 24:.0f} days ago). Upload a current Workday XLS instead."
            )
    else:
        st.caption("Could not read the Snowflake refresh timestamp.")

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
    # Fresh build → reset the accumulated new-agent review actions.
    st.session_state.validated_basis = {}
    st.session_state.disregarded_emails = set()

# === Step 5 & 6: Review + Export ============================================
if st.session_state.roster is not None:
    roster = st.session_state.roster
    wd = st.session_state.workday_df
    active_emails = set(wd["EMAIL"].dropna())

    st.header("5 · Review")

    # --- Job-title gate: drop non-ticket-bearing rows; classify unknown titles --
    # Any title not marked ticket-bearing (incl. management) is removed. Titles the
    # classification table has never seen are surfaced for the user to classify.
    unknown_titles = job_titles.unclassified_titles(roster)
    if unknown_titles:
        st.subheader("New job titles — confirm ticket-bearing")
        st.warning(
            f"{len(unknown_titles)} job title(s) aren't in the classification list. "
            "Mark each as **Ticket bearing** (stays on the roster) or leave unticked "
            "for non-ticket-bearing / management (removed). Saved for next month."
        )
        jt_df = pd.DataFrame({"Job title": unknown_titles, "Ticket bearing": False})
        jt_edited = st.data_editor(
            jt_df,
            key="job_title_editor",
            hide_index=True,
            disabled=["Job title"],
            column_config={
                "Ticket bearing": st.column_config.CheckboxColumn(
                    "Ticket bearing", default=False,
                    help="Tick if this role handles tickets (stays on the roster)",
                ),
            },
        )
        if st.button("Save job-title classifications", type="primary"):
            entries = [
                {"title": r["Job title"], "ticket_bearing": bool(r["Ticket bearing"])}
                for _, r in jt_edited.iterrows()
            ]
            n = job_titles.add_classifications(entries)
            job_titles.load_classification.clear()
            st.success(f"Saved {n} classification(s). Applying to the roster…")
            st.rerun()
        st.info("Classify the titles above and save before continuing the review.")
        st.stop()

    # All titles known → keep only ticket-bearing rows.
    roster, dropped_ntb = job_titles.split_by_ticket_bearing(roster)

    present, departed = roster_builder.split_departed(roster, active_emails)
    unresolved = roster_builder.find_unresolved(roster)
    # Only confirm agents present in the Agyle/Playvox roster (valid business role).
    playvox_emails = set(st.session_state.playvox.kept["Email address"].dropna())
    all_new_agents = basis.find_new_agents(roster, eligible_emails=playvox_emails)

    # Already-processed rows (validated or disregarded in a previous pass) drop off
    # the list so a long list can be worked through in several passes.
    processed = set(st.session_state.validated_basis) | st.session_state.disregarded_emails
    new_agents = all_new_agents[
        ~all_new_agents[components.EMAIL_COL].isin(processed)
    ].reset_index(drop=True)

    components.summary_metrics(roster, len(present), len(departed), len(unresolved))
    if len(dropped_ntb):
        st.caption(
            f"Removed {len(dropped_ntb)} non-ticket-bearing / management row(s) "
            "by job title."
        )

    st.subheader("New agents — confirm Region in Explore + Language")
    done = len(processed)
    if done:
        st.caption(
            f"Processed so far this session: {len(st.session_state.validated_basis)} "
            f"validated, {len(st.session_state.disregarded_emails)} disregarded. "
            f"{len(new_agents)} still to review."
        )
    new_result = components.collect_new_agent_basis(
        new_agents,
        region_options=basis.existing_regions(),
        language_options=basis.existing_languages(),
        key="new_agents_editor",
    )
    validated = new_result["validated"]
    disregarded = new_result["disregarded"]

    apply_label = (
        f"✅ Apply selections — save {len(validated)} to basis, "
        f"drop {len(disregarded)} disregarded"
    )
    if st.button(apply_label, disabled=not (validated or disregarded), type="primary"):
        added = basis.append_entries(validated) if validated else 0
        # Accumulate across passes so processed rows disappear and multi-step works.
        for e in validated:
            st.session_state.validated_basis[e["email"]] = e
        st.session_state.disregarded_emails |= disregarded
        st.success(
            f"Applied: saved {added} to the basis, dropped {len(disregarded)} "
            f"from the roster. Remaining rows updated below."
        )
        st.rerun()

    st.subheader("Departed / absent agents")
    to_delete = components.review_departed(departed, key="departed_editor")

    st.subheader("Unresolved rows")
    components.review_unresolved(unresolved, key="unresolved_editor")

    # Apply this session's validated new-agent region/language to the in-memory
    # roster so the preview/export reflect them (accumulated across passes).
    region_col = config.ROSTER_COLUMNS["C"]
    language_col = config.ROSTER_COLUMNS["M"]
    overrides = dict(st.session_state.validated_basis)
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
    drop_emails = set(to_delete) | st.session_state.disregarded_emails
    final = roster[~roster[components.EMAIL_COL].isin(drop_emails)].reset_index(drop=True)

    # === Step 6: Apply corrections from a finalized month ===================
    st.header("6 · Apply corrections (optional)")
    st.caption(
        "Upload a previously-finalized roster. Corrected values are written back "
        "to the basis so they carry forward into next month's build."
    )
    corr_file = st.file_uploader(
        "Corrected roster (.csv or .xlsx)", type=["csv", "xlsx"], key="corrections_uploader"
    )
    if corr_file is not None:
        try:
            corr_df = corrections.load_corrected_roster(corr_file)
            st.success(f"Read {len(corr_df):,} rows from the corrected roster.")
            with st.expander("Preview corrected roster"):
                st.dataframe(corr_df, hide_index=True)
            if st.button("Apply corrections to the basis", type="primary"):
                r = corrections.apply_corrections(corr_df)
                basis.load_basis.clear()
                lookups.load_z2_cache.clear()

                changed = r["new_agents"] + r["region_changed"] + r["language_changed"]
                if changed == 0 and r["z2_added"] == 0:
                    st.info(
                        "No changes — every value in the uploaded roster already "
                        "matches the basis. Nothing to carry forward."
                    )
                else:
                    st.success(
                        "✅ Corrections applied to the basis "
                        "(they'll carry into next month's build). Here's what changed:"
                    )
                    st.markdown(
                        f"- **{r['new_agents']}** new agent(s) added\n"
                        f"- **{r['region_changed']}** Region in Explore value(s) changed\n"
                        f"- **{r['language_changed']}** Language value(s) changed\n"
                        f"- {r['unchanged']} agent(s) already matched (no change)\n"
                        f"- **{r['z2_added']}** Z2 display name(s) added to the cache"
                    )
        except ValueError as exc:
            st.error(str(exc))

    # === Step 7: Export =====================================================
    st.header("7 · Export")
    st.write(
        f"Final roster: **{len(final):,}** rows "
        f"(removed {len(to_delete)} departed/absent, {len(disregarded)} disregarded)."
    )

    # CSV holds the fully-resolved values (Z2 name, Region in Explore, manager,
    # etc.) — opens cleanly in Excel and Google Sheets. This is the primary export.
    csv_data = export_xlsx.build_csv(final, month, year)
    csv_name = export_xlsx.output_csv_filename(month, year)
    st.download_button(
        "⬇️ Download roster (.csv)",
        data=csv_data,
        file_name=csv_name,
        mime="text/csv",
        type="primary",
    )

    with st.expander("Advanced: .xlsx with live Google formulas (for pasting into the Sheet)"):
        st.caption(
            "This workbook keeps live VLOOKUP/REGEXMATCH formulas tied to the "
            "monthly tabs. It is built for **Google Sheets** — Excel will warn "
            "about the formulas and may strip them. Use the CSV above for Excel."
        )
        xlsx_data = export_xlsx.build_workbook(final, wd, st.session_state.playvox, month, year)
        st.download_button(
            "⬇️ Download roster .xlsx (Google Sheets)",
            data=xlsx_data,
            file_name=export_xlsx.output_filename(month, year),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with st.expander("Final roster preview"):
        st.dataframe(final, hide_index=True)

st.divider()
try:
    st.caption(f"Z2 name cache: {len(lookups.load_z2_cache()):,} email→name pairs.")
except Exception:
    pass
st.caption("App last updated: 2026-07-01 15:43 UTC")
st.caption("For more information contact zrenault@zendesk.com")
