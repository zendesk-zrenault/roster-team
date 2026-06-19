# Monthly Team Roster Builder

A Streamlit app that rebuilds the monthly Advocacy team roster automatically.
It replaces a manual, multi-step process (filtering a Workday export, filtering a
Playvox export, copying both into Google Sheets, and re-pointing dozens of
formulas) with a guided 6-step wizard that produces a **Google-Sheets-ready
`.xlsx`** you paste into the live roster doc.

## What it does

1. **Target month** — pick the month/year being built.
2. **Workday roster** — pulls the current Advocacy headcount **live from Snowflake**
   (`CLEANSED.WORKDAY.WORKDAY_ROSTER_EMPLOYEE_INFO_SCD2`), or accepts the Workday
   XLS export as a fallback.
3. **Playvox roles** — upload the Playvox users CSV; blank roles and any role that
   isn't "Premier"/"Support" are dropped.
4. **Build** — unions the advocate emails from both sources, runs every lookup in
   Python, classifies team/role, and de-duplicates (keeping the most complete row).
5. **Review** — flags **departed/absent** agents (using Workday's `_FIVETRAN_DELETED`
   flag — no Slack needed) and **unresolved** rows, for confirm-delete or inline edit.
6. **Export** — download an `.xlsx` with three tabs (the roster + its two source
   tabs). The roster keeps **live Google formulas**, with references already pointing
   at the new month's tabs.

## Quick start

```bash
# 1. Create the environment (uv recommended)
uv venv --python 3.11 .venv
uv pip install --python .venv -e .

# 2. Configure the Snowflake connection (optional — XLS fallback works without it)
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
streamlit_app.py          # 6-step wizard (UI flow only)
core/
  config.py               # all verified facts: table, cost-center prefixes, columns
  role_rules.py           # team/role classification (ported from the sheet formulas)
  refs.py                 # month-aware tab names + roster formula generation
  lookups.py              # Z2 display-name cache (read/append)
services/
  workday_snowflake.py    # live SCD2 query (current + Advocacy + not-deleted)
  workday_file.py         # XLS-upload fallback (same schema)
  playvox.py              # CSV ingest + role filter
  roster_builder.py       # email union, lookups, dedup, review helpers
  zendesk_names.py        # column E: configurable Snowflake lookup + Z2 fallback
  export_xlsx.py          # writes the 3-tab workbook
ui/components.py          # review tables (departed / unresolved)
data/z2_names_list.csv    # seeded Z2 cache (gitignored — contains PII)
samples/                  # local input files (gitignored — contains PII)
scripts/                  # seed_z2_cache.py, smoke_test.py
```

## Notes & caveats

- **Cost-center filter** matches numeric prefixes (`277, 280, 285, 286, 287, 289`),
  not exact names, because Workday cost-center labels drift over time.
- **XLS fallback** cannot fill *Region in Workday* (column B) — that value is computed
  inside the Snowflake table, not present in the file export.
- **Column E (Zendesk display name):** no Snowflake users table was accessible from
  the `premier_metrics` connection during build, so the app falls back to the local
  Z2 Names List cache. Point it at a table any time via `[zendesk]` in secrets — see
  `CLAUDE.md`.
- **PII:** `samples/` and `data/*.csv` are gitignored. Never commit employee data.
