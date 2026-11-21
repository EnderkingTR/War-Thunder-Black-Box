"""SQLite storage (blackbox.db in the project root).

The database only holds derived data: it can always be rebuilt from recordings/,
the replay folder and results/. When SCHEMA_VERSION changes it is recreated.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime

from .analyze import ANALYZER_VERSION, Match
from .session import ROOT

DB_PATH = ROOT / "blackbox.db"
SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- 8111 telemetry recordings
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY, started TEXT, ended TEXT, duration_s REAL, vehicle TEXT, result TEXT,
    map_key TEXT, map_size_km REAL, objectives TEXT, lives INTEGER, kills_air INTEGER,
    kills_ground INTEGER, deaths INTEGER, unknown_messages INTEGER, analyzer_version INTEGER,
    imported_at TEXT, session_id TEXT
);
CREATE TABLE IF NOT EXISTS lives (
    match_id TEXT REFERENCES matches(id) ON DELETE CASCADE, idx INTEGER, vehicle TEXT,
    spawn_t REAL, end_t REAL, duration_s REAL, end_reason TEXT, killer TEXT, killer_vehicle TEXT,
    first_hit_t REAL, death_alt_m REAL, death_tas_kmh REAL, death_mach REAL, death_g REAL,
    death_nearest_enemy_km REAL, death_enemies_within_20km INTEGER, kills_air INTEGER,
    kills_ground INTEGER, hits_dealt INTEGER, hits_taken INTEGER, max_g REAL, min_g REAL,
    max_mach REAL, avg_alt_m REAL, avg_tas_kmh REAL, low_alt_share REAL, distance_km REAL,
    def_threat_km REAL, def_aspect REAL, def_notch REAL, def_cold REAL, def_hot REAL, def_low REAL,
    def_max_g REAL, def_turn_deg REAL, def_tas0 REAL, def_tas1 REAL, def_alt0 REAL, def_alt1 REAL,
    energy_m REAL, low_energy_share REAL, ab_share REAL, front_share REAL,
    PRIMARY KEY (match_id, idx)
);
CREATE TABLE IF NOT EXISTS events (
    match_id TEXT REFERENCES matches(id) ON DELETE CASCADE, t REAL, game_time REAL, kind TEXT,
    actor TEXT, actor_squad TEXT, actor_vehicle TEXT, target TEXT, target_squad TEXT,
    target_vehicle TEXT, extra TEXT, me_actor INTEGER, me_target INTEGER, raw TEXT
);
CREATE INDEX IF NOT EXISTS events_match ON events(match_id);

-- replays (.wrpl)
CREATE TABLE IF NOT EXISTS replays (
    file TEXT PRIMARY KEY, file_size INTEGER, session_id TEXT, map_id TEXT, battle_class TEXT,
    level_settings TEXT, started TEXT, end_s REAL, n_players INTEGER, my_idx INTEGER,
    my_team INTEGER, my_vehicle TEXT, my_vehicle_type TEXT, my_rank INTEGER,
    my_kills INTEGER, my_ground_kills INTEGER, my_ai_kills INTEGER, my_deaths INTEGER,
    my_assists INTEGER, my_score INTEGER, my_missile_evades INTEGER,
    lobby_pos INTEGER, team_pos INTEGER, parse_error TEXT, version INTEGER
);
CREATE INDEX IF NOT EXISTS replays_session ON replays(session_id);
CREATE TABLE IF NOT EXISTS replay_players (
    session_id TEXT, idx INTEGER, user_id TEXT, name TEXT, clan TEXT, team INTEGER,
    vehicle TEXT, vehicle_type TEXT, mrank INTEGER, country TEXT, platform TEXT,
    kills INTEGER, ground_kills INTEGER, ai_kills INTEGER, assists INTEGER, deaths INTEGER,
    score INTEGER, missile_evades INTEGER, is_me INTEGER, PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS replay_kills (
    session_id TEXT, ms INTEGER, killer_idx INTEGER, killer_name TEXT, killer_vehicle TEXT,
    victim_idx INTEGER, victim_name TEXT, victim_vehicle TEXT, weapon TEXT, destroyed_weapon TEXT,
    me_killer INTEGER, me_victim INTEGER
);
CREATE INDEX IF NOT EXISTS replay_kills_session ON replay_kills(session_id);

-- copied battle result texts
CREATE TABLE IF NOT EXISTS results (
    session_id TEXT PRIMARY KEY, mode TEXT, map_name TEXT, result TEXT, earned_sl INTEGER,
    earned_crp INTEGER, total_sl INTEGER, total_rp INTEGER, repair_sl INTEGER, activity INTEGER,
    played_s INTEGER, research_vehicle TEXT, damaged_vehicles TEXT, categories TEXT, raw TEXT
);
CREATE TABLE IF NOT EXISTS result_items (
    session_id TEXT, category TEXT, time_s INTEGER, vehicle TEXT, weapon TEXT, target TEXT,
    sl INTEGER, rp INTEGER, raw TEXT
);

-- map display names (learned from result texts or set by hand)
CREATE TABLE IF NOT EXISTS map_names (map_id TEXT PRIMARY KEY, name TEXT, source TEXT);

-- one row per battle, rebuilt after every import from the tables above
CREATE TABLE IF NOT EXISTS battles (
    session_id TEXT PRIMARY KEY, started TEXT, map_id TEXT, map TEXT, mode TEXT, battle_class TEXT,
    vehicle TEXT, vehicle_type TEXT, result TEXT, kills INTEGER, ground_kills INTEGER,
    deaths INTEGER, assists INTEGER, score INTEGER, missile_evades INTEGER, lobby_pos INTEGER,
    n_players INTEGER, team_pos INTEGER, end_s REAL, played_s INTEGER, activity INTEGER,
    total_sl INTEGER, total_rp INTEGER, earned_sl INTEGER, repair_sl INTEGER, match_id TEXT,
    has_replay INTEGER, has_result INTEGER, has_telemetry INTEGER
);
"""

