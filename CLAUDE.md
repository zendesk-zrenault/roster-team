# AI Development Guide — Roster Team

This app automates the monthly Advocacy team-roster build. Read this before
editing; it captures the verified facts and the non-obvious design decisions.

## Deployment & persistence (Snowflake-backed)

The app is deployed to **Streamlit in Snowflake (SiS)**, not a local-only tool.
SiS containers reset between sessions, so the two carry-forward stores are
**Snowflake tables**, not local files (full deploy guide: `docs/DEPLOYMENT.md`):
- `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.ROSTER_BASIS` (EMAIL, REGION_EXPLORE, LANGUAGE)
- `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.Z2_NAMES_CACHE` (EMAIL, Z2_NAME)

`services/basis.py` and `core/lookups.py` read/write these via Snowpark SQL.
Seed them once with `scripts/setup_snowflake.py`. **SiS gotchas** (all documented
in DEPLOYMENT.md, each cost a deploy cycle): use the warehouse runtime not the
container runtime; pin packages in `environment.yml` (`streamlit=1.52.2`,
`openpyxl=3.1.5`); never ship `pyproject.toml` (triggers a PyPI fetch → EAI error).

## Carry-forward columns C and M — the basis table

**Region in Explore (col C)** and **Foreign Language (col M)** are NOT in any
uploaded source — they are maintained month to month in the **`ROSTER_BASIS`
Snowflake table** keyed by Advocate Email. Fallbacks: Workday Region (col B) for
C, `config.DEFAULT_FOREIGN_LANGUAGE` for M.

Flow (`services/basis.py`):
- `region_map()` / `language_map()` — {email: value} carried into `build_roster`
  via its `region_map=` / `language_map=` params (these win over `prior_month_df`).
- `find_new_agents(roster, eligible_emails=)` — roster emails NOT in the basis,
  restricted to Playvox/Agyle-eligible agents. The review step
  (`ui.components.collect_new_agent_basis`) prompts for their Region + Language
  (free-text TextColumns; Region defaults to the Workday region, Language to
  English), with per-row **Validate** (save to basis) / **Disregard** (drop from
  roster, e.g. promoted to manager) checkboxes.
- `append_entries([...])` — inserts confirmed new agents (idempotent; skips known).
- `upsert_entries([...])` — MERGE used by the corrections step: updates existing
  emails AND inserts new ones; a blank incoming value never clobbers an existing one.

The "💾 Save to basis" button persists validated entries; the in-memory roster is
also patched so the current preview/export reflect them pre-rebuild. The exported
formulas (core/refs.py) still VLOOKUP the prior-month roster tab as the live-sheet
carry-forward, independent of the basis table.

## Export & corrections

Two export formats (`services/export_xlsx.py`):
- **`build_csv()` (primary)** — the roster with every column resolved to a VALUE.
  Opens cleanly in Excel and Sheets. Use this for anything Excel touches.
- **`build_workbook()` (advanced)** — the 3-tab formula workbook (below). Built for
  Google Sheets; **Excel flags its Google-only formulas as corrupt and strips them**
  on repair (this is why formula-driven cols like C and E came back blank in Excel —
  the fix was the CSV path).

The **corrections step** (`services/corrections.py`, app Step 7) ingests a
previously-finalized roster (.csv or .xlsx, tolerant of header-on-row-6) and writes
its Region in Explore + Language back to the basis via `upsert_entries`, plus any
col-E Z2 names to the cache. This is how a manager's manual edits carry forward.

## Architecture (3 layers)

1. `services/` — data in/out: Snowflake query, XLS/CSV ingest, roster assembly, export.
2. `core/` — pure logic + config: classification rules, tab-name/formula generation, caches.
3. `streamlit_app.py` + `ui/` — the wizard UI. Keep logic out of the UI layer.

**Principle:** explicit data flow. Functions take DataFrames/dicts and return them;
no hidden session-state reads inside services. Streamlit: **1.52.2 in the deployed
SiS app** (pinned in `environment.yml`), newer locally. When touching Streamlit
syntax, consult the bundled `developing-with-streamlit` skill (in the sibling
`zdp-streamlit-starter-kit`) and avoid APIs newer than 1.52.

