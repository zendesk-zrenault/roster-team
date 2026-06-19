"""Month-aware tab names and roster formula generation.

The exported .xlsx is meant to be pasted into the live Google Sheet. The main
roster keeps *live formulas*; this module produces those formula strings with
references pointing at the correct new-month tabs.

Tabs produced by the app (names must match what the formulas reference):
  * roster:  "All Teams <Month> <Year>"            e.g. "All Teams July 2026"
  * workday: "<Month> <Year> Workday"              e.g. "July 2026 Workday"
  * playvox: "<Month> <Year> Playvox Roster"       e.g. "July 2026 Playvox Roster"

Formulas also reference two tabs that already live in the user's sheet:
  * "Z2 Names List"            (column E fallback)
  * "All Teams <prev month>"  (columns C and M carry-forward)

Improvement over the legacy sheet: columns G/H/I/J there keyed off the *name*
(D7); here every Workday lookup keys off *email* (F) against our clean landing
tab, removing the name-collision fragility.
"""

from core import config

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def month_name(month_num: int) -> str:
    return MONTHS[month_num - 1]


def prior_month(month_num: int, year: int) -> tuple[int, int]:
    """Return (month_num, year) of the month before the given one."""
    if month_num == 1:
        return 12, year - 1
    return month_num - 1, year


def tab_names(month_num: int, year: int) -> dict[str, str]:
    """All tab names for a given month, including the prior-month roster tab."""
    m = month_name(month_num)
    pm_num, pm_year = prior_month(month_num, year)
    return {
        "roster": f"All Teams {m} {year}",
        "workday": f"{m} {year} Workday",
        "playvox": f"{m} {year} Playvox Roster",
        "prior_roster": f"All Teams {month_name(pm_num)} {pm_year}",
    }


# Roster column F holds the email (the join key for every lookup).
# Landing-tab (workday) column order = config.WORKDAY_COLUMNS, so the 1-based
# VLOOKUP index of each field is its position there.
def _wd_index(field: str) -> int:
    return config.WORKDAY_COLUMNS.index(field) + 1


# Last landing-tab column letter (for the $A:$<last> VLOOKUP range).
def _wd_last_col_letter() -> str:
    n = len(config.WORKDAY_COLUMNS)
    # n is 17 -> "Q"; handles >26 too, though not needed here.
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def roster_formulas(row: int, tabs: dict[str, str]) -> dict[str, str]:
    """Return {column_letter: formula_or_value} for one roster data row.

    `row` is the 1-based spreadsheet row. Columns F (email) and N (comment) are
    written as values by the caller, so they are omitted here.
    """
    wd = f"'{tabs['workday']}'"
    pv = f"'{tabs['playvox']}'"
    prev = f"'{tabs['prior_roster']}'"
    last = _wd_last_col_letter()
    wd_range = f"{wd}!$A:${last}"

    return {
        # A — Roster Teams: native Google REGEXMATCH/IFS (self-contained on L).
        "A": (
            f'=IFERROR(IFS('
            f'REGEXMATCH(L{row},"Core Plus"),"Core Plus",'
            f'REGEXMATCH(L{row},"Service Desk"),"Service Desk",'
            f'REGEXMATCH(L{row},"Premier"),"Premier"),"Core")'
        ),
        # B — Region in Workday.
        "B": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('REGION')},FALSE),\"\")",
        # C — Region in Explore: carry forward from prior month, fallback to B.
        "C": (
            f"=IFERROR(VLOOKUP(F{row},"
            f"{{{prev}!$F:$F,{prev}!$C:$C}},2,FALSE),B{row})"
        ),
        # D — Advocate (full name).
        "D": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('FULL_NAME')},FALSE),\"\")",
        # E — Z2/Zendesk display name (existing live tab).
        "E": f"=IFERROR(VLOOKUP(F{row},'Z2 Names List'!A:B,2,FALSE),\"\")",
        # G — Job title.
        "G": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('JOB_TITLE')},FALSE),\"\")",
        # H — Start Date (hire date).
        "H": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('HIRE_DATE')},FALSE),\"\")",
        # I — Manager.
        "I": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('WORKER_MANAGER')},FALSE),\"\")",
        # J — Management Chain (C_STAFF_6 / "Level 06").
        "J": f"=IFERROR(VLOOKUP(F{row},{wd_range},{_wd_index('C_STAFF_6')},FALSE),\"\")",
        # K — Role: native Google REGEXMATCH/IFS (self-contained on L).
        "K": (
            f'=IFERROR(IFS('
            f'REGEXMATCH(L{row},"Service Desk"),"Service Desk",'
            f'REGEXMATCH(L{row},"Language Support"),"Language Support",'
            f'REGEXMATCH(L{row},"Customer Support"),"Customer Support",'
            f'REGEXMATCH(L{row},"Enhanced Support"),"Enhanced Support",'
            f'REGEXMATCH(L{row},"Adv Technical Support"),"Advanced Technical Support",'
            f'REGEXMATCH(L{row},"Tier 3"),"Advanced Technical Support",'
            f'REGEXMATCH(L{row},"Premier"),"Premier",'
            f'REGEXMATCH(L{row},"Digital Sales"),"Digital Sales"),"Customer Support")'
        ),
        # L — Role Validation: look up email in the new Playvox tab (D=email, E=roles).
        "L": f"=IFERROR(VLOOKUP(F{row},{pv}!$D:$E,2,FALSE),\"\")",
        # M — Foreign Language: carry forward from prior month, default English.
        "M": (
            f"=IFERROR(VLOOKUP(F{row},{prev}!$F:$M,8,FALSE),"
            f'"{config.DEFAULT_FOREIGN_LANGUAGE}")'
        ),
    }
