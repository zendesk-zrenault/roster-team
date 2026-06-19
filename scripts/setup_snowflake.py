"""One-time Snowflake setup: create schema, tables, and seed from local files.

Run this ONCE before the first SiS deploy (or after a schema drop/recreate):

    cd "/Users/zrenault/Documents/GitHub Repos/Roster Team"
    .venv/bin/python scripts/setup_snowflake.py

Requires:
  - data/basis_region_language.xlsx  (342-row basis, gitignored)
  - data/z2_names_list.csv           (5,332-row Z2 cache, gitignored)
  - A live Snowflake session via the premier_metrics CLI connection.
"""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
from snowflake.snowpark import Session  # noqa: E402

from core import config  # noqa: E402

WORKDAY_COLS = config.ROSTER_COLUMNS  # letter -> label

BASIS_FILE = Path("data/basis_region_language.xlsx")
Z2_FILE = Path("data/z2_names_list.csv")

EMAIL_COL = config.ROSTER_COLUMNS["F"]
REGION_COL = config.ROSTER_COLUMNS["C"]
LANG_COL = config.ROSTER_COLUMNS["M"]

DDL = f"""
CREATE DATABASE IF NOT EXISTS {config.PERSIST_DATABASE};

CREATE SCHEMA IF NOT EXISTS {config.PERSIST_DATABASE}.{config.PERSIST_SCHEMA};

CREATE TABLE IF NOT EXISTS {config.BASIS_TABLE} (
    EMAIL     VARCHAR NOT NULL,
    REGION_EXPLORE VARCHAR,
    LANGUAGE  VARCHAR,
    CONSTRAINT pk_basis PRIMARY KEY (EMAIL)
);

CREATE TABLE IF NOT EXISTS {config.Z2_TABLE} (
    EMAIL    VARCHAR NOT NULL,
    Z2_NAME  VARCHAR,
    CONSTRAINT pk_z2 PRIMARY KEY (EMAIL)
);
"""


def _get_session() -> Session:
    return Session.builder.config("connection_name", config.DEFAULT_CONNECTION_NAME).create()


def _seed_basis(session: Session) -> int:
    if not BASIS_FILE.exists():
        print(f"  ⚠️  {BASIS_FILE} not found — skipping basis seed")
        return 0

    df = pd.read_excel(BASIS_FILE, header=0, dtype=str).fillna("")
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in [EMAIL_COL, REGION_COL, LANG_COL] if c not in df.columns]
    if missing:
        print(f"  ⚠️  Basis file missing columns {missing} — skipping")
        return 0

    df = df[[EMAIL_COL, REGION_COL, LANG_COL]].copy()
    df[EMAIL_COL] = df[EMAIL_COL].str.strip().str.lower()
    df = df[df[EMAIL_COL] != ""].drop_duplicates(subset=EMAIL_COL, keep="last")

    sp_df = session.create_dataframe(
        df.rename(columns={EMAIL_COL: "EMAIL", REGION_COL: "REGION_EXPLORE", LANG_COL: "LANGUAGE"})
    )
    sp_df.write.mode("overwrite").save_as_table(config.BASIS_TABLE)
    return len(df)


def _seed_z2(session: Session) -> int:
    if not Z2_FILE.exists():
        print(f"  ⚠️  {Z2_FILE} not found — skipping Z2 seed")
        return 0

    df = pd.read_csv(Z2_FILE, dtype=str).fillna("")
    df.columns = [str(c).strip() for c in df.columns]

    if "Email" not in df.columns or "Z2 Name" not in df.columns:
        print("  ⚠️  Z2 file missing Email/Z2 Name columns — skipping")
        return 0

    df = df[["Email", "Z2 Name"]].copy()
    df["Email"] = df["Email"].str.strip().str.lower()
    df = df[df["Email"] != ""].drop_duplicates(subset="Email", keep="last")

    sp_df = session.create_dataframe(df.rename(columns={"Email": "EMAIL", "Z2 Name": "Z2_NAME"}))
    sp_df.write.mode("overwrite").save_as_table(config.Z2_TABLE)
    return len(df)


def main() -> None:
    print(f"Connecting via '{config.DEFAULT_CONNECTION_NAME}'…")
    session = _get_session()
    print("  ✓ Connected")

    print("\nCreating schema and tables…")
    for stmt in [s.strip() for s in DDL.strip().split(";") if s.strip()]:
        session.sql(stmt).collect()
    print(f"  ✓ {config.PERSIST_DATABASE}.{config.PERSIST_SCHEMA} ready")

    print("\nSeeding basis table…")
    n = _seed_basis(session)
    print(f"  ✓ {n} rows written to {config.BASIS_TABLE}")

    print("\nSeeding Z2 names cache…")
    n = _seed_z2(session)
    print(f"  ✓ {n} rows written to {config.Z2_TABLE}")

    print("\nDone. Run scripts/smoke_test.py to verify, then deploy with:")
    print(
        "  .venv/bin/snow streamlit deploy --replace -x \\\n"
        "    --account zendesk-global --user zrenault@zendesk.com "
        "--authenticator externalbrowser \\\n"
        "    --role STREAMLIT_APP_ADMIN_ROLE --database STREAMLIT_APPS "
        f"--schema {config.PERSIST_SCHEMA} --warehouse PUBLIC_ZENDESK_L"
    )


if __name__ == "__main__":
    main()
