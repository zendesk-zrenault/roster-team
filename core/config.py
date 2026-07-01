"""Central configuration for the Roster Team app.

Every value here was verified against live Snowflake data and the user's sample
sheets during planning. Adjust here rather than scattering literals across the app.
"""

# --- Snowflake source (Workday roster) ---------------------------------------
# Verified: 48-col SCD2 table; current record = VALID_TO_TIMESTAMP at the
# sentinel below; exactly one current row per EMPLOYEE_ID.
WORKDAY_TABLE = "CLEANSED.WORKDAY.WORKDAY_ROSTER_EMPLOYEE_INFO_SCD2"
SCD2_CURRENT_SENTINEL = "9999-12-31 00:00:00.000"

# Default Snowflake CLI connection name (overridable via st.secrets["dev"]).
DEFAULT_CONNECTION_NAME = "premier_metrics"

# Role the app runs under. The premier_metrics connection pins role=PUBLIC, which
# cannot read/write the STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER tables (reads return
# NULL, writes corrupt). The tables are owned by STREAMLIT_APP_ADMIN_ROLE, which is
# also the deployed SiS execution role — so use it locally too for consistency.
APP_ROLE = "STREAMLIT_APP_ADMIN_ROLE"

# Advocacy cost centers. Names drift over time ("280 Advocacy Core" -> "280 Core",
# spacing variants on 285), so we filter on the NUMERIC PREFIX, never the full string.
ADVOCACY_COST_CENTER_PREFIXES = ["277", "280", "285", "286", "287", "289"]

# Workday columns pulled from Snowflake (also the target schema the XLS fallback
# must map onto). _FIVETRAN_DELETED is the departure signal (WORKER_STATUS is
# always 1 and therefore useless).
WORKDAY_COLUMNS = [
    "EMAIL",
    "FULL_NAME",
    "FIRST_NAME",
    "LAST_NAME",
    "JOB_TITLE",
    "BUSINESS_TITLE",
    "HIRE_DATE",
    "WORKER_MANAGER",
    "MANAGER_ID",
    "C_STAFF_6",          # management chain "Level 06"
    "REGION",
    "COUNTRY",
    "LOCATION",
    "COST_CENTER",
    "EMPLOYEE_TYPE",
    "WORKER_TYPE",
    "_FIVETRAN_DELETED",
]

# --- Playvox CSV -------------------------------------------------------------
PLAYVOX_FIRST_NAME_COL = "First name"
PLAYVOX_LAST_NAME_COL = "Last name"
PLAYVOX_EMAIL_COL = "Email address"
PLAYVOX_ROLE_COL = "Business Roles"

# Keep only rows whose Business Roles contains one of these (case-insensitive);
# blank roles are always dropped. Verified: ~334 of 407 sample rows survive.
PLAYVOX_KEEP_ROLE_KEYWORDS = ["premier", "support"]

# --- Main roster output (the "All Teams <Month> <Year>" tab) -----------------
# Header row sits on row 6 in the live sheet; data starts on row 7.
ROSTER_HEADER_ROW = 6
ROSTER_DATA_START_ROW = 7

# Column letter -> header label, exactly as in the live sheet (A..N).
ROSTER_COLUMNS = {
    "A": "Roster Teams",
    "B": "Region in Workday",
    "C": "Region in Explore (Shift)",
    "D": "Advocate",
    "E": "Advocate Z2 name if different from column D",
    "F": "Advocate Email",
    "G": "Job title",
    "H": "Start Date",
    "I": "Manager",
    "J": "Management Chain",
    "K": "Role ",  # trailing space matches the live sheet header
    "L": "Role Validation (Playvox)",
    "M": "Foreign Language Advocate",
    "N": "Comment",
}

DEFAULT_FOREIGN_LANGUAGE = "English"

# --- Zendesk display-name source (roster column E) ---------------------------
# Authoritative source = a Snowflake table mapping advocate email -> Zendesk
# account display name. Discovery during build did NOT find one accessible from
# the premier_metrics connection (FCT_AGENT_CONTACT_LIST is customer CRM
# contacts; Z2_TICKETS has AGENT_EMAIL but no name column; ACCOUNT_USAGE is
# unauthorized). So this is OPTIONAL: set it (here or via st.secrets["zendesk"])
# once the right table is known, otherwise the app falls back to the Z2 cache.
#
#   ZENDESK_USERS_TABLE     = "DB.SCHEMA.USERS"
#   ZENDESK_USERS_EMAIL_COL = "EMAIL"
#   ZENDESK_USERS_NAME_COL  = "NAME"
ZENDESK_USERS_TABLE: str | None = None
ZENDESK_USERS_EMAIL_COL = "EMAIL"
ZENDESK_USERS_NAME_COL = "NAME"

# --- Snowflake persisted data (replaces local files for cloud deployment) ----
# These tables live in STREAMLIT_APPS.ADVOCACY_MONTHLY_ROSTER and are
# readable/writable by the app's Snowflake session. Run
# scripts/setup_snowflake.py once to create and seed them.
PERSIST_DATABASE = "STREAMLIT_APPS"
PERSIST_SCHEMA = "ADVOCACY_MONTHLY_ROSTER"

# Basis table for the two carry-forward columns (C and M) that exist in no
# uploaded source file. Seeded from data/basis_region_language.xlsx.
# Columns: EMAIL VARCHAR, REGION_EXPLORE VARCHAR, LANGUAGE VARCHAR.
BASIS_TABLE = f"{PERSIST_DATABASE}.{PERSIST_SCHEMA}.ROSTER_BASIS"

# Z2 Names cache: advocate email -> Zendesk account display name (roster col E).
# Seeded from data/z2_names_list.csv (5,332 rows). Grows each month.
# Columns: EMAIL VARCHAR, Z2_NAME VARCHAR.
Z2_TABLE = f"{PERSIST_DATABASE}.{PERSIST_SCHEMA}.Z2_NAMES_CACHE"

# Job-title classification: which Workday JOB_TITLEs are ticket-bearing. Only
# ticket-bearing titles stay in the roster; Non-Ticket Bearing AND management
# ("Ticket Bearing Mgmt") titles are dropped. Seeded from the repo CSV below and
# grown when the user classifies a previously-unseen title during review.
# Columns: JOB_TITLE VARCHAR, TICKET_BEARING BOOLEAN.
JOB_TITLE_TABLE = f"{PERSIST_DATABASE}.{PERSIST_SCHEMA}.JOB_TITLE_CLASSIFICATION"
JOB_TITLE_CSV = "data/job_title_classification.csv"
