"""Import pipeline: telemetry recordings + replays + battle result texts -> blackbox.db."""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from . import analyze, db, results_text, session, wrpl
from .names import map_name
from .session import ROOT

RESULTS_DIR = ROOT / "results"
DEFAULT_REPLAY_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\War Thunder\Replays")
REPLAY_VERSION = 3
GROUND_MODES = ("fetih", "hakimiyet", "çarpışma", "savaş", "conquest", "domination", "battle")


def _same(a: str | None, b: str) -> bool:
    return bool(a) and a.casefold() == b.casefold()


# ------------------------------------------------------------ recordings
def import_recordings(con, me: str, force: bool, log=print) -> int:
    done = db.imported_versions(con)
    todo = [d for d in session.list_sessions() if force or done.get(d.name) != analyze.ANALYZER_VERSION]
    for i, d in enumerate(todo, 1):
        s = session.load(d)
        m = analyze.analyze(s, me)
        db.save_match(con, m, s.meta.get("ended"))
        log(f"  telemetri [{i}/{len(todo)}] {m.id}")
    return len(todo)


# --------------------------------------------------------------- replays
def battle_kind(battle_class: str | None, mode: str | None = None) -> str:
    """'air_ground_Dom' -> ground (tanks with planes); 'base_dom', 'alt_dom' ... -> air."""
    if battle_class:
        return "ground" if "ground" in battle_class.lower() else "air"
    m = (mode or "").lower()
    return "ground" if any(g in m for g in GROUND_MODES) else "air"


def _lineup(pinfo: dict) -> list[tuple[str, str]]:
    ci = pinfo.get("crafts_info")
    if not isinstance(ci, dict):
        return []
    return [(v["name"], v.get("type")) for k, v in ci.items()
            if k.startswith("array") and isinstance(v, dict) and v.get("name")]


def _craft_info(pinfo: dict) -> tuple[str | None, str | None, int | None]:
    vehicle = vtype = rank = None
    crafts = pinfo.get("crafts")
    if isinstance(crafts, dict) and crafts:
        vehicle = next(iter(crafts.values()))
    ci = pinfo.get("crafts_info")
    if isinstance(ci, dict):
        first = next((v for k, v in ci.items() if k.startswith("array") and isinstance(v, dict)), None)
        if first:
            vehicle = vehicle or first.get("name")
            vtype, rank = first.get("type"), first.get("rank")
    return vehicle, vtype, rank