LIFE_COLS = ["idx", "vehicle", "spawn_t", "end_t", "duration_s", "end_reason", "killer", "killer_vehicle",
             "first_hit_t", "death_alt_m", "death_tas_kmh", "death_mach", "death_g",
             "death_nearest_enemy_km", "death_enemies_within_20km", "kills_air", "kills_ground",
             "hits_dealt", "hits_taken", "max_g", "min_g", "max_mach", "avg_alt_m", "avg_tas_kmh",
             "low_alt_share", "distance_km",
             "def_threat_km", "def_aspect", "def_notch", "def_cold", "def_hot", "def_low", "def_max_g",
             "def_turn_deg", "def_tas0", "def_tas1", "def_alt0", "def_alt1",
             "energy_m", "low_energy_share", "ab_share", "front_share"]
EVENT_COLS = ["t", "game_time", "kind", "actor", "actor_squad", "actor_vehicle", "target", "target_squad",
              "target_vehicle", "extra", "me_actor", "me_target", "raw"]


def connect() -> sqlite3.Connection:
    con = _open()
    try:
        ver = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    except sqlite3.OperationalError:
        ver = None
    if ver is None or int(ver[0]) != SCHEMA_VERSION:
        # derived data only (rebuilt by import): drop everything in place, so an open web server
        # holding the file does not block the upgrade
        con.execute("PRAGMA foreign_keys = OFF")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            con.execute(f'DROP TABLE IF EXISTS "{t}"')
        con.commit()
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        con.commit()
    return con


def _open() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def insert(con, table: str, row: dict) -> None:
    cols = list(row)
    con.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols])


def imported_versions(con) -> dict[str, int]:
    return {r["id"]: r["analyzer_version"] for r in con.execute("SELECT id, analyzer_version FROM matches")}


def save_match(con, m: Match, ended: str | None) -> None:
    with con:
        con.execute("DELETE FROM matches WHERE id = ?", (m.id,))
        insert(con, "matches", {
            "id": m.id, "started": m.started, "ended": ended, "duration_s": m.duration_s,
            "vehicle": m.vehicle, "result": m.result, "map_key": m.map_key, "map_size_km": m.map_size_km,
            "objectives": json.dumps(m.objectives, ensure_ascii=False), "lives": len(m.lives),
            "kills_air": sum(l.kills_air for l in m.lives), "kills_ground": sum(l.kills_ground for l in m.lives),
            "deaths": sum(1 for l in m.lives if l.end_reason in ("shot_down", "crashed")),
            "unknown_messages": len(m.unknown_messages), "analyzer_version": ANALYZER_VERSION,
            "imported_at": datetime.now().isoformat(timespec="seconds"), "session_id": None})
        for life in m.lives:
            d = asdict(life)
            d["duration_s"] = life.duration_s
            insert(con, "lives", {"match_id": m.id, **{c: d[c] for c in LIFE_COLS}})
        con.executemany(
            f"INSERT INTO events (match_id, {', '.join(EVENT_COLS)}) VALUES (?{', ?' * len(EVENT_COLS)})",
            [[m.id] + [e.get(c) for c in EVENT_COLS] for e in m.events])
