"""Read-only queries over blackbox.db, returning plain dicts/lists (used by the web API)."""

from __future__ import annotations

import json

from . import names, session, skills



def build_where(f: dict, alias: str = "b") -> tuple[str, list]:
    conds, params = [], []
    kind = f.get("type") or "air"
    if kind in ("air", "ground"):
        conds.append(f"{alias}.kind = ?")
        params.append(kind)
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
        AVG(total_sl) sl, AVG(total_rp) rp, SUM(played_s) played,
        SUM(bases_est) bases, COUNT(bases_est) nbases, SUM(bases_est > 0) nbase_battles,
        SUM(CASE WHEN bases_est IS NOT NULL THEN air_kills END) bk, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_rp END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) rp_min, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_sl END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) sl_min FROM battles b{w}""", p).fetchone())

    bw = w + " AND b.has_replay = 1"
    lob = dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw})
        SELECT AVG(CASE WHEN is_me=1 THEN score END) my_score, AVG(CASE WHEN is_me=0 THEN score END) l_score,
          SUM(CASE WHEN is_me=1 THEN mode_kills END) my_k, SUM(CASE WHEN is_me=1 THEN deaths END) my_d,
          SUM(CASE WHEN is_me=0 THEN mode_kills END) l_k, SUM(CASE WHEN is_me=0 THEN deaths END) l_d,
          AVG(CASE WHEN is_me=1 THEN missile_evades END) my_ev, AVG(CASE WHEN is_me=0 THEN missile_evades END) l_ev,
          AVG(CASE WHEN is_me=1 THEN assists END) my_a, AVG(CASE WHEN is_me=0 THEN assists END) l_a,
          AVG(CASE WHEN is_me=1 THEN mode_kills END) my_kpm, AVG(CASE WHEN is_me=0 THEN mode_kills END) l_kpm,
          1.0 * SUM(is_me = 0) / NULLIF(COUNT(DISTINCT session_id), 0) others
        FROM replay_players rp JOIN bs USING (session_id)""", p).fetchone())
    top = dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw}),
        r AS (SELECT rp.*, ROW_NUMBER() OVER (PARTITION BY rp.session_id ORDER BY rp.score DESC) rn
              FROM replay_players rp JOIN bs USING (session_id))
        SELECT AVG(score) score, SUM(mode_kills) k, SUM(deaths) d, AVG(missile_evades) ev, AVG(assists) a,
          AVG(mode_kills) kpm FROM r WHERE rn <= 3""", p).fetchone())

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
    return {"totals": t, "kind": f.get("type") or "air",
            "lobby": {"me": {"score": lob["my_score"], "k": lob["my_k"], "d": lob["my_d"],
                             "ev": lob["my_ev"], "a": lob["my_a"], "kpm": lob["my_kpm"]},
                      "lobby": {"score": lob["l_score"], "k": lob["l_k"], "d": lob["l_d"],
                                "ev": lob["l_ev"], "a": lob["l_a"], "kpm": lob["l_kpm"]},
                      "top3": {"score": top["score"], "k": top["k"], "d": top["d"], "ev": top["ev"],
                               "a": top["a"], "kpm": top["kpm"]},
                      "others": lob["others"]},
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
    return _rows(con.execute(f"""
        WITH fb AS (SELECT session_id, MIN(time_s) t FROM result_items WHERE category = 'Yok edilen üsler'
                    GROUP BY session_id),
             fd AS (SELECT session_id, MIN(ms) / 1000.0 t FROM replay_kills WHERE me_victim = 1 GROUP BY session_id)
        SELECT map, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(deaths) d, AVG(score) score, AVG(1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0)) lobby,
        SUM(missile_evades) ev, AVG(total_sl) sl, AVG(total_rp) rp, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_rp END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) rp_min, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_sl END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) sl_min,
        SUM(bases_est) bases, COUNT(bases_est) nb, SUM(bases_est > 0) base_matches,
        AVG(fb.t) first_base_s, AVG(fd.t) first_death_s, AVG(capture_zone) cz
        FROM battles b LEFT JOIN fb USING (session_id) LEFT JOIN fd USING (session_id){w}
        GROUP BY map ORDER BY n DESC""", p))


def vehicles(con, f: dict) -> list[dict]:
    w, p = build_where(f)
    rows = _rows(con.execute(f"""SELECT vehicle, vehicle_type, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l,
        SUM(kills) k, SUM(deaths) d, AVG(score) score, AVG(1.0 * (lobby_pos - 1) / NULLIF(n_players - 1, 0)) lobby,
        SUM(missile_evades) ev, AVG(total_sl) sl, AVG(total_rp) rp, SUM(has_result) nres, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_rp END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) rp_min, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_sl END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) sl_min,
        SUM(bases_est) bases, COUNT(bases_est) nb, AVG(capture_zone) cz, AVG(fd.t) first_death_s,
        SUM(fd.t IS NULL AND b.has_replay = 1) survived
        FROM battles b LEFT JOIN (SELECT session_id, MIN(ms) / 1000.0 t FROM replay_kills WHERE me_victim = 1
                                  GROUP BY session_id) fd USING (session_id){w}
        GROUP BY vehicle ORDER BY n DESC""", p))
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


def trend(con, f: dict) -> dict:
    """Rolling averages over the last `win` battles, oldest first: is it getting better?"""
    w, p = build_where(f)
    rows = _rows(con.execute(f"""SELECT session_id, started, kills, deaths, score, bases_est, total_rp, played_s,
        has_result, has_replay, capture_zone FROM battles b{w} ORDER BY started""", p))
    deaths: dict = {}
    for r in con.execute(f"""SELECT k.session_id, k.weapon FROM replay_kills k
            JOIN battles b ON b.session_id = k.session_id{w} AND k.me_victim = 1""", p):
        deaths.setdefault(r[0], []).append(skills.weapon_class(r[1]))
    n = len(rows)
    win = max(3, min(10, n // 3))
    pts = []
    for i in range(win - 1, n):
        seg = rows[i - win + 1:i + 1]
        k = sum(r["kills"] or 0 for r in seg)
        d = sum(r["deaths"] or 0 for r in seg)
        bs = [r["bases_est"] for r in seg if r["bases_est"] is not None]
        res = [r for r in seg if r["has_result"] and r["played_s"]]
        dw = [c for r in seg for c in deaths.get(r["session_id"], [])]
        cz = [r["capture_zone"] for r in seg if r["capture_zone"] is not None]
        pts.append({"started": seg[-1]["started"], "kd": k / d if d else None, "kpm": k / len(seg),
                    "score": _avg([r["score"] for r in seg]),
                    "bases": sum(bs) / len(bs) if bs else None,
                    "rp_min": 60 * sum(r["total_rp"] or 0 for r in res) / sum(r["played_s"] for r in res) if res else None,
                    "ir": dw.count("ir") / len(dw) if dw else None,
                    "cz": sum(cz) / len(cz) if cz else None})
    return {"window": win, "n": n, "points": pts}


def ground_vehicles(con, f: dict) -> list[dict]:
    """Kills and deaths per own vehicle in ground battles (several vehicles per battle)."""
    w, p = build_where(f)
    rows = _rows(con.execute(f"""SELECT v, SUM(k) k, SUM(d) d, COUNT(DISTINCT sid) n FROM (
          SELECT k.killer_vehicle v, 1 k, 0 d, k.session_id sid FROM replay_kills k
            JOIN battles b ON b.session_id = k.session_id{w} AND k.me_killer = 1 AND k.destroyed_weapon IS NULL
          UNION ALL
          SELECT k.victim_vehicle v, 0, 1, k.session_id FROM replay_kills k
            JOIN battles b ON b.session_id = k.session_id{w} AND k.me_victim = 1)
        WHERE v IS NOT NULL GROUP BY v ORDER BY k + d DESC""", p + p))
    types = dict(con.execute("SELECT vehicle, type FROM vehicle_types").fetchall())
    for r in rows:
        r["vehicle"], r["vehicle_name"], r["type"] = r["v"], names.vehicle(r["v"]), types.get(r["v"])
    return rows


def missing_results(con, f: dict) -> list[dict]:
    w, p = build_where(f)
    return _decorate(_rows(con.execute(f"""SELECT session_id, started, map, vehicle, kills, deaths, score, end_s
        FROM battles b{w} AND b.has_result = 0 AND b.has_replay = 1 ORDER BY started DESC""", p)))


# ------------------------------------------------------------------ skills
def _class_counts(weapons: list) -> dict:
    out = {c: 0 for c in skills.CLASSES}
    for wpn in weapons:
        out[skills.weapon_class(wpn)] += 1
    return out


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _num(x):
    return f"{x:,.0f}".replace(",", ".")


def _pct(x):
    return f"%{round(100 * x)}"


def skill_report(con, f: dict) -> dict:
    w, p = build_where(f)
    K = f"FROM replay_kills k JOIN battles b ON b.session_id = k.session_id{w}"
    J = K.replace(" JOIN battles b", " LEFT JOIN vehicle_types kt ON kt.vehicle = k.killer_vehicle"
                                    " LEFT JOIN vehicle_types vt ON vt.vehicle = k.victim_vehicle JOIN battles b", 1)
    kills = _rows(con.execute(f"""SELECT k.session_id, k.ms, k.weapon, k.me_victim, k.me_killer, k.victim_idx,
        k.killer_idx, k.destroyed_weapon, kt.type killer_type, vt.type victim_type {J}
        AND k.victim_name IS NOT NULL ORDER BY k.session_id, k.ms""", p))
    if f.get("type") == "ground":
        return _ground_report(con, f, kills)

    # what kills you vs what kills everybody else in the same battles
    my_d = _class_counts([k["weapon"] for k in kills if k["me_victim"]])
    lob_d = _class_counts([k["weapon"] for k in kills if not k["me_victim"]])
    my_k = _class_counts([k["weapon"] for k in kills if k["me_killer"] and not k["destroyed_weapon"]])
    lob_k = _class_counts([k["weapon"] for k in kills if not k["me_killer"] and k["killer_idx"] is not None
                           and not k["destroyed_weapon"]])
    classes = [{"id": c, "name": n, "my_deaths": my_d[c], "lobby_deaths": lob_d[c], "my_kills": my_k[c],
                "lobby_kills": lob_k[c]} for c, n in skills.CLASSES.items()]

    my_fd, lob_fd = _first_death(kills)
    lob = _lobby(con, w, p)

    # telemetry: defensive window of every shot-down life, paired in order with the replay's kill weapon
    lives = _rows(con.execute(f"""SELECT l.*, b.session_id, b.started, b.map
        FROM lives l JOIN battles b ON b.match_id = l.match_id{w} ORDER BY b.started, l.idx""", p))
    my_deaths: dict = {}
    for k in kills:
        if k["me_victim"]:
            my_deaths.setdefault(k["session_id"], []).append(k)
    defense, used = [], {}
    for l in lives:
        if l["end_reason"] != "shot_down":
            continue
        i = used.get(l["session_id"], 0)
        used[l["session_id"]] = i + 1
        dk = my_deaths.get(l["session_id"], [])
        wpn = dk[i]["weapon"] if i < len(dk) else None
        cls = skills.weapon_class(wpn) if i < len(dk) else "unknown"
        style, verdict = skills.defense_verdict(cls, l) if l["def_max_g"] is not None else ("veri yok", "n/a")
        defense.append({"session_id": l["session_id"], "started": l["started"], "map": l["map"],
                        "vehicle": names.vehicle(l["vehicle"]), "weapon": names.weapon(wpn) if wpn else None,
                        "cls": cls, "style": style, "verdict": verdict,
                        **{c: l[c] for c in ("def_threat_km", "def_aspect", "def_notch", "def_cold", "def_hot",
                                             "def_low", "def_max_g", "def_turn_deg", "def_tas0", "def_tas1",
                                             "def_alt0", "def_alt1")}})

    flown = [l for l in lives if (l["duration_s"] or 0) >= 60]
    energy = {"n": len(flown), "energy_m": _avg([l["energy_m"] for l in flown]),
              "low_energy": _avg([l["low_energy_share"] for l in flown]),
              "ab": _avg([l["ab_share"] for l in flown]), "front": _avg([l["front_share"] for l in flown]),
              "low_alt": _avg([l["low_alt_share"] for l in flown]), "max_g": _avg([l["max_g"] for l in flown]),
              "avg_tas": _avg([l["avg_tas_kmh"] for l in flown])}

    bases = _bases(con, w, p)
    return {"kind": "air", "classes": classes, "first_death": {"me": my_fd, "lobby": lob_fd}, "lobby": lob,
            "defense": defense, "energy": energy, "bases": bases,
            "findings": _findings(classes, my_fd, lob_fd, lob, defense, energy, bases)}


def _bases(con, w, p) -> dict:
    """Base bombing: counted in bases taken (result text, or a per-aircraft estimate), never in tonnage."""
    b = dict(con.execute(f"""SELECT COUNT(bases_est) n, SUM(has_result) exact, SUM(bases_est) bases,
        SUM(bases_est > 0) with_bases, SUM(air_kills) air_kills, MAX(bases_est) best
        FROM battles b{w} AND b.bases_est IS NOT NULL""", p).fetchone())
    # grind effect: only battles with a result text have exact RP/SL and an exact base count
    split = _rows(con.execute(f"""SELECT bases > 0 took, COUNT(*) n, AVG(total_rp) rp, AVG(total_sl) sl,
        AVG(score) score, AVG(air_kills) kills, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_rp END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) rp_min, 60.0 * SUM(CASE WHEN has_result = 1 THEN total_sl END) / NULLIF(SUM(CASE WHEN has_result = 1 THEN played_s END), 0) sl_min
        FROM battles b{w} AND b.has_result = 1 GROUP BY 1""", p))
    b["split"] = {("with" if r["took"] else "without"): r for r in split}
    # timing: when the first base falls and whether you die before reaching one (result text + replay)
    timing = _rows(con.execute(f"""
        SELECT b.session_id, b.bases, (SELECT MIN(time_s) FROM result_items ri WHERE ri.session_id = b.session_id
                AND ri.category = 'Yok edilen üsler') fb,
               (SELECT MIN(ms) / 1000.0 FROM replay_kills k WHERE k.session_id = b.session_id AND k.me_victim = 1) fd
        FROM battles b{w} AND b.has_result = 1 AND b.has_replay = 1""", p))
    times = [con.execute("SELECT time_s FROM result_items WHERE session_id = ? AND category = 'Yok edilen üsler' "
                         "ORDER BY time_s", (t["session_id"],)).fetchall() for t in timing]
    gaps = [b2[0] - b1[0] for ts in times for b1, b2 in zip(ts, ts[1:])]
    died = [t for t in timing if t["fd"] is not None]
    b["timing"] = {
        "n": len(timing), "first_base_s": _median([t["fb"] for t in timing]),
        "gap_s": _median(gaps), "died": len(died),
        "died_before_base": sum(1 for t in died if t["fb"] is None or t["fd"] < t["fb"]),
        "died_without_base": sum(1 for t in died if not t["bases"]),
    }
    b["weapons"] = _rows(con.execute(f"""SELECT ri.weapon name, COUNT(*) n FROM result_items ri
        JOIN battles b ON b.session_id = ri.session_id{w} AND ri.category = 'Yok edilen üsler'
        GROUP BY ri.weapon ORDER BY n DESC LIMIT 6""", p))
    n = b["n"] or 0
    b["per_match"] = (b["bases"] or 0) / n if n else None
    b["share"] = (b["with_bases"] or 0) / n if n else None
    b["impact"] = ((b["bases"] or 0) + (b["air_kills"] or 0)) / n if n else None
    return b


def _first_death(kills) -> tuple:
    """Median time of each player's first death: you vs the rest of the lobby (ms)."""
    first: dict = {}
    for k in kills:
        first.setdefault((k["session_id"], k["victim_idx"]), (k["ms"], k["me_victim"]))
    return (_median([ms for ms, me in first.values() if me]), _median([ms for ms, me in first.values() if not me]))


