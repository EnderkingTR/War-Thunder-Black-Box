"""Read-only queries over blackbox.db, returning plain dicts/lists (used by the web API)."""

from __future__ import annotations

import json

from . import names, session, skills

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


def _pct(x):
    return f"%{round(100 * x)}"


def skill_report(con, f: dict) -> dict:
    w, p = build_where(f)
    K = f"FROM replay_kills k JOIN battles b ON b.session_id = k.session_id{w}"
    kills = _rows(con.execute(f"""SELECT k.session_id, k.ms, k.weapon, k.me_victim, k.me_killer, k.victim_idx,
        k.killer_idx, k.destroyed_weapon {K} AND k.victim_name IS NOT NULL ORDER BY k.session_id, k.ms""", p))

    # what kills you vs what kills everybody else in the same battles
    my_d = _class_counts([k["weapon"] for k in kills if k["me_victim"]])
    lob_d = _class_counts([k["weapon"] for k in kills if not k["me_victim"]])
    my_k = _class_counts([k["weapon"] for k in kills if k["me_killer"] and not k["destroyed_weapon"]])
    lob_k = _class_counts([k["weapon"] for k in kills if not k["me_killer"] and k["killer_idx"] is not None
                           and not k["destroyed_weapon"]])
    classes = [{"id": c, "name": n, "my_deaths": my_d[c], "lobby_deaths": lob_d[c], "my_kills": my_k[c],
                "lobby_kills": lob_k[c]} for c, n in skills.CLASSES.items()]

    # first death time: you vs the lobby
    first_death: dict = {}
    for k in kills:
        first_death.setdefault((k["session_id"], k["victim_idx"]), (k["ms"], k["me_victim"]))
    my_fd = _median([ms for ms, me in first_death.values() if me])
    lob_fd = _median([ms for ms, me in first_death.values() if not me])

    bw = w + " AND b.has_replay = 1"
    lob = dict(con.execute(f"""WITH bs AS (SELECT session_id FROM battles b{bw})
        SELECT COUNT(DISTINCT session_id) n,
          AVG(CASE WHEN is_me=1 THEN missile_evades END) my_ev, AVG(CASE WHEN is_me=0 THEN missile_evades END) l_ev,
          SUM(CASE WHEN is_me=1 THEN kills END) my_k, SUM(CASE WHEN is_me=1 THEN deaths END) my_d,
          SUM(CASE WHEN is_me=0 THEN kills END) l_k, SUM(CASE WHEN is_me=0 THEN deaths END) l_d
        FROM replay_players rp JOIN bs USING (session_id)""", p).fetchone())

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

    return {"classes": classes, "first_death": {"me": my_fd, "lobby": lob_fd}, "lobby": lob,
            "defense": defense, "energy": energy,
            "findings": _findings(classes, my_fd, lob_fd, lob, defense, energy)}


def _findings(classes, my_fd, lob_fd, lob, defense, energy) -> list[dict]:
    out = []

    def add(kind, title, detail, n, min_n=5, hint=None):
        out.append({"kind": kind, "title": title, "detail": detail, "n": n, "low_data": n < min_n, "hint": hint})

    hints = {
        "radar": "Kilit uyarısında füzeye dik dön (notch) ya da 100 m altına in (multipath); chaff'ı notch'la birlikte at.",
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
                  f"multipath (100 m altı) görüldü.")
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
    order = {"weak": 0, "strong": 1, "note": 2}
    out.sort(key=lambda x: (x["low_data"], order[x["kind"]]))
    return out
