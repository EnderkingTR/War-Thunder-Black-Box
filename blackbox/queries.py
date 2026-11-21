"""Read-only queries over blackbox.db, returning plain dicts/lists (used by the web API)."""

from __future__ import annotations

import json

from . import names, session

AIR_TYPES = ("fighter", "assault", "bomber", "attacker")


def build_where(f: dict, alias: str = "b") -> tuple[str, list]:
    conds, params = [], []
    kind = f.get("type") or "air"
    ph = ", ".join("?" * len(AIR_TYPES))
    if kind == "air":
        conds.append(f"({alias}.vehicle_type IS NULL OR {alias}.vehicle_type IN ({ph}))")
        params += AIR_TYPES
    elif kind == "ground":
        conds.append(f"{alias}.vehicle_type NOT IN ({ph})")
        params += AIR_TYPES
    if f.get("vehicle"):
        conds.append(f"{alias}.vehicle = ?")
        params.append(f["vehicle"])
    if f.get("map"):
        conds.append(f"{alias}.map = ?")
        params.append(f["map"])
    if f.get("since"):
        conds.append(f"{alias}.started >= ?")
        params.append(f["since"])
    if f.get("last"):
        conds.append(f"{alias}.session_id IN (SELECT session_id FROM battles ORDER BY started DESC LIMIT ?)")
        params.append(int(f["last"]))
    return (" WHERE " + " AND ".join(conds)) if conds else " WHERE 1=1", params


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _bucket_minutes(ms_list):
    edges = [(0, 2, "0–2"), (2, 3, "2–3"), (3, 4, "3–4"), (4, 5, "4–5"), (5, 7, "5–7"), (7, 10, "7–10"),
             (10, 999, "10+")]
    out = [{"label": lab, "n": 0} for _, _, lab in edges]
    for ms in ms_list:
        m = ms / 60000
        for i, (a, b, _) in enumerate(edges):
            if a <= m < b:
                out[i]["n"] += 1
                break
    return out


def _weapon_counts(rows) -> list[dict]:
    agg: dict[str, int] = {}
    for r in rows:
        key = names.weapon(r["weapon"]) if r["weapon"] else "Silahsız (kaza / manevra)"
        agg[key] = agg.get(key, 0) + r["n"]
    return [{"name": k, "n": v} for k, v in sorted(agg.items(), key=lambda x: -x[1])]


def _vehicle_counts(rows, key="v", unknown="Bilinmiyor") -> list[dict]:
    return [{"name": names.vehicle(r[key]) if r[key] else unknown, "id": r[key], "n": r["n"]} for r in rows]


# ------------------------------------------------------------------ filters
def filter_options(con, f: dict) -> dict:
    kind_only = {"type": f.get("type") or "air"}
    w, p = build_where(kind_only)
    vehicles = [r[0] for r in con.execute(f"SELECT vehicle FROM battles b{w} AND vehicle IS NOT NULL "
                                          f"GROUP BY vehicle ORDER BY COUNT(*) DESC", p)]
    maps = [r[0] for r in con.execute(f"SELECT map FROM battles b{w} AND map IS NOT NULL GROUP BY map "
                                      f"ORDER BY map", p)]
    rng = con.execute(f"SELECT MIN(started), MAX(started), COUNT(*) FROM battles b{w}", p).fetchone()
    return {"vehicles": [{"id": v, "name": names.vehicle(v)} for v in vehicles], "maps": maps,
            "first": rng[0], "last": rng[1], "count": rng[2]}


