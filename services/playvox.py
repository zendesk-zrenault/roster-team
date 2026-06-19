"""Playvox users CSV ingestion + Business Role filtering.

The monthly Playvox export is uploaded as CSV. We keep First/Last name, email,
and Business Roles, then filter:
  * drop rows with a blank Business Roles value
  * keep only rows whose Business Roles contains one of the configured keywords
    ("premier" / "support", case-insensitive)

Verified on the sample: 407 rows -> ~334 survive.

The result feeds:
  * roster column L (Role Validation) keyed by email
  * roster columns A and K (team/role classification, derived from L)
  * the "Month YYYY Playvox Roster" output tab (First / Last / Full / Email / Roles)
"""

from dataclasses import dataclass

import pandas as pd

from core import config


@dataclass
class PlayvoxResult:
    """Outcome of loading + filtering a Playvox export."""

    kept: pd.DataFrame  # columns: First name, Last name, Email address, Business Roles, Full Name
    total_rows: int
    blank_role_dropped: int
    no_keyword_dropped: int

    @property
    def kept_count(self) -> int:
        return len(self.kept)


def _has_keyword(role_value: str) -> bool:
    text = role_value.lower()
    return any(kw in text for kw in config.PLAYVOX_KEEP_ROLE_KEYWORDS)


def load_playvox_csv(file) -> PlayvoxResult:
    """Read + filter an uploaded Playvox CSV. `file` is a path or file-like object."""
    df = pd.read_csv(file, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    required = [
        config.PLAYVOX_FIRST_NAME_COL,
        config.PLAYVOX_LAST_NAME_COL,
        config.PLAYVOX_EMAIL_COL,
        config.PLAYVOX_ROLE_COL,
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Playvox CSV missing expected columns: {missing}. Found: {list(df.columns)[:20]}"
        )

    total = len(df)
    df = df[required].copy()
    df[config.PLAYVOX_ROLE_COL] = df[config.PLAYVOX_ROLE_COL].fillna("").str.strip()
    df[config.PLAYVOX_EMAIL_COL] = (
        df[config.PLAYVOX_EMAIL_COL].fillna("").str.strip().str.lower()
    )

    blank_mask = df[config.PLAYVOX_ROLE_COL] == ""
    blank_dropped = int(blank_mask.sum())
    df = df[~blank_mask]

    keyword_mask = df[config.PLAYVOX_ROLE_COL].apply(_has_keyword)
    no_keyword_dropped = int((~keyword_mask).sum())
    df = df[keyword_mask].copy()

    df["Full Name"] = (
        df[config.PLAYVOX_FIRST_NAME_COL].fillna("").str.strip()
        + " "
        + df[config.PLAYVOX_LAST_NAME_COL].fillna("").str.strip()
    ).str.strip()

    df = df.reset_index(drop=True)
    return PlayvoxResult(
        kept=df,
        total_rows=total,
        blank_role_dropped=blank_dropped,
        no_keyword_dropped=no_keyword_dropped,
    )


def role_by_email(result: PlayvoxResult) -> dict[str, str]:
    """{email_lower: Business Roles} for joining onto the roster (column L)."""
    df = result.kept
    return dict(zip(df[config.PLAYVOX_EMAIL_COL], df[config.PLAYVOX_ROLE_COL], strict=False))
