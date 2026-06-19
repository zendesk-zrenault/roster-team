"""Role/team classification rules ported verbatim from the live sheet formulas.

These reproduce the Google Sheets REGEXMATCH/IFS chains for columns A and K,
which classify each advocate from their Playvox "Business Roles" string (col L).

Column A formula (Roster Teams):
    IFERROR(IFS(
        REGEXMATCH(L, "Core Plus"),    "Core Plus",
        REGEXMATCH(L, "Service Desk"), "Service Desk",
        REGEXMATCH(L, "Premier"),      "Premier"),
    "Core")

Column K formula (Role):
    IFS(
        REGEXMATCH(L, "Service Desk"),          "Service Desk",
        REGEXMATCH(L, "Language Support"),       "Language Support",
        REGEXMATCH(L, "Customer Support"),       "Customer Support",
        REGEXMATCH(L, "Enhanced Support"),       "Enhanced Support",
        REGEXMATCH(L, "Adv Technical Support"),  "Advanced Technical Support",
        REGEXMATCH(L, "Tier 3"),                 "Advanced Technical Support",
        REGEXMATCH(L, "Premier"),                "Premier",
        REGEXMATCH(L, "Digital Sales"),          "Digital Sales")
    -> default "Customer Support"

The patterns contain no regex metacharacters, so a case-sensitive substring test
faithfully reproduces Google Sheets RE2 REGEXMATCH behavior. Order matters: the
first matching rule wins, exactly like IFS.
"""

# (substring to find in col L, value to assign) — first match wins.
TEAM_RULES = [
    ("Core Plus", "Core Plus"),
    ("Service Desk", "Service Desk"),
    ("Premier", "Premier"),
]
TEAM_DEFAULT = "Core"

ROLE_RULES = [
    ("Service Desk", "Service Desk"),
    ("Language Support", "Language Support"),
    ("Customer Support", "Customer Support"),
    ("Enhanced Support", "Enhanced Support"),
    ("Adv Technical Support", "Advanced Technical Support"),
    ("Tier 3", "Advanced Technical Support"),
    ("Premier", "Premier"),
    ("Digital Sales", "Digital Sales"),
]
ROLE_DEFAULT = "Customer Support"


def _classify(role_validation: str | None, rules: list[tuple[str, str]], default: str) -> str:
    """First-match-wins substring classification (case-sensitive, like REGEXMATCH)."""
    text = "" if role_validation is None else str(role_validation)
    for needle, value in rules:
        if needle in text:
            return value
    return default


def classify_team(role_validation: str | None) -> str:
    """Column A: Roster Teams. Defaults to 'Core' (IFERROR fallback)."""
    return _classify(role_validation, TEAM_RULES, TEAM_DEFAULT)


def classify_role(role_validation: str | None) -> str:
    """Column K: Role. Defaults to 'Customer Support'."""
    return _classify(role_validation, ROLE_RULES, ROLE_DEFAULT)
