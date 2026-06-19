---
name: roster
description: Build the monthly Advocacy team roster. Use when the user wants to create/refresh the monthly Team Roster, process the Workday + Playvox exports, or run the roster app. Triggers: roster, monthly roster, team roster, Playvox, Workday headcount, Advocacy headcount.
---

# Monthly Team Roster

Automates the monthly Advocacy roster build: Workday (Snowflake) + Playvox CSV →
a Google-Sheets-ready `.xlsx`. Full design is in this project's `CLAUDE.md`.

## When to use

- "Build / refresh the team roster for <month>"
- "Process this month's Playvox / Workday export"
- "Run the roster app"

## Workflow

### Step 1 — Launch the app (preferred path)

The app is the intended monthly tool. From the project root:

```bash
.venv/bin/streamlit run streamlit_app.py
```

Then guide the user through the 6 steps: pick month → load Workday (Snowflake or
XLS) → upload Playvox CSV → Build → Review departed/unresolved → Download `.xlsx`.
Tell them to paste the downloaded tabs into the live Google Sheet.

### Step 2 — Or run headless (scripted/diagnostic)

To validate inputs or build without the UI, drive the services directly (this is
what `scripts/smoke_test.py` does):

```python
from services.workday_file import load_workday_file      # or workday_snowflake.fetch_workday_roster()
from services.playvox import load_playvox_csv
from services.roster_builder import build_roster
from services.export_xlsx import build_workbook
from core import lookups

wd = load_workday_file("<workday.xlsx>")                  # XLS fallback
pv = load_playvox_csv("<playvox.csv>")
roster = build_roster(wd, pv, z2_map=lookups.z2_name_map())
data = build_workbook(roster, wd, pv, month_num=7, year=2026)
```

### Step 3 — Sanity-check the numbers

Confirm with the user before exporting:
- Workday advocacy headcount per cost center looks right.
- Playvox survivor count is plausible (blank + non-Premier/Support dropped).
- Departed/absent list (Workday `_FIVETRAN_DELETED`) is expected before deleting.

## Key facts (see CLAUDE.md for the full list)

- Cost centers filtered by **numeric prefix** `277/280/285/286/287/289`.
- Departed check uses **`_FIVETRAN_DELETED`**, NOT `WORKER_STATUS` (always 1), NOT Slack.
- Output keeps **live Google formulas**, refs rewritten to the new month's tabs.
- Column E (Zendesk name) falls back to the local Z2 cache unless a Snowflake users
  table is configured in `.streamlit/secrets.toml`.

## Don't

- Don't commit `samples/` or `data/*.csv` (employee PII).
- Don't filter cost centers by exact label (they drift).