def import_replay(con, path: Path, me: str) -> str:
    rp = wrpl.load(path)
    h, res = rp.header, rp.results or {}
    players = res.get("player") or []
    if isinstance(players, dict):
        players = [players]
    infos = {}
    ui = (res.get("uiScriptsData") or {}).get("playersInfo") or {}
    for v in ui.values():
        if isinstance(v, dict):
            infos[str(v.get("id"))] = v

    sid = h.session_id
    con.execute("DELETE FROM replay_players WHERE session_id = ?", (sid,))
    con.execute("DELETE FROM replay_kills WHERE session_id = ?", (sid,))

    my_idx = next((i for i, p in enumerate(players) if _same(p.get("name"), me)), None)
    kind = battle_kind(h.battle_class)
    for info in infos.values():
        for name, vtype in _lineup(info):
            con.execute("INSERT OR IGNORE INTO vehicle_types VALUES (?, ?)", (name, vtype))
    vehicles = {}
    for i, p in enumerate(players):
        info = infos.get(str(p.get("userId")), {})
        veh, vtype, _ = _craft_info(info)
        vehicles[i] = veh
        db.insert(con, "replay_players", {
            "session_id": sid, "idx": i, "user_id": p.get("userId"), "name": p.get("name"),
            "clan": p.get("clanTag"), "team": p.get("team"), "vehicle": veh, "vehicle_type": vtype,
            "mrank": info.get("mrank"), "country": info.get("country"), "platform": info.get("platform"),
            "kills": p.get("kills"), "ground_kills": p.get("groundKills"), "ai_kills": p.get("aiKills"),
            "assists": p.get("assists"), "deaths": p.get("deaths"), "score": p.get("score"),
            "missile_evades": p.get("missileEvades"), "is_me": int(i == my_idx),
            "mode_kills": (p.get("kills") or 0) + ((p.get("groundKills") or 0) if kind == "ground" else 0)})

    # killer_pid is the index into the results player list. Entity uids of first spawns are pid + a per-match
    # base; respawned vehicles (ground battles) get new uids, which we learn when that unit kills something.
    offsets = [k.killer_uid - k.killer_pid for k in rp.kills
               if k.killer_uid is not None and k.killer_pid is not None]
    base = statistics.mode(offsets) if offsets else None
    uid_owner, uid_vehicle = {}, {}
    if base is not None:
        uid_owner = {base + i: i for i in range(len(players))}
    for k in rp.kills:
        if k.killer_uid is not None and k.killer_pid is not None and k.killer_pid < len(players):
            uid_owner.setdefault(k.killer_uid, k.killer_pid)
            uid_vehicle.setdefault(k.killer_uid, k.killer_vehicle)
    for k in rp.kills:
        if k.killer_pid is not None and k.killer_pid < len(players):
            vehicles.setdefault(k.killer_pid, k.killer_vehicle)
        v_idx = uid_owner.get(k.victim_uid) if k.victim_uid is not None else None
        ki = k.killer_pid if k.killer_pid is not None and k.killer_pid < len(players) else None
        db.insert(con, "replay_kills", {
            "session_id": sid, "ms": k.ms, "killer_idx": ki,
            "killer_name": players[ki].get("name") if ki is not None else None,
            "killer_vehicle": k.killer_vehicle, "victim_idx": v_idx,
            "victim_name": players[v_idx].get("name") if v_idx is not None else None,
            "victim_vehicle": uid_vehicle.get(k.victim_uid) or (vehicles.get(v_idx) if v_idx is not None else None),
            "weapon": k.weapon, "destroyed_weapon": k.destroyed_weapon,
            "me_killer": int(ki is not None and ki == my_idx),
            "me_victim": int(v_idx is not None and v_idx == my_idx)})

    row = {"file": path.name, "file_size": path.stat().st_size, "session_id": sid, "map_id": h.map_id,
           "battle_class": h.battle_class, "kind": kind, "level_settings": h.level_settings,
           "started": datetime.fromtimestamp(h.start_time).isoformat(timespec="seconds") if h.start_time else None,
           "end_s": (rp.end_ms or 0) / 1000 or res.get("timePlayed"), "n_players": len(players),
           "my_idx": my_idx, "parse_error": None, "version": REPLAY_VERSION}
    if my_idx is not None:
        p = players[my_idx]
        info = infos.get(str(p.get("userId")), {})
        veh, vtype, rank = _craft_info(info)
        my_kill_veh = next((k.killer_vehicle for k in rp.kills if k.killer_pid == my_idx and k.killer_vehicle), None)
        by_score = sorted(range(len(players)), key=lambda i: -(players[i].get("score") or 0))
        team = [i for i in by_score if players[i].get("team") == p.get("team")]
        my_veh = my_kill_veh or veh
        vtype = dict(_lineup(info)).get(my_veh, vtype)
        row.update({"my_team": p.get("team"), "my_vehicle": my_veh, "my_vehicle_type": vtype,
                    "my_rank": rank, "my_kills": p.get("kills"), "my_ground_kills": p.get("groundKills"),
                    "my_ai_kills": p.get("aiKills"), "my_deaths": p.get("deaths"), "my_assists": p.get("assists"),
                    "my_score": p.get("score"), "my_missile_evades": p.get("missileEvades"),
                    "lobby_pos": by_score.index(my_idx) + 1, "team_pos": team.index(my_idx) + 1})
    db.insert(con, "replays", row)
    return sid


def import_replays(con, me: str, replay_dir: Path, force: bool, log=print) -> int:
    if not replay_dir.exists():
        log(f"  replay klasörü bulunamadı: {replay_dir}")
        return 0
    known = {r["file"]: (r["file_size"], r["version"]) for r in con.execute("SELECT file, file_size, version FROM replays")}
    files = sorted(replay_dir.glob("*.wrpl"), key=lambda p: p.stat().st_mtime)
    todo = [f for f in files if force or known.get(f.name) != (f.stat().st_size, REPLAY_VERSION)]
    for i, f in enumerate(todo, 1):
        try:
            with con:
                import_replay(con, f, me)
            log(f"  replay [{i}/{len(todo)}] {f.name}")
        except Exception as e:  # keep going; one broken/old replay should not stop the import
            with con:
                db.insert(con, "replays", {"file": f.name, "file_size": f.stat().st_size,
                                           "parse_error": f"{type(e).__name__}: {e}", "version": REPLAY_VERSION})
            log(f"  replay [{i}/{len(todo)}] {f.name}  HATA: {type(e).__name__}: {e}")
    return len(todo)


# --------------------------------------------------------------- results
def import_results(con, log=print) -> int:
    if not RESULTS_DIR.exists():
        return 0
    known = {r[0] for r in con.execute("SELECT session_id FROM results")}
    n = 0
    for f in sorted(RESULTS_DIR.glob("*.txt")):
        for br in results_text.parse_text(f.read_text(encoding="utf-8")):
            if br.session_id in known:
                continue
            with con:
                db.insert(con, "results", {
                    "session_id": br.session_id, "mode": br.mode, "map_name": br.map_name, "result": br.result,
                    "earned_sl": br.earned_sl, "earned_crp": br.earned_crp, "total_sl": br.total_sl,
                    "total_rp": br.total_rp, "repair_sl": br.repair_sl, "activity": br.activity,
                    "played_s": br.played_s, "research_vehicle": br.research_vehicle,
                    "damaged_vehicles": br.damaged_vehicles,
                    "categories": json.dumps(br.categories, ensure_ascii=False), "raw": br.raw})
                con.executemany(
                    "INSERT INTO result_items VALUES (?,?,?,?,?,?,?,?,?)",
                    [(br.session_id, it.category, it.time_s, it.vehicle, it.weapon, it.target, it.sl, it.rp, it.raw)
                     for it in br.items])
            known.add(br.session_id)
            n += 1
            log(f"  sonuç {br.session_id}  {br.map_name}  {br.result}")
    return n


