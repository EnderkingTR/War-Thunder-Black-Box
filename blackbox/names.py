"""Readable names for internal game ids (weapons, maps)."""

from __future__ import annotations

import re

_COUNTRY_PREFIXES = {"us", "su", "cn", "swd", "sw", "jp", "ir", "fr", "uk", "de", "ger", "it", "il", "za",
                     "r", "br", "in", "pk", "tw", "kr"}
_WEAPON_SUFFIXES = ("_default", "_sidewinder", "_sparrow", "_fa_18", "_short")


def weapon(w: str | None) -> str | None:
    """'us_aim_120c_5_default' -> 'AIM-120C-5', 'su_r_27er' -> 'R-27ER'."""
    if not w:
        return w
    s = w.lower()
    s = re.sub(r"_default.*$", "", s)  # 'aim_120c_5_default_switzerland' -> 'aim_120c_5'
    changed = True
    while changed:
        changed = False
        for suf in _WEAPON_SUFFIXES:
            if s.endswith(suf):
                s = s[: -len(suf)]
                changed = True
    parts = s.split("_")
    # drop a leading country prefix (su_r_27er -> r_27er), but keep a lone "r" (r_27er stays)
    if len(parts) > 1 and parts[0] in _COUNTRY_PREFIXES and not (parts[0] == "r" and len(parts) == 2):
        parts = parts[1:]
    s = "-".join(parts).upper()
    if re.match(r"^(\d+MM-|HE-|AP-|API|APDS|APFSDS|APHE|HEI|HEF|SAP|T-|FI-)", s) and not s.startswith("AIM"):
        return f"Top/mermi: {s}"
    s = re.sub(r"^AIM(\d)", r"AIM-\1", s)
    s = re.sub(r"^PL(\d)", r"PL-\1", s)
    s = re.sub(r"^RB(\d)", r"RB \1", s)
    return s


def map_name(map_id: str | None) -> str | None:
    """'air_grand_canyon' -> 'Grand Canyon' (fallback when no localized name is known)."""
    if not map_id:
        return map_id
    s = re.sub(r"^(air|avg|av|tank)_", "", map_id)
    return s.replace("_", " ").title()
