"""Local persisted lookups: the Z2 (Zendesk display name) cache.

The Z2 Names List maps Advocate Email -> Zendesk/Z2 display name. It is the
fallback source for roster column E and is appended to each month as new names
are resolved (from Snowflake or manual entry).
"""

from pathlib import Path

import pandas as pd

from core import config


def load_z2_cache() -> pd.DataFrame:
    """Return the Z2 cache as a DataFrame with columns Email, Z2 Name.

    Emails are normalized to lowercase. Returns an empty frame if the cache
    file does not exist yet.
    """
    path = Path(config.Z2_NAMES_CACHE)
    if not path.exists():
        return pd.DataFrame(columns=["Email", "Z2 Name"])
    df = pd.read_csv(path, dtype=str).fillna("")
    df["Email"] = df["Email"].str.strip().str.lower()
    df["Z2 Name"] = df["Z2 Name"].str.strip()
    return df.drop_duplicates(subset="Email", keep="last").reset_index(drop=True)


def z2_name_map() -> dict[str, str]:
    """Return {email_lower: z2_name} for fast lookups."""
    df = load_z2_cache()
    return dict(zip(df["Email"], df["Z2 Name"], strict=False))


def append_z2_names(new_pairs: dict[str, str]) -> int:
    """Append newly-resolved email->name pairs to the Z2 cache.

    Existing emails are not overwritten. Returns the number of rows added.
    """
    if not new_pairs:
        return 0

    existing = load_z2_cache()
    have = set(existing["Email"])

    rows = [
        {"Email": email.strip().lower(), "Z2 Name": str(name).strip()}
        for email, name in new_pairs.items()
        if email and name and email.strip().lower() not in have
    ]
    if not rows:
        return 0

    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.drop_duplicates(subset="Email", keep="first").reset_index(drop=True)

    path = Path(config.Z2_NAMES_CACHE)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return len(rows)