# ------------------------------------------------------------------ summary
def summary(con, f: dict) -> dict:
    w, p = build_where(f)
    t = dict(con.execute(f"""SELECT COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(ground_kills) gk, SUM(deaths) d, SUM(assists) a, AVG(score) score, SUM(missile_evades) ev,
        AVG(1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0)) lobby, SUM(has_result) nres,
        AVG(total_sl) sl, AVG(total_rp) rp, SUM(played_s) played FROM battles b{w}""", p).fetchone())

    bw = w + " AND b.has_replay = 1"
    lob = dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw})
        SELECT AVG(CASE WHEN is_me=1 THEN score END) my_score, AVG(CASE WHEN is_me=0 THEN score END) l_score,
          SUM(CASE WHEN is_me=1 THEN kills END) my_k, SUM(CASE WHEN is_me=1 THEN deaths END) my_d,
          SUM(CASE WHEN is_me=0 THEN kills END) l_k, SUM(CASE WHEN is_me=0 THEN deaths END) l_d,
          AVG(CASE WHEN is_me=1 THEN missile_evades END) my_ev, AVG(CASE WHEN is_me=0 THEN missile_evades END) l_ev,
          AVG(CASE WHEN is_me=1 THEN assists END) my_a, AVG(CASE WHEN is_me=0 THEN assists END) l_a
        FROM replay_players rp JOIN bs USING (session_id)""", p).fetchone())
    top = dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw}),
        r AS (SELECT rp.*, ROW_NUMBER() OVER (PARTITION BY rp.session_id ORDER BY rp.score DESC) rn
              FROM replay_players rp JOIN bs USING (session_id))
        SELECT AVG(score) score, SUM(kills) k, SUM(deaths) d, AVG(missile_evades) ev, AVG(assists) a
        FROM r WHERE rn <= 3""", p).fetchone())

    K = f"FROM replay_kills k JOIN battles b ON b.session_id = k.session_id{w}"
    death_ms = [r[0] for r in con.execute(f"SELECT k.ms {K} AND k.me_victim = 1", p)]
    death_weapons = _weapon_counts(con.execute(f"SELECT weapon, COUNT(*) n {K} AND k.me_victim = 1 GROUP BY weapon", p))
    kill_weapons = _weapon_counts(con.execute(
        f"SELECT weapon, COUNT(*) n {K} AND k.me_killer = 1 AND k.destroyed_weapon IS NULL GROUP BY weapon", p))
    recent = _rows(con.execute(f"SELECT * FROM battles b{w} ORDER BY started DESC LIMIT 10", p))
    form = _rows(con.execute(f"""SELECT session_id, started, result, kills, deaths, score,
        1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0) lobby FROM battles b{w} ORDER BY started DESC LIMIT 40""", p))
    tel = dict(con.execute(f"""SELECT COUNT(*) n, AVG(l.death_alt_m) death_alt, AVG(l.death_tas_kmh) death_tas,
        AVG(l.death_nearest_enemy_km) death_enemy_km, AVG(l.avg_alt_m) alt, AVG(l.avg_tas_kmh) tas,
        AVG(l.max_g) max_g, AVG(l.low_alt_share) low FROM lives l JOIN battles b ON b.match_id = l.match_id{w}""",
                           p).fetchone())
    return {"totals": t, "lobby": {"me": {"score": lob["my_score"], "k": lob["my_k"], "d": lob["my_d"],
                                          "ev": lob["my_ev"], "a": lob["my_a"]},
                                   "lobby": {"score": lob["l_score"], "k": lob["l_k"], "d": lob["l_d"],
                                             "ev": lob["l_ev"], "a": lob["l_a"]},
                                   "top3": {"score": top["score"], "k": top["k"], "d": top["d"], "ev": top["ev"],
                                            "a": top["a"]}},
            "death_timing": _bucket_minutes(death_ms), "death_weapons": death_weapons[:8],
            "kill_weapons": kill_weapons[:8], "recent": _decorate(recent), "form": list(reversed(form)),
            "telemetry": tel}


