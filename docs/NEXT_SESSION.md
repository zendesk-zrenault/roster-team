# Next session — finish the Google-sync + live Z2-name work

Status as of 2026-07-06. Three pieces are **built + verified in isolation** but
**not yet wired into the app**. Pick up here.

## ✅ Done and committed
- **gcloud Google Sheets write access** — set up locally, confirmed read+write on the
  live "Explore Roster Teams" sheet. Skill installed at `~/.claude/skills/publish-to-drive/`.
- **"Roster Reference Data" Google Sheet** created on zrenault's Drive, 3 tabs seeded:
  `Job Titles` (164), `Z2 Names` (5332), `Region & Language Basis` (342).
  ID in `core/config.py` → `REFERENCE_SHEET_ID`. Recreate with
  `.venv/bin/python scripts/create_reference_sheet.py`.
- **`services/gsheet_sync.py`** — `sync_all()` / `sync_job_titles()` / `sync_z2()` /
  `sync_basis()`. Overwrites each tab from current state. LOCAL-only (gcloud token);
  safe no-op when `gcloud_available()` is False (deployed container). Tested: all True locally.

## ⏳ To wire tomorrow

### 1. Live Z2-name lookup (replaces the stale Z2 cache as PRIMARY source)
**Found the source.** No single table has email+name, so JOIN two:
- `FUNCTIONAL.CUSTOMER_EXPERIENCE.Z2_TICKETS` — has `TICKET_ASSIGNEE_ID` + `AGENT_EMAIL`
- `FUNCTIONAL.CUSTOMER_EXPERIENCE.Z2_TICKETS_UPDATE_TICKET_STATES` — has
  `TICKET_UPDATE_TICKET_ASSIGNEE_ID` + `TICKET_UPDATE_TICKET_ASSIGNEE_NAME` (29.8M populated rows)

Names carry OOO/PTO suffixes ("Jean Logro (OOO…) My back-up…") → clean by cutting at
first `(` or `-`. Verified query resolves **6,098 emails** to clean names
(uriel.costa→"Uriel Costa", gm.manuel→"Gm Manuel"):

```sql
WITH names AS (
  SELECT DISTINCT TICKET_UPDATE_TICKET_ASSIGNEE_ID AS AID,
         TRIM(REGEXP_SUBSTR(TICKET_UPDATE_TICKET_ASSIGNEE_NAME, '^[^(-]+')) AS ANAME_CLEAN
  FROM FUNCTIONAL.CUSTOMER_EXPERIENCE.Z2_TICKETS_UPDATE_TICKET_STATES
  WHERE TICKET_UPDATE_TICKET_ASSIGNEE_NAME IS NOT NULL
),
emails AS (
  SELECT DISTINCT TICKET_ASSIGNEE_ID AS AID, LOWER(AGENT_EMAIL) AS EMAIL
  FROM FUNCTIONAL.CUSTOMER_EXPERIENCE.Z2_TICKETS
  WHERE AGENT_EMAIL ILIKE '%@zendesk.com' AND TICKET_ASSIGNEE_ID IS NOT NULL
),
ranked AS (
  SELECT e.EMAIL, n.ANAME_CLEAN,
         ROW_NUMBER() OVER (PARTITION BY e.EMAIL ORDER BY LENGTH(n.ANAME_CLEAN) ASC) rn
  FROM emails e JOIN names n ON e.AID = n.AID
  WHERE n.ANAME_CLEAN IS NOT NULL AND n.ANAME_CLEAN != ''
)
SELECT EMAIL, ANAME_CLEAN FROM ranked WHERE rn = 1;
```
**Wire into `services/zendesk_names.py`**: this query becomes the PRIMARY resolver
(cache/`Z2__USER` fallback). `PRESENTATION.DDS.Z2__USER` was the "ideal" table Cortex
found but reads 0 non-null under our grants — do NOT use it.

### 2. Local-app gsheet sync
- On build: optionally `gsheet_sync.sync_all()` to refresh the sheet from Snowflake
  (so deployed-app validations show up).
- After each validation (job title / new-agent basis / corrections): call the matching
  `sync_*` so the Google Sheet stays current.
- Deployed app: gate on `gsheet_sync.gcloud_available()` — no-op + a caption that Google
  sync happens via the local app.

### 3. Deployed app must treat the Gsheet as the reference source (via Snowflake mirror)

**Goal (user):** when the DEPLOYED app builds a roster, it should use the reference
data that local-app validations posted to the Google Sheet — i.e. the Gsheet is the
source of truth for job titles / Z2 names / Region+Language basis.

**Constraint (hard, confirmed):** the deployed SiS app CANNOT read Google directly
(no gcloud, no internet egress). So it cannot query the Gsheet at runtime.

**Therefore — make the Gsheet the master and mirror it into Snowflake:**
- The Google Sheet "Roster Reference Data" is the human-editable **source of truth**.
- The **local app is the one-way bridge Gsheet → Snowflake**: on each local run (and/or
  a dedicated "Sync reference data" button), it READS the 3 Gsheet tabs and OVERWRITES
  the Snowflake tables (`ROSTER_BASIS`, `Z2_NAMES_CACHE`, and — if we move job titles back
  to a table — the job-title source) with the sheet's current contents.
- The **deployed app keeps reading Snowflake** (unchanged), so it transparently gets
  whatever the Gsheet holds as of the last local sync.

**Direction of sync matters — get it right:**
- Gsheet → Snowflake (this item): so deployed app sees Gsheet edits/validations.
- Snowflake → Gsheet (item 2 above): so Gsheet shows deployed-app validations.
  Both directions run from the local app. Decide conflict rule: **Gsheet wins** for a
  given key when both changed (it's the human-reviewed master), unless a newer Snowflake
  row exists — keep it simple: last-write-from-local-run overwrites, and log what changed.
- `gsheet_sync.py` currently only does Snowflake → Gsheet (`sync_*`). ADD the reverse:
  `pull_from_sheet()` that reads each tab and upserts into Snowflake. Add a Streamlit
  button "⟳ Sync reference data from Google Sheet" (local-only, gated on gcloud_available()).

**Honest limitation to state in the UI:** the deployed app is only as fresh as the last
local sync. It is NOT live against the Gsheet. Truly-live deployed reads would need a
Snowflake External Access Integration + Google service account (admin-gated, deferred).

### 4. Test, commit, redeploy, update memory.

## Reminders
- Deployed SiS app CANNOT reach Google (no gcloud/internet) — Google writes are LOCAL only.
- Basis + Z2 Snowflake tables intermittently corrupt to all-NULL; self-heal guards exist
  (`basis.load_basis` / `lookups.load_z2_cache` re-seed from local files). See
  [[roster-team-deployment]].