def _lobby(con, w, p) -> dict:
    bw = w + " AND b.has_replay = 1"
    return dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw})
        SELECT COUNT(DISTINCT session_id) n,
          AVG(CASE WHEN is_me=1 THEN missile_evades END) my_ev, AVG(CASE WHEN is_me=0 THEN missile_evades END) l_ev,
          SUM(CASE WHEN is_me=1 THEN mode_kills END) my_k, SUM(CASE WHEN is_me=1 THEN deaths END) my_d,
          SUM(CASE WHEN is_me=0 THEN mode_kills END) l_k, SUM(CASE WHEN is_me=0 THEN deaths END) l_d,
          AVG(CASE WHEN is_me=1 THEN assists END) my_a, AVG(CASE WHEN is_me=0 THEN assists END) l_a,
          AVG(CASE WHEN is_me=1 THEN mode_kills END) my_kpm, AVG(CASE WHEN is_me=0 THEN mode_kills END) l_kpm,
          AVG(CASE WHEN is_me=1 THEN deaths END) my_dpm, AVG(CASE WHEN is_me=0 THEN deaths END) l_dpm,
          AVG(CASE WHEN is_me=1 THEN capture_zone END) my_cz, AVG(CASE WHEN is_me=0 THEN capture_zone END) l_cz
        FROM replay_players rp JOIN bs USING (session_id)""", p).fetchone())


def _count_rows(keys: dict, mine: list, lobby: list, mine_k: list, lobby_k: list) -> list[dict]:
    def cnt(xs):
        out = {c: 0 for c in keys}
        for x in xs:
            out[x] = out.get(x, 0) + 1
        return out
    a, b, c, d = cnt(mine), cnt(lobby), cnt(mine_k), cnt(lobby_k)
    return [{"id": k, "name": n, "my_deaths": a.get(k, 0), "lobby_deaths": b.get(k, 0), "my_kills": c.get(k, 0),
             "lobby_kills": d.get(k, 0)} for k, n in keys.items()]


def _ground_report(con, f, kills) -> dict:
    w, p = build_where(f)
    real = [k for k in kills if not k["destroyed_weapon"]]

    def killer(k):
        return skills.vehicle_group(k["killer_type"], k["weapon"])

    def victim(k):
        return skills.vehicle_group(k["victim_type"], "any")

    others_killed = [k for k in real if not k["me_killer"] and k["killer_idx"] is not None]
    by_killer = _count_rows(skills.GROUPS,
                            [killer(k) for k in real if k["me_victim"]],
                            [killer(k) for k in real if not k["me_victim"]],
                            [victim(k) for k in real if k["me_killer"]],
                            [victim(k) for k in others_killed])
    # ammo only means something for ground-vs-ground: kills made by tanks / SPAA
    gnd = [k for k in real if killer(k) in ("tank", "spaa")]
    am = lambda k: skills.ground_ammo_class(k["weapon"])
    ammo = _count_rows(skills.AMMO,
                       [am(k) for k in gnd if k["me_victim"]],
                       [am(k) for k in gnd if not k["me_victim"]],
                       [am(k) for k in gnd if k["me_killer"]],
                       [am(k) for k in gnd if not k["me_killer"] and k["killer_idx"] is not None])
    my_fd, lob_fd = _first_death(kills)
    lob = _lobby(con, w, p)
    coverage = {"mapped": sum(1 for k in real if k["me_victim"]), "total": lob.get("my_d")}
    vehicles = ground_vehicles(con, f)
    return {"kind": "ground", "classes": by_killer, "ammo": ammo, "coverage": coverage,
            "first_death": {"me": my_fd, "lobby": lob_fd},
            "lobby": lob, "defense": [], "energy": {"n": 0}, "vehicles": vehicles,
            "findings": _ground_findings(by_killer, ammo, my_fd, lob_fd, lob, vehicles)}


def _ground_findings(groups, ammo, my_fd, lob_fd, lob, vehicles=()) -> list[dict]:
    out = []
    _ground_extra = []
    if lob.get("my_cz") is not None and lob.get("l_cz"):
        r = lob["my_cz"] / lob["l_cz"]
        detail = f"Maç başına {lob['my_cz']:.2f} bölge ele geçirme; lobi {lob['l_cz']:.2f}."
        if r >= 1.3:
            _ground_extra.append(("strong", "Bölge ele geçirmede lobinin üstündesin", detail))
        elif r <= 0.6:
            _ground_extra.append(("weak", "Bölgelere az giriyorsun", detail))
    good = [v for v in vehicles if v["k"] + v["d"] >= 4]
    if len(good) >= 2:
        best = max(good, key=lambda v: v["k"] / max(v["d"], 1))
        worst = min(good, key=lambda v: v["k"] / max(v["d"], 1))
        if best is not worst:
            _ground_extra.append(("note", f"En verimli aracın: {best['vehicle_name']}",
                                  f"{best['vehicle_name']}: {best['k']} kill / {best['d']} ölüm; "
                                  f"{worst['vehicle_name']}: {worst['k']} kill / {worst['d']} ölüm (eşleşen kayıtlar)."))

    def add(kind, title, detail, n, min_n=5, hint=None):
        out.append({"kind": kind, "title": title, "detail": detail, "n": n, "low_data": n < min_n, "hint": hint})

    g = {c["id"]: c for c in groups}
    my_total = sum(c["my_deaths"] for c in groups)
    lob_total = sum(c["lobby_deaths"] for c in groups)
    if my_total >= 5 and lob_total:
        air_me = (g["air"]["my_deaths"] + g["heli"]["my_deaths"]) / my_total
        air_lob = (g["air"]["lobby_deaths"] + g["heli"]["lobby_deaths"]) / lob_total
        detail = f"Ölümlerinin {_pct(air_me)} kadarı uçak ya da helikopterden; aynı maçlardaki lobide {_pct(air_lob)}."
        if air_me - air_lob >= 0.08:
            add("weak", "Hava saldırılarına açıksın", detail, my_total, 8,
                "Düşman uçağı uyarısında açık alanda durma; bina, ağaç ya da tepe arkasına geç, SPAA'ya yakın kal.")
        elif air_lob - air_me >= 0.08:
            add("strong", "Hava saldırılarından iyi korunuyorsun", detail, my_total, 8)
        t_me, t_lob = g["tank"]["my_deaths"] / my_total, g["tank"]["lobby_deaths"] / lob_total
        if t_me - t_lob >= 0.1:
            add("weak", "Tank düellolarında sık düşüyorsun",
                f"Ölümlerinin {_pct(t_me)} kadarı tanklardan; lobide {_pct(t_lob)}.", my_total, 8,
                "Tepe arkasından (hull-down) ateş et, köşe başlarını önce kontrol et, ateş ettikten sonra yer değiştir.")
        c_me, c_lob = g["none"]["my_deaths"] / my_total, g["none"]["lobby_deaths"] / lob_total
        if c_me - c_lob >= 0.08:
            add("weak", "Silahsız ölümler fazla",
                f"Ölümlerinin {_pct(c_me)} kadarı silahsız (kaza, devrilme, çarpma); lobide {_pct(c_lob)}.",
                my_total, 8)

    if lob.get("my_d") and lob.get("l_d"):
        mine, theirs = lob["my_k"] / lob["my_d"], lob["l_k"] / lob["l_d"]
        detail = f"K/D {mine:.2f} (kara + hava kill); aynı maçlardaki lobi {theirs:.2f}."
        if mine >= theirs * 1.2:
            add("strong", "Lobiden yüksek K/D", detail, lob["n"] or 0)
        elif mine <= theirs * 0.8:
            add("weak", "K/D lobinin altında", detail, lob["n"] or 0)
    if lob.get("my_a") is not None and lob.get("l_a"):
        detail = f"Maç başına {lob['my_a']:.1f} asist; lobi {lob['l_a']:.1f}."
        if lob["my_a"] >= lob["l_a"] * 1.3:
            add("strong", "Takımına çok destek veriyorsun", detail, lob["n"] or 0)
        elif lob["my_a"] <= lob["l_a"] * 0.7:
            add("note", "Asistlerin lobinin altında", detail, lob["n"] or 0)
    if my_fd and lob_fd:
        diff = (lob_fd - my_fd) / 1000
        detail = f"İlk ölümün ortanca {my_fd / 60000:.1f}. dakikada; lobide {lob_fd / 60000:.1f}. dakikada."
        if diff >= 30:
            add("weak", "Lobiden erken düşüyorsun", detail, my_total, 5,
                "İlk dakikalarda bilinen kamp ve keskin nişancı noktalarından uzak dur, takımla birlikte ilerle.")
        elif diff <= -30:
            add("strong", "Lobiden uzun hayatta kalıyorsun", detail, my_total)

    mk = sum(c["my_kills"] for c in ammo)
    if mk >= 5:
        top = max(ammo, key=lambda c: c["my_kills"])
        add("note", f"Kara kill'lerinin çoğu: {top['name']}",
            f"Kara hedeflerine aldığın kill'lerin {_pct(top['my_kills'] / mk)} kadarı bu mühimmatla.", mk)
    for kind, title, detail in _ground_extra:
        add(kind, title, detail, lob.get("n") or 0)
    order = {"weak": 0, "strong": 1, "note": 2}
    out.sort(key=lambda x: (x["low_data"], order[x["kind"]]))
    return out


def _findings(classes, my_fd, lob_fd, lob, defense, energy, bases=None) -> list[dict]:
    out = []

    def add(kind, title, detail, n, min_n=5, hint=None):
        out.append({"kind": kind, "title": title, "detail": detail, "n": n, "low_data": n < min_n, "hint": hint})

    hints = {
        "radar": "Kilit uyarısında füzeye dik dön (notch) ya da 60 m altına in (multipath); chaff'ı notch'la birlikte at.",
        "ir": "8-10 km içinde art yakıcıyı kıs, flare'ı füze atılmadan önce de kullan, düşmanın arka yarı küresinde oyalanma.",
        "sam": "Haritadaki SAM bölgelerine 10-15 km'den fazla yaklaşma; alçakta arazinin arkasında kal.",
        "gun": "Yakın it dalaşında enerjiyi koru, düz uçuştan kaçın.",
        "none": "Alçak uçuşta arazi ve aşırı G (bayılma / kanat kopması) sınırlarına dikkat.",
    }

    my_total = sum(c["my_deaths"] for c in classes)
    lob_total = sum(c["lobby_deaths"] for c in classes)
    if my_total >= 5 and lob_total:
        for c in classes:
            if c["id"] == "other":
                continue
            a, b = c["my_deaths"] / my_total, c["lobby_deaths"] / lob_total
            what = c["name"] if c["id"] != "none" else "Kaza / yere çakılma"
            if a - b >= 0.08:
                detail = f"Ölümlerinin {_pct(a)} kadarı bu kaynaktan; aynı maçlardaki lobide {_pct(b)}."
                if c["id"] == "ir" and (energy.get("ab") or 0) >= 0.6:
                    detail += f" Art yakıcın uçuş süresinin {_pct(energy['ab'])} kadarında açık; IR füzeleri için kolay hedef."
                add("weak", f"{what} seni sık düşürüyor", detail, my_total, 8, hints.get(c["id"]))
            elif b - a >= 0.08 and c["lobby_deaths"] >= 10:
                add("strong", f"{what} seni nadiren düşürüyor",
                    f"Ölümlerinin {_pct(a)} kadarı bu kaynaktan; lobide {_pct(b)}.", my_total, 8)

    if lob.get("my_ev") is not None and lob.get("l_ev"):
        r = lob["my_ev"] / lob["l_ev"]
        detail = f"Maç başına {lob['my_ev']:.1f} füzeden kaçış; lobi ortalaması {lob['l_ev']:.1f}."
        if r >= 1.2:
            add("strong", "Füzelerden kaçmakta iyisin", detail, lob["n"] or 0)
        elif r <= 0.8:
            add("weak", "Füzelerden kaçışın lobinin altında", detail, lob["n"] or 0)

    if lob.get("my_d") and lob.get("l_d"):
        mine, theirs = lob["my_k"] / lob["my_d"], lob["l_k"] / lob["l_d"]
        detail = f"K/D {mine:.2f}; aynı maçlardaki lobi {theirs:.2f}."
        if mine >= theirs * 1.2:
            add("strong", "Lobiden yüksek K/D", detail, lob["n"] or 0)
        elif mine <= theirs * 0.8:
            if bases and (bases.get("per_match") or 0) >= 0.3:
                detail += (f" Ama maç başına {bases['per_match']:.1f} üs alıyorsun; oyun tarzın kill değil "
                           f"hedef odaklı, K/D tek başına seni anlatmıyor.")
                add("note", "K/D lobinin altında, ama üs bombalıyorsun", detail, lob["n"] or 0)
            else:
                add("weak", "K/D lobinin altında", detail, lob["n"] or 0)

    if my_fd and lob_fd:
        diff = (lob_fd - my_fd) / 1000
        detail = f"İlk ölümün ortanca {my_fd / 60000:.1f}. dakikada; lobide {lob_fd / 60000:.1f}. dakikada."
        if diff >= 30:
            add("weak", "Lobiden erken düşüyorsun", detail, my_total)
        elif diff <= -30:
            add("strong", "Lobiden uzun hayatta kalıyorsun", detail, my_total)

    measured = [d for d in defense if d["verdict"] != "n/a" and d["cls"] in ("radar", "ir", "gun", "sam")]
    radar = [d for d in measured if d["cls"] == "radar"]
    if radar:
        undefended = [d for d in radar if d["verdict"] != "good"]
        notch = sum(1 for d in radar if (d["def_notch"] or 0) >= 0.35)
        mp = sum(1 for d in radar if (d["def_low"] or 0) >= 0.5)
        detail = (f"Radar füzesiyle düştüğün {len(radar)} ölümün {notch} tanesinde notch, {mp} tanesinde "
                  f"multipath (60 m altı) görüldü.")
        if len(undefended) / len(radar) >= 0.5:
            add("weak", "Vurulduğun radar füzelerinde savunma zayıf", detail, len(radar), 4, hints["radar"])
        elif len(undefended) / len(radar) <= 0.25:
            add("note", "Radar füzelerine karşı savunma yapıyorsun",
                detail + " Yine de vurulduğuna göre zamanlama ya da yön seçimi gözden geçirilebilir.",
                len(radar), 4)
    hot = [d for d in measured if (d["def_hot"] or 0) >= 0.5]
    if measured and len(hot) / len(measured) >= 0.35:
        add("weak", "Vurulmadan önce tehdide doğru uçuyorsun",
            f"{len(measured)} ölümün {len(hot)} tanesinde son 15 saniyenin yarısından fazlasında burnun "
            f"en yakın düşmana dönüktü.", len(measured), 4,
            "Atışını yaptıktan sonra burnunu çevir (crank / soğuk), füzen ulaşana kadar düşmana doğru kapanma.")

    if energy["n"] and energy["low_energy"] is not None:
        if energy["low_energy"] >= 0.12:
            add("weak", "Enerjini sık kaybediyorsun",
                f"Uçuş süresinin {_pct(energy['low_energy'])} kadarı 600 km/h altında (300 m üstü).",
                energy["n"], 4)
        elif energy["low_energy"] <= 0.03:
            add("strong", "Enerjini koruyorsun",
                f"Uçuş süresinin yalnızca {_pct(energy['low_energy'])} kadarı 600 km/h altında.", energy["n"], 4)
    if energy["n"] and energy["front"] is not None and energy["front"] >= 0.4:
        add("note", "Sık sık takımın en önündesin",
            f"Düşman görünürken zamanın {_pct(energy['front'])} kadarında düşmana en yakın dost uçak sendin. "
            f"Bu hem fırsat hem de ilk hedef olmak demek.", energy["n"], 4)
    if bases and bases.get("n"):
        n, pm = bases["n"], bases["per_match"] or 0
        w_, wo = bases["split"].get("with"), bases["split"].get("without")
        detail = (f"{n} maçta toplam {bases['bases'] or 0} üs; maç başına {pm:.1f}, "
                  f"maçların {_pct(bases['share'] or 0)} kadarında en az bir üs aldın.")
        if w_ and wo and w_["rp"] and wo["rp"]:
            detail += (f" Üs aldığın maçlarda ortalama {_num(w_['rp'])} RP / {_num(w_['sl'])} SL, "
                       f"almadıklarında {_num(wo['rp'])} RP / {_num(wo['sl'])} SL.")
        if pm >= 0.5 or (bases["share"] or 0) >= 0.35:
            add("strong", "Üs bombalamada güçlüsün", detail, n, 5)
            out[-1]["prio"] = 1
        tm = bases.get("timing") or {}
        if tm.get("died", 0) >= 5 and tm["died_before_base"] / tm["died"] >= 0.5:
            add("weak", "Düştüğün maçların çoğunda üs alamadan düşüyorsun",
                f"Düştüğün {tm['died']} maçın {tm['died_before_base']} tanesinde ilk üssünü almadan önce düştün.",
                tm["died"], 5,
                "Üs koşusunda alçak ve hızlı gir, ilk dakikalarda radar füzelerine karşı arazinin arkasında kal; "
                "önce en yakın üsse değil, düşman savaşçılarının uzak olduğu kanattaki üsse yönel.")
        elif pm > 0:
            add("note", "Arada üs alıyorsun", detail, n, 5)
        if w_ and wo and w_["rp"] and wo["rp"] and w_["n"] >= 3 and wo["n"] >= 3 and w_["rp"] >= 1.5 * wo["rp"]:
            per_min = (f" Dakika başına: {_num(w_['rp_min'])} RP'ye karşı {_num(wo['rp_min'])} RP."
                       if w_.get("rp_min") and wo.get("rp_min") else "")
            add("strong", f"Üs almak grind'ını {w_['rp'] / wo['rp']:.1f} kat artırıyor",
                f"Sonuç metni olan {w_['n'] + wo['n']} maçta: üs aldığın {w_['n']} maçın ortalaması "
                f"{_num(w_['rp'])} RP, almadığın {wo['n']} maçın {_num(wo['rp'])} RP.{per_min}",
                w_["n"] + wo["n"], 6)
            out[-1]["prio"] = 1
    order = {"weak": 0, "strong": 1, "note": 2}
    out.sort(key=lambda x: (x["low_data"], order[x["kind"]], -x.get("prio", 0)))
    return out
