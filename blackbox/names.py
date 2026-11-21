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


_VEHICLE_FIXES = {"su": "Su", "mig": "MiG", "saab": "Saab", "jas": "JAS", "ussr": "", "us": "", "germ": "",
                  "uk": "", "jp": "", "cn": "", "it": "", "fr": "", "sw": "", "il": ""}


def vehicle(v: str | None) -> str | None:
    """'fa_18c_late' -> 'F/A-18C Late', 'su_30mkk' -> 'Su-30MKK', 'saab_jas39c' -> 'Saab JAS39C'."""
    if not v:
        return v
    if v.startswith("fa_"):
        v = "f/a_" + v[3:]
    tokens = [t for t in v.split("_") if t]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        low = t.lower()
        if low in _VEHICLE_FIXES and not out and nxt is not None and _VEHICLE_FIXES[low] == "":
            i += 1  # country prefix (ussr_t_80u -> T-80U)
            continue
        prefix = _VEHICLE_FIXES.get(low, t.upper() if len(t) <= 3 or "/" in t else t.title())
        if (nxt and any(c.isdigit() for c in nxt) and not any(c.isdigit() for c in t) and len(t) <= 4
                and low != "saab"):
            out.append(f"{_VEHICLE_FIXES.get(low, t.upper())}-{nxt.upper()}")
            i += 2
            continue
        out.append(t.upper() if any(c.isdigit() for c in t) else prefix)
        i += 1
    return " ".join(out)


def map_name(map_id: str | None) -> str | None:
    """'air_grand_canyon' -> 'Grand Canyon' (fallback when no localized name is known)."""
    if not map_id:
        return map_id
    s = re.sub(r"^(air|avg|av|tank)_", "", map_id)
    return s.replace("_", " ").title()
