"""SQLite storage for analyzed matches (blackbox.db in the project root)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime

from .analyze import ANALYZER_VERSION, Match
from .session import ROOT

DB_PATH = ROOT / "blackbox.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    started TEXT,
    duration_s REAL,
    vehicle TEXT,
    result TEXT,
    map_key TEXT,
    map_size_km REAL,
    objectives TEXT,
    lives INTEGER,
    kills_air INTEGER,
    kills_ground INTEGER,
    deaths INTEGER,
    unknown_messages INTEGER,
    analyzer_version INTEGER,
    imported_at TEXT
);
CREATE TABLE IF NOT EXISTS lives (
    match_id TEXT REFERENCES matches(id) ON DELETE CASCADE,
    idx INTEGER,
    vehicle TEXT,
    spawn_t REAL, end_t REAL, duration_s REAL,
    end_reason TEXT,
    killer TEXT, killer_vehicle TEXT,
    first_hit_t REAL,
    death_alt_m REAL, death_tas_kmh REAL, death_mach REAL, death_g REAL,
    death_nearest_enemy_km REAL, death_enemies_within_20km INTEGER,
    kills_air INTEGER, kills_ground INTEGER, hits_dealt INTEGER, hits_taken INTEGER,
    max_g REAL, min_g REAL, max_mach REAL, avg_alt_m REAL, avg_tas_kmh REAL,
    low_alt_share REAL, distance_km REAL,
    PRIMARY KEY (match_id, idx)
);
CREATE TABLE IF NOT EXISTS events (
    match_id TEXT REFERENCES matches(id) ON DELETE CASCADE,
    t REAL, game_time REAL, kind TEXT,
    actor TEXT, actor_squad TEXT, actor_vehicle TEXT,
    target TEXT, target_squad TEXT, target_vehicle TEXT,
    extra TEXT, me_actor INTEGER, me_target INTEGER, raw TEXT
);
CREATE INDEX IF NOT EXISTS events_match ON events(match_id);
CREATE TABLE IF NOT EXISTS maps (
    map_key TEXT PRIMARY KEY,
    name TEXT
);
"""

LIFE_COLS = ["idx", "vehicle", "spawn_t", "end_t", "duration_s", "end_reason", "killer", "killer_vehicle",
             "first_hit_t", "death_alt_m", "death_tas_kmh", "death_mach", "death_g",
             "death_nearest_enemy_km", "death_enemies_within_20km", "kills_air", "kills_ground",
             "hits_dealt", "hits_taken", "max_g", "min_g", "max_mach", "avg_alt_m", "avg_tas_kmh",
             "low_alt_share", "distance_km"]
EVENT_COLS = ["t", "game_time", "kind", "actor", "actor_squad", "actor_vehicle", "target", "target_squad",
              "target_vehicle", "extra", "me_actor", "me_target", "raw"]


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def imported_versions(con) -> dict[str, int]:
    return {r["id"]: r["analyzer_version"] for r in con.execute("SELECT id, analyzer_version FROM matches")}


def save_match(con, m: Match) -> None:
    with con:
        con.execute("DELETE FROM matches WHERE id = ?", (m.id,))
        con.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (m.id, m.started, m.duration_s, m.vehicle, m.result, m.map_key, m.map_size_km,
             json.dumps(m.objectives, ensure_ascii=False), len(m.lives),
             sum(l.kills_air for l in m.lives), sum(l.kills_ground for l in m.lives),
             sum(1 for l in m.lives if l.end_reason in ("shot_down", "crashed")),
             len(m.unknown_messages), ANALYZER_VERSION, datetime.now().isoformat(timespec="seconds")))
        for life in m.lives:
            d = asdict(life)
            d["duration_s"] = life.duration_s
            con.execute(f"INSERT INTO lives (match_id, {', '.join(LIFE_COLS)}) VALUES (?{', ?' * len(LIFE_COLS)})",
                        [m.id] + [d[c] for c in LIFE_COLS])
        con.executemany(
            f"INSERT INTO events (match_id, {', '.join(EVENT_COLS)}) VALUES (?{', ?' * len(EVENT_COLS)})",
            [[m.id] + [e.get(c) for c in EVENT_COLS] for e in m.events])
        if m.map_key:
            con.execute("INSERT OR IGNORE INTO maps (map_key, name) VALUES (?, NULL)", (m.map_key,))
