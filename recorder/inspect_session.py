"""War Thunder BlackBox - recording inspector (discovery phase).

Reads a session recorded by record.py and reports what the game API actually
delivered: every field per endpoint with type and value range, map object kinds,
all kill-feed / damage messages, chat, and mission status changes.

Usage:
    python inspect_session.py              # newest recording
    python inspect_session.py 20261121_203000
    python inspect_session.py path/to/session_folder

The report is printed and also saved as report.txt inside the session folder.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "recordings"


def find_session(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if p.is_dir():
            return p
        p = RECORDINGS_DIR / arg
        if p.is_dir():
            return p
        sys.exit(f"Session not found: {arg}")
    sessions = sorted(d for d in RECORDINGS_DIR.glob("*") if d.is_dir() and not d.name.startswith("_"))
    if not sessions:
        sys.exit(f"No recordings in {RECORDINGS_DIR}")
    return sessions[-1]


def read_records(session: Path):
    gz = session / "events.jsonl.gz"
    plain = session / "events.jsonl"
    opener = (lambda: gzip.open(gz, "rt", encoding="utf-8")) if gz.exists() else (
        lambda: open(plain, encoding="utf-8"))
    with opener() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # last line can be cut if the recorder was killed


class FieldStats:
    def __init__(self) -> None:
        self.types: Counter = Counter()
        self.count = 0
        self.min = None
        self.max = None
        self.samples: Counter = Counter()

    def add(self, v) -> None:
        self.count += 1
        self.types[type(v).__name__] += 1
        if isinstance(v, bool):
            self.samples[v] += 1
        elif isinstance(v, (int, float)):
            self.min = v if self.min is None else min(self.min, v)
            self.max = v if self.max is None else max(self.max, v)
        elif isinstance(v, str) and len(self.samples) < 30:
            self.samples[v[:60]] += 1
        elif isinstance(v, str):
            if v[:60] in self.samples:
                self.samples[v[:60]] += 1

    def describe(self) -> str:
        t = "/".join(self.types)
        if self.min is not None:
            return f"{t:<6} n={self.count:<6} min={fmt(self.min)} max={fmt(self.max)}"
        if self.samples:
            top = ", ".join(f"{k!r}" + (f" x{c}" if c > 1 else "") for k, c in self.samples.most_common(6))
            more = " ..." if len(self.samples) > 6 else ""
            return f"{t:<6} n={self.count:<6} {top}{more}"
        return f"{t:<6} n={self.count}"


def fmt(x) -> str:
    return f"{x:.4g}" if isinstance(x, float) else str(x)


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        if not obj:
            yield prefix + "[]", "<empty list>"
        for item in obj:
            yield from flatten(item, prefix + "[]")
    else:
        yield prefix, obj


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    session = find_session(sys.argv[1] if len(sys.argv) > 1 else None)
    out: list[str] = []
    p = out.append

    fields: dict[str, dict[str, FieldStats]] = defaultdict(lambda: defaultdict(FieldStats))
    ep_count: Counter = Counter()
    ep_first: dict[str, float] = {}
    ep_last: dict[str, float] = {}
    obj_kinds: Counter = Counter()
    obj_per_frame: list[int] = []
    damage_msgs: list[tuple] = []
    event_msgs: list[tuple] = []
    chat: list[tuple] = []
    mission_status: list[tuple] = []
    vehicle_types: Counter = Counter()
    map_fetch: list[tuple] = []

    for rec in read_records(session):
        ep, d, t = rec.get("ep"), rec.get("d"), rec.get("t", 0)
        ep_count[ep] += 1
        ep_first.setdefault(ep, t)
        ep_last[ep] = t

        if ep in ("state", "indicators", "map_info"):
            for k, v in flatten(d):
                if k is not None:
                    fields[ep][k].add(v)
            if ep == "indicators" and isinstance(d, dict) and "type" in d:
                vehicle_types[d["type"]] += 1
        elif ep == "map_obj" and isinstance(d, list):
            obj_per_frame.append(len(d))
            for o in d:
                if isinstance(o, dict):
                    obj_kinds[(o.get("type"), o.get("icon"), o.get("color"))] += 1
                    for k, v in o.items():
                        fields["map_obj[]"][k].add(v)
        elif ep == "mission" and isinstance(d, dict):
            st = d.get("status")
            if not mission_status or mission_status[-1][1] != st:
                mission_status.append((t, st))
            for k, v in flatten(d):
                if k is not None:
                    fields[ep][k].add(v)
        elif ep == "hudmsg" and isinstance(d, dict):
            for m in d.get("damage") or []:
                damage_msgs.append((t, m.get("time"), m.get("msg"), m))
            for m in d.get("events") or []:
                event_msgs.append((t, m))
        elif ep == "map_fetch":
            map_fetch.append((t, d))
        elif ep == "gamechat" and isinstance(d, list):
            for m in d:
                chat.append((t, m.get("sender"), m.get("mode"), m.get("msg"), m.get("enemy")))

    meta_path = session / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    p(f"=== Session {session.name} ===")
    if meta:
        p(f"started {meta.get('started')}  ended {meta.get('ended')}  duration {meta.get('duration_s')}s")
    p(f"map image: {'yes' if (session / 'map.jpg').exists() else 'NO'}")
    for t, d in map_fetch:
        p(f"  map fetch t={t:.1f}s {d}")
    if vehicle_types:
        p("vehicles (indicators.type): " + ", ".join(f"{k} x{v}" for k, v in vehicle_types.most_common()))

    p("\n--- Records per endpoint ---")
    for ep, c in ep_count.most_common():
        span = ep_last[ep] - ep_first[ep]
        rate = c / span if span > 0 else 0
        p(f"{ep:<18} {c:>7} records  ~{rate:5.1f}/s")

    for ep in ("state", "indicators", "map_info", "mission", "map_obj[]"):
        if ep not in fields:
            continue
        p(f"\n--- Fields: {ep} ({len(fields[ep])}) ---")
        for k in sorted(fields[ep]):
            p(f"  {k:<34} {fields[ep][k].describe()}")

    if obj_kinds:
        p("\n--- Map object kinds (type, icon, color) -> sightings ---")
        for (typ, icon, color), c in obj_kinds.most_common():
            p(f"  {str(typ):<14} {str(icon):<18} {str(color):<10} {c}")
        p(f"  objects per frame: min {min(obj_per_frame)} max {max(obj_per_frame)}")

    p(f"\n--- Mission status changes ---")
    for t, st in mission_status:
        p(f"  t={t:8.1f}s  {st}")

    p(f"\n--- Damage / kill feed messages ({len(damage_msgs)}) ---")
    for t, gt, msg, raw in damage_msgs:
        extra = {k: v for k, v in raw.items() if k not in ("msg", "time", "id")}
        p(f"  t={t:8.1f}s game={gt}  {msg}" + (f"   {extra}" if extra else ""))

    if event_msgs:
        p(f"\n--- HUD events ({len(event_msgs)}) ---")
        for t, m in event_msgs:
            p(f"  t={t:8.1f}s  {m}")

    p(f"\n--- Chat ({len(chat)}) ---")
    for t, sender, mode, msg, enemy in chat:
        p(f"  t={t:8.1f}s [{mode}] {sender}{' (enemy)' if enemy else ''}: {msg}")

    report = "\n".join(out)
    print(report)
    (session / "report.txt").write_text(report, encoding="utf-8")
    print(f"\nReport saved to {session / 'report.txt'}")


if __name__ == "__main__":
    main()
