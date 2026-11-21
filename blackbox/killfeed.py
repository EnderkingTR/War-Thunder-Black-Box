"""Kill feed (hudmsg damage) parser.

Turns lines like
    "^yshTR^ ENDERKING_tr (F/A-18C Late) düşürdü: -TCRM- Foo (MiG-35)"
into structured events. Turkish is what the game client sends here; English
patterns are included best-effort. Unknown lines become kind="other" and are kept
raw so new patterns can be added later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (kind, phrase) - two-party verbs: "<actor> (<veh>) PHRASE <target> [(<veh>)]"
TWO_PARTY = [
    ("kill", "düşürdü:"),
    ("destroy", "imha etti:"),
    ("crit", "kritik hasar verdi"),
    ("severe", "ağır hasar verdi"),
    ("fire", "yaktı:"),
    ("hit", "vurdu:"),
    # English client
    ("kill", "shot down"),
    ("destroy", "destroyed"),
    ("crit", "critically damaged"),
    ("severe", "severely damaged"),
    ("fire", "set afire"),
    ("hit", "hit"),
]

# (kind, regex) - one-party lines
ONE_PARTY = [
    ("crash", re.compile(r"^(?P<a>.+?) \((?P<av>.*)\) (?:yere çakıldı|has crashed)\.?$")),
    ("first_strike", re.compile(r"^(?P<a>.+?) \((?P<av>.*)\) (?:ilk darbeyi vurdu|has delivered the first strike)!?$")),
    ("final_blow", re.compile(r"^(?P<a>.+?) \((?P<av>.*)\) (?:son vuruşu yaptı|has delivered the final blow)!?$")),
    ("achievement", re.compile(r'^(?P<a>.+?) \((?P<av>.*)\) ?, "(?P<extra>.+)" başarımını kazandı$')),
    ("achievement", re.compile(r'^(?P<a>.+?) \((?P<av>.*)\) has achieved "(?P<extra>.+)"$')),
    ("left", re.compile(r"^(?P<a>.+?) (?:oyundan çıktı|has disconnected from the game|has left the game)\.?$")),
    ("noise", re.compile(r"NET_PLAYER_DISCONNECT_FROM_GAME")),
]

# Squad tags: [TAG] =TAG= ^TAG^ -TAG- ╊TAG╋ and similar, as first word.
_TAG_RE = re.compile(r"^(\[[^\]]+\]|=[^=\s]+=|\^[^\^\s]+\^|-[^-\s]+-|╊[^╋\s]+╋|\{[^}]+\}|<[^>]+>)\s+")
# Leading platform/marker glyphs in names and vehicle names (⋇, ◄, ␗, ◌, ▄, ◘, ◔ ...)
_LEAD_SYMBOLS_RE = re.compile(r"^[^\w\[\]=^\-{<╊]+", re.UNICODE)
_VEH_SYMBOLS_RE = re.compile(r"^[^\w]+", re.UNICODE)


@dataclass
class KillfeedEvent:
    kind: str
    actor: str | None = None
    actor_squad: str | None = None
    actor_vehicle: str | None = None
    target: str | None = None
    target_squad: str | None = None
    target_vehicle: str | None = None
    extra: str | None = None  # achievement name, weapon path, ...
    raw: str = ""


def split_player(s: str) -> tuple[str, str | None]:
    """'^yshTR^ ENDERKING_tr' -> ('ENDERKING_tr', 'yshTR')"""
    s = s.strip()
    squad = None
    m = _TAG_RE.match(s)
    if m:
        squad = m.group(1)[1:-1]
        s = s[m.end():]
    s = _LEAD_SYMBOLS_RE.sub("", s)
    return s.strip(), squad


def clean_vehicle(v: str | None) -> str | None:
    if v is None:
        return None
    return _VEH_SYMBOLS_RE.sub("", v).strip() or None


def _split_name_vehicle(s: str) -> tuple[str, str | None]:
    """'Name (Vehicle)' -> ('Name', 'Vehicle'); vehicle may itself contain parentheses."""
    s = s.strip()
    if not s.endswith(")"):
        return s, None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                return s[:i].strip(), s[i + 1:-1]
    return s, None


def parse(msg: str) -> KillfeedEvent:
    raw = msg
    msg = msg.strip()
    for kind, rx in ONE_PARTY:
        m = rx.search(msg) if kind == "noise" else rx.match(msg)
        if m:
            if kind == "noise":
                return KillfeedEvent("noise", raw=raw)
            name, squad = split_player(m.group("a"))
            gd = m.groupdict()
            return KillfeedEvent(kind, actor=name, actor_squad=squad,
                                 actor_vehicle=clean_vehicle(gd.get("av")), extra=gd.get("extra"), raw=raw)

    for kind, phrase in TWO_PARTY:
        sep = f") {phrase} "
        idx = msg.find(sep)
        if idx < 0:
            continue
        left, right = msg[: idx + 1], msg[idx + len(sep):]
        a_name, a_veh = _split_name_vehicle(left)
        a_name, a_squad = split_player(a_name)
        ev = KillfeedEvent(kind, actor=a_name, actor_squad=a_squad, actor_vehicle=clean_vehicle(a_veh), raw=raw)
        if right.startswith("weapons/"):
            ev.kind = kind + "_weapon"  # e.g. a missile was destroyed / shot down
            ev.extra = right
            return ev
        if right.startswith("[ai] "):
            ev.extra = "ai"
            right = right[5:]
        t_name, t_veh = _split_name_vehicle(right)
        if t_veh is None and ev.extra == "ai":
            ev.target, ev.target_vehicle = None, clean_vehicle(t_name)
        else:
            ev.target, ev.target_squad = split_player(t_name)
            ev.target_vehicle = clean_vehicle(t_veh)
        return ev

    return KillfeedEvent("other", raw=raw)


def same_player(name: str | None, me: str) -> bool:
    return bool(name) and name.casefold() == me.casefold()
