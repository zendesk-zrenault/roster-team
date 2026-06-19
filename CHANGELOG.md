# Changelog

All notable changes to the Monthly Team Roster Builder.

## 2026-06-19 — Deploy to Snowflake + CSV export + corrections

First production deployment to **Streamlit in Snowflake**, plus two fixes that
came out of testing the first downloaded file.

### Added
- **Deployed to Streamlit in Snowflake (SiS)** at
  `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.ADVOCACY_MONTHLY_ROSTER` so others can run
  the monthly build without a local setup. GitHub repo:
  <https://github.com/zendesk-zrenault/roster-team> (public).
- **Snowflake-backed persistence.** The two carry-forward stores moved from local
  files to Snowflake tables (`ROSTER_BASIS`, `Z2_NAMES_CACHE`) so data survives SiS
  container resets. One-time seed: `scripts/setup_snowflake.py` (342 basis + 5,332 Z2 rows).
- **CSV export (now the primary download).** `export_xlsx.build_csv()` writes the
  roster with every column resolved to a value — opens cleanly in Excel and Sheets.
- **Apply-corrections step (Step 7).** Upload a previously-finalized roster a manager
  edited; corrected Region in Explore / Language are upserted into the basis (and any
  Z2 names cached) so the changes carry into next month. New `services/corrections.py`
  and `basis.upsert_entries()` (MERGE: update existing + insert new; blanks don't clobber).
- **Footer:** "App last updated" timestamp + contact (zrenault@zendesk.com).

### Fixed
- **Corrupt .xlsx in Excel / missing Region in Explore + Z2 name.** The .xlsx export
  wrote Google-Sheets-only formulas (array literals, `IFS`/`REGEXMATCH`); Excel flagged
  the file as corrupt and stripped the formulas on repair, blanking those columns. The
  CSV export (resolved values) is the fix; the formula .xlsx is kept behind an "Advanced"
  expander for Google Sheets paste.
- **SiS deployment errors** (each resolved): switched container runtime → warehouse
  runtime (container lacked `openpyxl`); pinned `streamlit=1.52.2` + `openpyxl=3.1.5` in
  `environment.yml` (default 1.22.0 was too old for `st.file_uploader`/`st.data_editor`);
  stopped shipping `pyproject.toml` (its deps triggered a PyPI fetch → EAI/DNS error).

### Notes
- The "App last updated" footer timestamp is hardcoded — bump it manually on redeploy.
- Redeploy instructions: `docs/DEPLOYMENT.md`.

## 2026-06-19 (earlier) — Initial build

- 6-step wizard: month → Workday (Snowflake SCD2 / XLS fallback) → Playvox CSV →
  build → review → export. Workday `_FIVETRAN_DELETED` replaces the Slack departed
  check. Region in Explore (C) + Language (M) carry forward from a basis file. Per-row
  Validate/Disregard for new agents. Verified end-to-end on the June 2026 sample files.