## Verified facts (don't re-derive — confirmed against live Snowflake)

- **Workday table** `CLEANSED.WORKDAY.WORKDAY_ROSTER_EMPLOYEE_INFO_SCD2` (SCD2).
  - Current record = `VALID_TO_TIMESTAMP = '9999-12-31 00:00:00.000'`; one row per employee.
  - **`WORKER_STATUS` is useless** — always `1`. Never use it for active/terminated.
  - **`_FIVETRAN_DELETED` is the departure signal** (TRUE = left). This replaces Slack.
  - Already contains `REGION`, `COUNTRY`, `LOCATION`, `C_STAFF_1..6`, `WORKER_MANAGER` —
    so the old Region/Manager lookup tabs are unnecessary.
- **Advocacy cost centers** = numeric prefixes `277, 280, 285, 286, 287, 289`. Filter on
  the **prefix**, never the full label (labels drift: "280 Advocacy Core" → "280 Core").
- **Playvox filter**: drop blank Business Roles; keep only roles containing "premier"/"support".
  407 sample rows → 334 survive.
- **Column E source**: discovery found no email→display-name Zendesk table reachable from
  `premier_metrics` (FCT_AGENT_CONTACT_LIST = customer CRM contacts; Z2_TICKETS has
  AGENT_EMAIL but no name; ACCOUNT_USAGE unauthorized). Falls back to the Z2 cache.

All of these live in `core/config.py`. Change them there, not inline.

## The formula .xlsx design (the "advanced" export)

The formula `.xlsx` has three tabs and is meant to be pasted into the live Google Sheet
(the CSV is the default export — see "Export & corrections" above):
- `<Month> <Year> Workday` and `<Month> <Year> Playvox Roster` — **values** (landing tabs).
- `All Teams <Month> <Year>` — the roster. Columns **F** (email) and **N** (comment) are
  values; **everything else is a live Google formula** generated by `core/refs.py`, with
  references already rewritten to the new month's tabs + the prior-month roster + the
  existing `Z2 Names List` tab. Header on row 6, data from row 7 (matches the live sheet).

`build_roster()` *also* resolves every column to a value internally — that value pass is
what drives dedup, the departed check, and unresolved detection. The exported formulas and
the internal values are kept consistent; if you change one, change the other.

## Common changes

- **Different cost centers** → edit `ADVOCACY_COST_CENTER_PREFIXES` in `core/config.py`.
- **New/changed role mapping** → edit `TEAM_RULES` / `ROLE_RULES` in `core/role_rules.py`
  (first-match-wins, mirrors the sheet's `IFS`). Update the matching formula text in
  `core/refs.py` so the live formula and the Python value agree.
- **Add a roster column** → add to `ROSTER_COLUMNS` (config), give it a formula or value in
  `refs.roster_formulas()`, and source it in `roster_builder.build_roster()`.
- **Wire up the Zendesk name table** → set `[zendesk]` in `.streamlit/secrets.toml`:
  ```toml
  [zendesk]
  users_table = "DB.SCHEMA.USERS"
  email_col   = "EMAIL"
  name_col    = "NAME"
  ```
  `services/zendesk_names.py` will use it and append new names to the Z2 cache.

## Snowflake access

Reuse `services.workday_snowflake.get_session()` (cached `@st.cache_resource`; active
session in SiS, else `Session.builder.config("connection_name", …)` from
`~/.snowflake/connections.toml`). Read-only metadata under `SNOWFLAKE.ACCOUNT_USAGE` is
**unauthorized** on `premier_metrics` — test metadata queries under caller's rights before
relying on them.

## Verify

```bash
.venv/bin/python scripts/smoke_test.py   # end-to-end on samples; asserts key counts
.venv/bin/ruff check .
.venv/bin/streamlit run streamlit_app.py
```

## Don't

- ❌ Use `WORKER_STATUS` for active/terminated (always 1).
- ❌ Filter cost centers by exact string.
- ❌ Commit `samples/` or `data/*.csv` (employee PII; both gitignored).
- ❌ Add `use_container_width` (deprecated in 1.58 — use `width="stretch"`).
