"""Parser for the in-game battle result text (copied from the hangar notification).

Example (Turkish client):
    [Operasyon] İspanya görevinde zafer!
    Yok edilen uçaklar          1    10112 SL    1197 RP
        2:44    F/A-18C Late    AIM-120C-5    Su-27SM     450 görev puanı ...
    ...
    Kazanılan: 20784 SL, 4109 CRP
    Faaliyet: 69%
    Bütün araçların otomatik tamiri: -3169 SL
    Oturum: 72c412c10016d34a
    Toplam: 17615 SL, 4109 CRP, 4109 RP

One copied text may hold several battles; split_battles() separates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER_RE = re.compile(r"^\[(?P<mode>[^\]]+)\]\s+(?P<map>.+?)\s+görevinde\s+(?P<res>zafer|yenilgi)!\s*$", re.M)
SESSION_RE = re.compile(r"^Oturum:\s*([0-9a-f]{6,})\s*$", re.M)
EARNED_RE = re.compile(r"^Kazanılan:\s*(?P<sl>-?\d+)\s*SL(?:,\s*(?P<crp>\d+)\s*CRP)?", re.M)
TOTAL_RE = re.compile(r"^Toplam:\s*(?P<sl>-?\d+)\s*SL(?:,\s*(?P<crp>\d+)\s*CRP)?(?:,\s*(?P<rp>\d+)\s*RP)?", re.M)
ACTIVITY_RE = re.compile(r"^Faaliyet:\s*(\d+)%", re.M)
REPAIR_RE = re.compile(r"otomatik tamiri:\s*(-?\d+)\s*SL", re.M)
PLAYED_RE = re.compile(r"^Oynanan Süre\s+(\d+):(\d\d)", re.M)
RESEARCH_RE = re.compile(r"^Araştırılan birim:\s*\n(?P<veh>.+?):\s*(?P<rp>\d+)\s*RP", re.M)
DAMAGED_RE = re.compile(r"^Hasarlı Araçlar:\s*(.+)$", re.M)
TIME_RE = re.compile(r"^\d+:\d\d$")
SL_RE = re.compile(r"(-?\d+)\s*SL")
RP_RE = re.compile(r"(\d+)\s*RP")


@dataclass
class ResultItem:
    category: str
    time_s: int | None
    vehicle: str | None
    weapon: str | None
    target: str | None
    sl: int | None
    rp: int | None
    raw: str


@dataclass
class BattleResult:
    session_id: str
    mode: str
    map_name: str
    result: str               # win | loss
    earned_sl: int | None = None
    earned_crp: int | None = None
    total_sl: int | None = None
    total_rp: int | None = None
    repair_sl: int | None = None
    activity: int | None = None
    played_s: int | None = None
    research_vehicle: str | None = None
    damaged_vehicles: str | None = None
    categories: dict = field(default_factory=dict)   # name -> {"count", "sl", "rp"}
    items: list[ResultItem] = field(default_factory=list)
    raw: str = ""


def split_battles(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    starts = [m.start() for m in HEADER_RE.finditer(text)]
    return [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]


def _i(m, g=1):
    return int(m.group(g)) if m and m.group(g) is not None else None


def _last_amount(rx, s):
    vals = rx.findall(s)
    return int(vals[-1]) if vals else None


def parse_battle(text: str) -> BattleResult | None:
    h = HEADER_RE.search(text)
    s = SESSION_RE.search(text)
    if not h or not s:
        return None
    br = BattleResult(session_id=s.group(1), mode=h.group("mode").strip(), map_name=h.group("map").strip(),
                      result="win" if h.group("res") == "zafer" else "loss", raw=text)
    e, t = EARNED_RE.search(text), TOTAL_RE.search(text)
    br.earned_sl, br.earned_crp = _i(e, "sl"), _i(e, "crp")
    br.total_sl, br.total_rp = _i(t, "sl"), _i(t, "rp")
    br.repair_sl = _i(REPAIR_RE.search(text))
    br.activity = _i(ACTIVITY_RE.search(text))
    p = PLAYED_RE.search(text)
    br.played_s = int(p.group(1)) * 60 + int(p.group(2)) if p else None
    r = RESEARCH_RE.search(text)
    br.research_vehicle = r.group("veh").strip() if r else None
    d = DAMAGED_RE.search(text)
    br.damaged_vehicles = d.group(1).strip() if d else None

    # Reward table: category lines start at column 0, detail lines are indented.
    category = None
    for line in text.split("\n")[1:]:
        if not line.strip():
            continue
        if line.startswith("Kazanılan:"):
            break  # footer (totals, research, boosters) - parsed by the regexes above
        if not line[0].isspace():
            parts = re.split(r"\s{2,}", line.strip())
            category = parts[0]
            nums = [x for x in parts[1:] if re.fullmatch(r"\d+", x)]
            br.categories[category] = {"count": int(nums[0]) if nums else None,
                                       "sl": _last_amount(SL_RE, line), "rp": _last_amount(RP_RE, line)}
            continue
        if category is None:
            continue
        parts = re.split(r"\s{2,}", line.strip())
        time_s = None
        if parts and TIME_RE.match(parts[0]):
            mm, ss = parts.pop(0).split(":")
            time_s = int(mm) * 60 + int(ss)
        vehicle = parts[0] if parts else None
        weapon = target = None
        if time_s is not None and len(parts) >= 3 and "görev puanı" not in parts[1]:
            weapon = None if parts[1].startswith("—") else parts[1]
            target = parts[2]
            if "görev puanı" in target or "hasar" in target or re.fullmatch(r"\d*\s*kg", target):
                target = None
        br.items.append(ResultItem(category, time_s, vehicle, weapon, target,
                                   _last_amount(SL_RE, line), _last_amount(RP_RE, line), line.strip()))
    return br


def parse_text(text: str) -> list[BattleResult]:
    out = []
    for chunk in split_battles(text):
        br = parse_battle(chunk)
        if br:
            out.append(br)
    return out


def looks_like_result(text: str) -> bool:
    return bool(text and HEADER_RE.search(text) and SESSION_RE.search(text))
