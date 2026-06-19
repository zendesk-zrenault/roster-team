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

# --- Local persisted data ----------------------------------------------------
DATA_DIR = "data"
Z2_NAMES_CACHE = "data/z2_names_list.csv"  # columns: Email, Z2 Name

# Basis file for the two carry-forward columns that exist in NO uploaded source:
#   C "Region in Explore (Shift)" and M "Foreign Language Advocate".
# It is a prior-roster-shaped workbook (roster headers on row 1) keyed by email.
# New agents get appended back here after the user supplies their values, so the
# basis grows month over month. Fallbacks: Workday region for C, "English" for M.
BASIS_FILE = "data/basis_region_language.xlsx"
BASIS_HEADER_ROW = 1  # 1-indexed row holding the column headers
