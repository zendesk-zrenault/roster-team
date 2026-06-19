# Monthly Team Roster Builder

A Streamlit app that rebuilds the monthly Advocacy team roster automatically.
It replaces a manual, multi-step process (filtering a Workday export, filtering a
Playvox export, copying both into Google Sheets, re-pointing dozens of formulas,
and chasing departed agents) with a guided wizard that produces a finished roster
you can open in Excel or paste into the live Google Sheet.

**Deployed:** Streamlit in Snowflake (SiS) —
`STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.ADVOCACY_MONTHLY_ROSTER` (account `zendesk-global`).
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for how to redeploy.

## What it does

1. **Target month** — pick the month/year being built.
2. **Workday roster** — pulls the current Advocacy headcount **live from Snowflake**
   (`CLEANSED.WORKDAY.WORKDAY_ROSTER_EMPLOYEE_INFO_SCD2`), or accepts the Workday
   XLS export as a fallback.
3. **Playvox roles** — upload the Playvox users CSV; blank roles and any role that
   isn't "Premier"/"Support" are dropped.
4. **Build** — unions the advocate emails from both sources, runs every lookup in
   Python, classifies team/role, and de-duplicates (keeping the most complete row).
   Region in Explore (col C) and Language (col M) carry forward from the basis.
5. **Review** — flags **departed/absent** agents (using Workday's `_FIVETRAN_DELETED`
   flag — no Slack needed), prompts for **new agents'** Region + Language, and lets
   you **Validate** (save to basis) or **Disregard** (drop, e.g. promoted to manager).
6. **Export** — download the finished roster:
   - **`.csv` (primary)** — fully-resolved values (names, Z2 names, Region in Explore,
     managers, dates). Opens cleanly in Excel **and** Google Sheets.
   - **`.xlsx` (advanced)** — keeps live Google formulas for pasting into the live Sheet.
     ⚠️ Excel will flag/strip these formulas — use the CSV for Excel.
7. **Apply corrections** — upload a previously-finalized roster a manager edited
   (added an agent, or changed Region in Explore / Language). Corrected carry-forward
   values are written back to the basis so they carry into next month's build.

## Persistent data (Snowflake tables)

Because the deployed app resets between sessions, the two carry-forward stores are
**Snowflake tables**, not local files:

| Table | Purpose |
|-------|---------|
| `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.ROSTER_BASIS` | Region in Explore + Language per email |
| `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER.Z2_NAMES_CACHE` | Zendesk display name (col E) per email |

Both grow automatically as new agents are validated, display names resolved, and
manager corrections applied. One-time seed: `scripts/setup_snowflake.py`.

## Quick start (local dev)

```bash
# 1. Create the environment (uv recommended)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 2. Configure the Snowflake connection (XLS fallback works without it,
#    but the basis/Z2 tables need a live connection)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#   then set connection_name to a Snowflake CLI connection (`snow connection list`)

# 3. Run
.venv/bin/streamlit run streamlit_app.py
```

## Verify it works

```bash
.venv/bin/python scripts/smoke_test.py    # full pipeline on the sample files
.venv/bin/ruff check .                     # lint
```

## Project layout

```
streamlit_app.py          # the wizard (UI flow only)
core/
  config.py               # all verified facts: table, cost-center prefixes, columns, persist tables
  role_rules.py           # team/role classification (ported from the sheet formulas)
  refs.py                 # month-aware tab names + roster formula generation
  lookups.py              # Z2 display-name cache (Snowflake-backed)
services/
  workday_snowflake.py    # live SCD2 query (current + Advocacy + not-deleted)
  workday_file.py         # XLS-upload fallback (same schema)
  playvox.py              # CSV ingest + role filter
  roster_builder.py       # email union, lookups, dedup, review helpers
  basis.py                # Region/Language carry-forward (Snowflake ROSTER_BASIS)
  zendesk_names.py        # column E: configurable Snowflake lookup + Z2 fallback
  corrections.py          # apply a manager-corrected roster back into the basis
  export_xlsx.py          # CSV export (resolved) + formula .xlsx export
ui/components.py          # review tables (new agents / departed / unresolved)
scripts/
  setup_snowflake.py      # one-time: create + seed the Snowflake tables
  smoke_test.py           # end-to-end pipeline test on samples
docs/DEPLOYMENT.md        # how to (re)deploy to Streamlit in Snowflake
data/                     # local seed files (gitignored — PII)
samples/                  # local input files (gitignored — PII)
```

## Notes & caveats

- **Cost-center filter** matches numeric prefixes (`277, 280, 285, 286, 287, 289`),
  not exact names, because Workday cost-center labels drift over time.
- **XLS fallback** cannot fill *Region in Workday* (column B) — that value is computed
  inside the Snowflake table, not present in the file export.
- **Column E (Zendesk display name):** no Snowflake users table was accessible from
  the `premier_metrics` connection during build, so the app falls back to the
  `Z2_NAMES_CACHE` table. Point it at a real table any time via `[zendesk]` in secrets.
- **PII:** `samples/` and `data/*.csv`/`*.xlsx` are gitignored. Never commit employee data.

## Reporting issues

Found a problem while building a month? Open a GitHub issue at
<https://github.com/zendesk-zrenault/roster-team/issues> with the step number, what you
expected, and what happened (a screenshot helps). See [CHANGELOG.md](CHANGELOG.md) for
the history of fixes.
