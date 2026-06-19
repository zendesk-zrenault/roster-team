# Deployment — Advocacy Monthly Roster → Streamlit in Snowflake

How this app is deployed to **Streamlit in Snowflake (SiS)**, and how to redeploy after changes.

> **TL;DR redeploy** (after committing your changes):
> ```bash
> cd "/Users/zrenault/Documents/GitHub Repos/Roster Team"
> find core services ui -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
> .venv/bin/snow streamlit deploy --replace -x \
>   --account zendesk-global --user zrenault@zendesk.com --authenticator externalbrowser \
>   --role STREAMLIT_APP_ADMIN_ROLE --database STREAMLIT_APPS \
>   --schema ADVOCACY_MONTHLY_ROSTER --warehouse PUBLIC_ZENDESK_L
> ```
> A browser opens for SSO. On success it prints the app URL.

---

## First-time setup (run once before first deploy)

### 1. Create Snowflake schema + tables and seed from local files

```bash
cd "/Users/zrenault/Documents/GitHub Repos/Roster Team"
.venv/bin/python scripts/setup_snowflake.py
```

This creates `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER` and two tables:
- `ROSTER_BASIS` — Region in Explore + Language for each advocate email (seeded from `data/basis_region_language.xlsx`)
- `Z2_NAMES_CACHE` — Zendesk display name per advocate email (seeded from `data/z2_names_list.csv`)

Both files are gitignored (PII). Run this script from a machine that has them.

### 2. Create the SiS schema in Snowflake (if it doesn't exist)

```sql
USE ROLE STREAMLIT_APP_ADMIN_ROLE;
CREATE SCHEMA IF NOT EXISTS STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER;
```

`setup_snowflake.py` does this too — just making it explicit.

### 3. Deploy

Run the TL;DR command above.

---

## The deployed app

- **Database / Schema:** `STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER`
- **App name:** `Advocacy_Monthly_Roster`
- **Runtime:** `SYSTEM$ST_CONTAINER_RUNTIME_PY3_11`, compute pool `SYSTEM_COMPUTE_POOL_CPU`
- **Warehouse:** `PUBLIC_ZENDESK_L`
- **Owner role:** `STREAMLIT_APP_ADMIN_ROLE`
- **Account:** `zendesk-global`

---

## ⚠️ Same gotchas as Premier Dashboard

### 1. Use the venv's `snow`, NOT the system one
System `snow` is 2.8.1 (Python 3.9) and does not support `definition_version: 2`.
Always use `.venv/bin/snow` (3.x).

### 2. Use `-x` to override the role
`premier_metrics` connection pins `role = "PUBLIC"` which lacks `CREATE STREAMLIT`.
The `-x` flag (temporary connection from flags) + `--role STREAMLIT_APP_ADMIN_ROLE` bypasses this.

### 3. Keep secrets + pycache OUT of the bundle
`snowflake.yml` lists only `.streamlit/config.toml` (not the whole `.streamlit/` dir).
Clear `__pycache__` before deploying (TL;DR does this).

---

## Persistent data (Snowflake tables, not local files)

Unlike a local run, the SiS container resets between sessions — local file writes are lost.
The two carry-forward stores are therefore Snowflake tables:

| Table | Purpose | Seeded from |
|-------|---------|-------------|
| `ROSTER_BASIS` | Region in Explore (col C) + Language (col M) per email | `data/basis_region_language.xlsx` |
| `Z2_NAMES_CACHE` | Zendesk display name (col E) per email | `data/z2_names_list.csv` |

Both grow automatically as users validate new agents or resolve display names each month.

---

## Full redeploy procedure

1. Commit your changes on `main`.
2. Test locally: `.venv/bin/streamlit run streamlit_app.py`
3. Run the TL;DR deploy command (clears pycache, deploys with `--replace`).
4. Verify:
   ```bash
   .venv/bin/snow streamlit describe Advocacy_Monthly_Roster -x \
     --account zendesk-global --user zrenault@zendesk.com --authenticator externalbrowser \
     --role STREAMLIT_APP_ADMIN_ROLE --database STREAMLIT_APPS \
     --schema ADVOCACY_MONTHLY_ROSTER
   ```

## Troubleshooting

- **`Version 2 is not supported`** → using system `snow`; switch to `.venv/bin/snow`.
- **`Insufficient privileges / role PUBLIC`** → missing `-x --role STREAMLIT_APP_ADMIN_ROLE`.
- **App crashes on start** → pull logs:
  ```bash
  .venv/bin/snow streamlit get-logs Advocacy_Monthly_Roster -x \
    --account zendesk-global --user zrenault@zendesk.com --authenticator externalbrowser \
    --role STREAMLIT_APP_ADMIN_ROLE --database STREAMLIT_APPS --schema ADVOCACY_MONTHLY_ROSTER
  ```
- **Empty basis / Z2 cache after deploy** → `setup_snowflake.py` hasn't been run yet, or ran against the wrong account.