def _decorate(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["vehicle_name"] = names.vehicle(r.get("vehicle"))
    return rows


# ------------------------------------------------------------------ lists
def battles(con, f: dict) -> list[dict]:
    w, p = build_where(f)
    return _decorate(_rows(con.execute(f"SELECT * FROM battles b{w} ORDER BY started DESC", p)))


def battle(con, sid: str) -> dict | None:
    b = con.execute("SELECT * FROM battles WHERE session_id = ?", (sid,)).fetchone()
    if not b:
        return None
    b = _decorate([dict(b)])[0]
    kills = _rows(con.execute("SELECT * FROM replay_kills WHERE session_id = ? ORDER BY ms", (sid,)))
    for k in kills:
        k["weapon_name"] = names.weapon(k["weapon"]) if k["weapon"] else None
        k["destroyed_name"] = names.weapon(k["destroyed_weapon"]) if k["destroyed_weapon"] else None
        k["killer_vehicle_name"] = names.vehicle(k["killer_vehicle"])
        k["victim_vehicle_name"] = names.vehicle(k["victim_vehicle"])
    players = _rows(con.execute("SELECT * FROM replay_players WHERE session_id = ? ORDER BY team, score DESC",
                                (sid,)))
    for pl in players:
        pl["vehicle_name"] = names.vehicle(pl["vehicle"])
    res = con.execute("SELECT * FROM results WHERE session_id = ?", (sid,)).fetchone()
    items = _rows(con.execute("SELECT * FROM result_items WHERE session_id = ?", (sid,)))
    lives = _rows(con.execute("SELECT * FROM lives WHERE match_id = ? ORDER BY idx", (b["match_id"],))) \
        if b.get("match_id") else []
    result = dict(res) if res else None
    if result:
        result["categories"] = json.loads(result["categories"] or "{}")
        result.pop("raw", None)
    return {"battle": b, "kills": kills, "players": players, "result": result, "result_items": items,
            "lives": lives}


def telemetry(con, match_id: str) -> dict | None:
    d = session.RECORDINGS_DIR / match_id
    if not d.is_dir() or "/" in match_id or "\\" in match_id or ".." in match_id:
        return None
    s = session.load(d)
    series, last = [], -1.0
    for t, st in zip(s.state.t, s.state.d):
        if t - last < 0.5 or not (isinstance(st, dict) and st.get("valid")):
            continue
        last = t
        series.append([round(t, 1), st.get("H, m"), st.get("TAS, km/h"), st.get("M"), st.get("Ny")])
    track, last = [], -1.0
    for t, frame in zip(s.map_obj.t, s.map_obj.d):
        if t - last < 1.0 or not isinstance(frame, list):
            continue
        for o in frame:
            if isinstance(o, dict) and o.get("icon") == "Player" and "x" in o:
                track.append([round(t, 1), round(o["x"], 4), round(o["y"], 4)])
                last = t
                break
    events = _rows(con.execute("""SELECT t, kind, actor, actor_vehicle, target, target_vehicle, me_actor, me_target
        FROM events WHERE match_id = ? AND (me_actor = 1 OR me_target = 1) ORDER BY t""", (match_id,)))
    lives = _rows(con.execute("SELECT * FROM lives WHERE match_id = ? ORDER BY idx", (match_id,)))
    return {"series": series, "track": track, "events": events, "lives": lives}


def weapons(con, f: dict) -> dict:
    w, p = build_where(f)
    K = f"FROM replay_kills k JOIN battles b ON b.session_id = k.session_id{w}"
    return {
        "kills": _weapon_counts(con.execute(
            f"SELECT weapon, COUNT(*) n {K} AND k.me_killer = 1 AND k.destroyed_weapon IS NULL GROUP BY weapon", p)),
        "deaths": _weapon_counts(con.execute(f"SELECT weapon, COUNT(*) n {K} AND k.me_victim = 1 GROUP BY weapon", p)),
        "killers": _vehicle_counts(con.execute(f"""SELECT killer_vehicle v, COUNT(*) n {K} AND k.me_victim = 1
            GROUP BY v ORDER BY n DESC LIMIT 15""", p), unknown="Kaza / bilinmiyor"),
        "victims": _vehicle_counts(con.execute(f"""SELECT victim_vehicle v, COUNT(*) n {K} AND k.me_killer = 1
            AND k.destroyed_weapon IS NULL GROUP BY v ORDER BY n DESC LIMIT 15""", p), unknown="AI hedef / bilinmiyor"),
        "intercepts": _weapon_counts(con.execute(f"""SELECT destroyed_weapon weapon, COUNT(*) n {K}
            AND k.me_killer = 1 AND k.destroyed_weapon IS NOT NULL GROUP BY destroyed_weapon""", p)),
    }


def maps(con, f: dict) -> list[dict]:
    w, p = build_where(f)
    return _rows(con.execute(f"""SELECT map, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(deaths) d, AVG(score) score, AVG(1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0)) lobby,
        SUM(missile_evades) ev, AVG(total_sl) sl, AVG(total_rp) rp
        FROM battles b{w} GROUP BY map ORDER BY n DESC""", p))


def vehicles(con, f: dict) -> list[dict]:
    w, p = build_where(f)
    rows = _rows(con.execute(f"""SELECT vehicle, vehicle_type, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l,
        SUM(kills) k, SUM(deaths) d, AVG(score) score, AVG(1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0)) lobby,
        SUM(missile_evades) ev, AVG(total_sl) sl, AVG(total_rp) rp, SUM(has_result) nres
        FROM battles b{w} GROUP BY vehicle ORDER BY n DESC""", p))
    return _decorate(rows)


def grind(con, f: dict) -> dict:
    w, p = build_where(f)
    w += " AND b.has_result = 1"
    rows = _decorate(_rows(con.execute(f"""SELECT session_id, started, map, vehicle, result, total_sl, total_rp,
        earned_sl, repair_sl, played_s, activity FROM battles b{w} ORDER BY started""", p)))
    agg = dict(con.execute(f"""SELECT COUNT(*) n, AVG(total_sl) sl, AVG(total_rp) rp, AVG(repair_sl) repair,
        SUM(total_sl) sum_sl, SUM(total_rp) sum_rp, SUM(played_s) played, AVG(activity) activity,
        AVG(CASE WHEN result='win' THEN total_sl END) win_sl, AVG(CASE WHEN result='loss' THEN total_sl END) loss_sl,
        AVG(CASE WHEN result='win' THEN total_rp END) win_rp, AVG(CASE WHEN result='loss' THEN total_rp END) loss_rp
        FROM battles b{w}""", p).fetchone())
    by_vehicle = _decorate(_rows(con.execute(f"""SELECT vehicle, COUNT(*) n, AVG(total_sl) sl, AVG(total_rp) rp,
        AVG(repair_sl) repair, SUM(played_s) played, SUM(total_sl) sum_sl, SUM(total_rp) sum_rp
        FROM battles b{w} GROUP BY vehicle ORDER BY n DESC""", p)))
    return {"battles": rows, "totals": agg, "by_vehicle": by_vehicle}
