"""Loading recorded sessions (written by recorder/record.py)."""

from __future__ import annotations

import gzip
import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "recordings"


def list_sessions() -> list[Path]:
    if not RECORDINGS_DIR.exists():
        return []
    return sorted(d for d in RECORDINGS_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("_")
                  and ((d / "events.jsonl.gz").exists() or (d / "events.jsonl").exists()))


def iter_records(session_dir: Path):
    gz, plain = session_dir / "events.jsonl.gz", session_dir / "events.jsonl"
    f = gzip.open(gz, "rt", encoding="utf-8") if gz.exists() else open(plain, encoding="utf-8")
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # cut last line if recorder was killed


class Series:
    """Time-ordered list of (t, payload) with nearest-before lookup."""

    def __init__(self) -> None:
        self.t: list[float] = []
        self.d: list = []

    def add(self, t: float, d) -> None:
        self.t.append(t)
        self.d.append(d)

    def at(self, t: float):
        """Last payload at or before t (None if nothing yet)."""
        i = bisect_right(self.t, t) - 1
        return self.d[i] if i >= 0 else None

    def between(self, t0: float, t1: float):
        i0, i1 = bisect_right(self.t, t0), bisect_right(self.t, t1)
        return zip(self.t[i0:i1], self.d[i0:i1])

    def __len__(self) -> int:
        return len(self.t)


@dataclass
class Session:
    dir: Path
    meta: dict
    state: Series = field(default_factory=Series)
    indicators: Series = field(default_factory=Series)
    map_obj: Series = field(default_factory=Series)
    map_info: Series = field(default_factory=Series)
    mission: Series = field(default_factory=Series)
    damage: list = field(default_factory=list)   # (t, msg dict)
    chat: list = field(default_factory=list)     # (t, msg dict)

    @property
    def id(self) -> str:
        return self.dir.name

    def map_jpg_hash(self) -> str | None:
        p = self.dir / "map.jpg"
        if p.exists() and p.stat().st_size > 1000:
            return hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        return None


def load(session_dir: Path) -> Session:
    meta_p = session_dir / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    s = Session(session_dir, meta)
    series = {"state": s.state, "indicators": s.indicators, "map_obj": s.map_obj,
              "map_info": s.map_info, "mission": s.mission}
    for rec in iter_records(session_dir):
        ep, t, d = rec.get("ep"), rec.get("t", 0.0), rec.get("d")
        if ep in series:
            series[ep].add(t, d)
        elif ep == "hudmsg" and isinstance(d, dict):
            s.damage.extend((t, m) for m in d.get("damage") or [])
        elif ep == "gamechat" and isinstance(d, list):
            s.chat.extend((t, m) for m in d)
    return s