def add_results_file(path: Path) -> int:
    """Split a text file with one or more copied battle results into results/<session>.txt."""
    RESULTS_DIR.mkdir(exist_ok=True)
    n = 0
    for br in results_text.parse_text(path.read_text(encoding="utf-8")):
        out = RESULTS_DIR / f"{br.session_id}.txt"
        if not out.exists():
            out.write_text(br.raw + "\n", encoding="utf-8")
            n += 1
    return n


# ------------------------------------------------------------ battles
def _ts(s: str | None) -> float | None:
    try:
        return datetime.fromisoformat(s).timestamp() if s else None
    except ValueError:
        return None


def rebuild_battles(con) -> int:
    with con:
        # learn localized map names from result texts
        for r in con.execute("""SELECT rp.map_id, rs.map_name FROM results rs
                                JOIN replays rp ON rp.session_id = rs.session_id WHERE rp.map_id IS NOT NULL"""):
            con.execute("INSERT OR IGNORE INTO map_names VALUES (?, ?, 'result')", (r["map_id"], r["map_name"]))
        names = {r["map_id"]: r["name"] for r in con.execute("SELECT * FROM map_names")}

        # link telemetry recordings to replays by time overlap
        con.execute("UPDATE matches SET session_id = NULL")
        reps = [r for r in con.execute("SELECT session_id, started, end_s FROM replays WHERE session_id IS NOT NULL")]
        for m in con.execute("SELECT id, started, ended, duration_s FROM matches").fetchall():
            m0 = _ts(m["started"])
            m1 = _ts(m["ended"]) or (m0 + (m["duration_s"] or 0) if m0 else None)
            best, best_ov = None, 0.0
            for r in reps:
                r0 = _ts(r["started"])
                if r0 is None or m0 is None:
                    continue
                ov = min(m1, r0 + (r["end_s"] or 0)) - max(m0, r0)
                if ov > best_ov:
                    best, best_ov = r["session_id"], ov
            if best and best_ov > 30:
                con.execute("UPDATE matches SET session_id = ? WHERE id = ?", (best, m["id"]))

        con.execute("DELETE FROM battles")
        rows = {}
        for r in con.execute("SELECT * FROM replays WHERE session_id IS NOT NULL AND my_idx IS NOT NULL "
                             "ORDER BY end_s"):
            rows[r["session_id"]] = {  # longest replay of a session wins (ORDER BY end_s)
                "session_id": r["session_id"], "started": r["started"], "map_id": r["map_id"],
                "map": names.get(r["map_id"]) or map_name(r["map_id"]), "mode": None,
                "battle_class": r["battle_class"], "kind": r["kind"], "vehicle": r["my_vehicle"],
                "vehicle_type": r["my_vehicle_type"], "result": None,
                "kills": (r["my_kills"] or 0) + ((r["my_ground_kills"] or 0) if r["kind"] == "ground" else 0),
                "air_kills": r["my_kills"], "ground_kills": r["my_ground_kills"],
                "deaths": r["my_deaths"], "assists": r["my_assists"], "score": r["my_score"],
                "missile_evades": r["my_missile_evades"], "lobby_pos": r["lobby_pos"], "n_players": r["n_players"],
                "team_pos": r["team_pos"], "end_s": r["end_s"], "has_replay": 1}
        for r in con.execute("SELECT * FROM results"):
            b = rows.setdefault(r["session_id"], {"session_id": r["session_id"], "map": r["map_name"],
                                                  "kind": battle_kind(None, r["mode"]), "has_replay": 0})
            b.update({"mode": r["mode"], "result": r["result"], "played_s": r["played_s"],
                      "activity": r["activity"], "total_sl": r["total_sl"], "total_rp": r["total_rp"],
                      "earned_sl": r["earned_sl"], "repair_sl": r["repair_sl"], "has_result": 1})
            b["map"] = r["map_name"]
        for m in con.execute("SELECT id, session_id FROM matches WHERE session_id IS NOT NULL"):
            if m["session_id"] in rows:
                rows[m["session_id"]].update({"match_id": m["id"], "has_telemetry": 1})
        for b in rows.values():
            b.setdefault("has_result", 0)
            b.setdefault("has_telemetry", 0)
            db.insert(con, "battles", b)
    return len(rows)


def run_import(me: str, replay_dir: Path, force: bool = False, log=print) -> dict:
    con = db.connect()
    out = {"telemetry": import_recordings(con, me, force, log),
           "replays": import_replays(con, me, replay_dir, force, log),
           "results": import_results(con, log)}
    out["battles"] = rebuild_battles(con)
    return out
