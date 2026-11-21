"""Skill heuristics: weapon classes, pre-hit defensive window, energy and positioning per life.

Everything here is an estimate from what the game exposes. The 8111 API has no missile launch or RWR
data, so the defensive window is judged relative to the nearest *spotted* enemy aircraft, which is not
necessarily the shooter.
"""

from __future__ import annotations

import math
import re

G = 9.81
DEF_WINDOW_S = 15.0       # look this far back from the first hit
LOW_RADIO_ALT_M = 100     # below this radar missiles start to suffer from multipath
LOW_ENERGY_TAS = 600      # km/h; slower than this (while airborne and not landing) is "low energy"
THREAT_MAX_KM = 60

# ------------------------------------------------------------------ weapon classes
CLASSES = {
    "radar": "Radar güdümlü füze",
    "ir": "IR güdümlü füze",
    "gun": "Top / makineli",
    "sam": "Hava savunma (SAM/uçaksavar)",
    "none": "Silahsız (kaza / çarpma)",
    "other": "Diğer (bomba, roket, tank)",
}

_RADAR = re.compile(r"aim_?120|aim_?7|aim_?54|r_77|rvv_ae|rvv_sd|pl_?12|pl_?15|sd_?10|mica_em|rb_?99|rb_?71|"
                    r"aam_?4|r_27e?r|r_24r|r_3r|darter|derby(?!_er_sam)|fakour|r_98mr|r_40r|meteor|aspide|"
                    r"530f|530d|r_530|skyflash|sparrow")
_IR = re.compile(r"aim_?9|sidewinder|r_73|r_60|pl_?8|pl_?5|pl_?2|pl_?9|pl_?10|r_3s|r_13|r_27e?t|r_98mt|r_40t|"
                 r"r_24t|mica_ir|magic|r_550|iris_t|rb_?74|rb_?24|aam_?3|aam_?5|type_?90|python|sraam|aim_?92|"
                 r"stinger|matra_r550")
_SAM = re.compile(r"rim_|zur|9m311|9m331|9m33|mim|aster|hhq|roland|_sam|fim_92|9m37|3m7|5v55|vt_1|igla|"
                  r"crotale|rapier|essm|type_03|fm_3000")
_GUN_IDS = re.compile(r"^(ap_i|ap_t|ap_ball|ap_i_t|he_frag|he_i|sap_hei|t_ball|apds_autocannon|i_t|he_frag_i)")


def weapon_class(w: str | None) -> str:
    if not w:
        return "none"
    s = w.lower()
    if _SAM.search(s):
        return "sam"
    if _RADAR.search(s):
        return "radar"
    if _IR.search(s):
        return "ir"
    m = re.match(r"^(\d+)mm_", s)
    if m:
        return "gun" if int(m.group(1)) <= 40 else "other"
    if _GUN_IDS.match(s):
        return "gun"
    return "other"


# ------------------------------------------------------------------ map helpers
def _rgb(color):
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return None
    try:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None


def is_enemy(color) -> bool:
    rgb = _rgb(color)
    return rgb is not None and rgb[0] > 150 and rgb[1] < 110 and rgb[2] < 110


def _split_frame(frame):
    """-> (me obj | None, friendly aircraft [(x,y)], enemy aircraft [(x,y)])"""
    me, friends, enemies = None, [], []
    if not isinstance(frame, list):
        return me, friends, enemies
    for o in frame:
        if not isinstance(o, dict) or o.get("type") != "aircraft" or "x" not in o:
            continue
        if o.get("icon") == "Player":
            me = o
        elif is_enemy(o.get("color")):
            enemies.append((o["x"], o["y"]))
        else:
            friends.append((o["x"], o["y"]))
    return me, friends, enemies


def _aspect_deg(me: dict, target) -> float | None:
    """Angle between my heading and the line to the target: 0 = flying at it, 90 = beam, 180 = away."""
    hx, hy = me.get("dx"), me.get("dy")
    vx, vy = target[0] - me["x"], target[1] - me["y"]
    nh, nv = math.hypot(hx or 0, hy or 0), math.hypot(vx, vy)
    if not nh or not nv:
        return None
    c = max(-1.0, min(1.0, (hx * vx + hy * vy) / (nh * nv)))
    return math.degrees(math.acos(c))


def _share(xs, pred):
    return round(sum(1 for x in xs if pred(x)) / len(xs), 3) if xs else None


# ------------------------------------------------------------------ defensive window
def defense_window(s, t_hit: float, scale_m: float | None) -> dict:
    """Behaviour in the DEF_WINDOW_S seconds before the first hit."""
    t0, t1 = t_hit - DEF_WINDOW_S, t_hit - 0.3
    out: dict = {}
    aspects, dists = [], []
    if scale_m:
        for _, frame in s.map_obj.between(t0, t1):
            me, _, enemies = _split_frame(frame)
            if not me or not enemies:
                continue
            near = min(enemies, key=lambda e: math.dist((me["x"], me["y"]), e))
            d_km = math.dist((me["x"], me["y"]), near) * scale_m / 1000
            if d_km > THREAT_MAX_KM:
                continue
            a = _aspect_deg(me, near)
            if a is not None:
                aspects.append(a)
                dists.append(d_km)
    if aspects:
        out["def_threat_km"] = round(sorted(dists)[len(dists) // 2], 1)
        out["def_aspect"] = round(sum(aspects) / len(aspects))
        out["def_notch"] = _share(aspects, lambda a: 65 <= a <= 115)
        out["def_cold"] = _share(aspects, lambda a: a > 115)
        out["def_hot"] = _share(aspects, lambda a: a < 65)

    gs, tas, alt = [], [], []
    for _, d in s.state.between(t0, t1):
        if isinstance(d, dict) and d.get("valid"):
            if (v := d.get("Ny")) is not None: gs.append(v)
            if (v := d.get("TAS, km/h")) is not None: tas.append(v)
            if (v := d.get("H, m")) is not None: alt.append(v)
    if gs:
        out["def_max_g"] = round(max(gs), 1)
    if tas:
        out["def_tas0"], out["def_tas1"] = round(tas[0]), round(tas[-1])
    if alt:
        out["def_alt0"], out["def_alt1"] = round(alt[0]), round(alt[-1])

    radio, comp = [], []
    for t, d in s.indicators.between(t0, t1):
        if isinstance(d, dict) and d.get("valid"):
            st = s.state.at(t)
            h = st.get("H, m") if isinstance(st, dict) else None
            ra = d.get("radio_altitude")
            # cockpit gauges use the aircraft's own units: feet on western jets
            gauge = d.get("altitude_hour")
            if ra is not None and gauge and h and h > 50 and gauge / h > 2.5:
                ra *= 0.3048
            if ra is None or (ra <= 0 and (h or 0) > 200):
                ra = h  # no radar altimeter or out of range: barometric altitude is the best we have
            if ra is not None:
                radio.append(ra)
            if (c := d.get("compass")) is not None:
                comp.append(c)
    if radio:
        out["def_low"] = _share(radio, lambda r: r < LOW_RADIO_ALT_M)
    if len(comp) > 1:
        turn = 0.0
        for a, b in zip(comp, comp[1:]):
            turn += abs((b - a + 180) % 360 - 180)
        out["def_turn_deg"] = round(turn)
    return out


# ------------------------------------------------------------------ whole-life profile
def life_profile(s, spawn_t: float, end_t: float, scale_m: float | None) -> dict:
    out: dict = {}
    # skip take-off and the last seconds (hits / crash distort everything)
    t0, t1 = spawn_t + 40, end_t - 3
    if t1 - t0 < 20:
        return out
    es, tas_air, ab = [], [], []
    for _, d in s.state.between(t0, t1):
        if not (isinstance(d, dict) and d.get("valid")):
            continue
        h, v = d.get("H, m"), d.get("TAS, km/h")
        if h is None or v is None:
            continue
        es.append(h + (v / 3.6) ** 2 / (2 * G))
        if h > 300:
            tas_air.append(v)
        if (th := d.get("throttle 1, %")) is not None:
            ab.append(th)
    if es:
        out["energy_m"] = round(sum(es) / len(es))
    if tas_air:
        out["low_energy_share"] = _share(tas_air, lambda v: v < LOW_ENERGY_TAS)
    if ab:
        out["ab_share"] = _share(ab, lambda x: x > 100)

    if scale_m:
        front = total = 0
        for _, frame in s.map_obj.between(t0, t1):
            me, friends, enemies = _split_frame(frame)
            if not me or not friends or not enemies:
                continue
            my_d = min(math.dist((me["x"], me["y"]), e) for e in enemies) * scale_m / 1000
            if my_d > 80:
                continue
            best_friend = min(min(math.dist(f, e) for e in enemies) for f in friends) * scale_m / 1000
            total += 1
            front += my_d <= best_friend
        if total >= 10:
            out["front_share"] = round(front / total, 3)
    return out


# ------------------------------------------------------------------ verdicts
def defense_verdict(cls: str, w: dict) -> tuple[str, str]:
    """-> (style label, verdict) for one death. verdict: good | weak | none | n/a"""
    notch, cold, hot, low = (w.get("def_notch") or 0), (w.get("def_cold") or 0), (w.get("def_hot") or 0), \
        (w.get("def_low") or 0)
    g = w.get("def_max_g") or 0
    used = []
    if notch >= 0.35: used.append("notch")
    if low >= 0.5: used.append("multipath")
    if cold >= 0.5: used.append("soğuk kaçış")
    if g >= 6: used.append(f"sert manevra ({g:.0f} G)")
    style = ", ".join(used) if used else ("tehdide doğru" if hot >= 0.5 else "düz uçuş")
    if cls == "none":
        return "kaza / çarpma", "n/a"
    if cls == "radar":
        if any(u in used for u in ("notch", "multipath", "soğuk kaçış")):
            return style, "good"
        return style, "weak" if g >= 4 else "none"
    if cls in ("ir", "gun"):
        if g >= 6 or cold >= 0.5:
            return style, "good"
        return style, "weak" if g >= 3.5 else "none"
    if cls == "sam":
        return style, "good" if (low >= 0.5 or g >= 6) else "none"
    return style, "n/a"


# ------------------------------------------------------------------ ground battles
GROUPS = {
    "tank": "Tank / tank avcısı",
    "spaa": "Uçaksavar (SPAA)",
    "air": "Uçak",
    "heli": "Helikopter",
    "none": "Silahsız (kaza / çarpma)",
    "unknown": "Bilinmiyor",
}
_GROUP_OF_TYPE = {"tank": "tank", "medium_tank": "tank", "heavy_tank": "tank", "light_tank": "tank",
                  "tank_destroyer": "tank", "spaa": "spaa", "fighter": "air", "assault": "air", "bomber": "air",
                  "attacker": "air", "helicopter": "heli"}


def vehicle_group(vtype: str | None, weapon: str | None) -> str:
    if not weapon:
        return "none"
    return _GROUP_OF_TYPE.get((vtype or "").lower(), "unknown")


AMMO = {
    "kinetic": "Kinetik (APFSDS / APDS)",
    "heat": "Kimyasal (HEAT)",
    "atgm": "Tanksavar füzesi (ATGM)",
    "he": "Patlayıcı (HE / topçu)",
    "autocannon": "Otomatik top / makineli",
    "other": "Diğer",
}
_ATGM = re.compile(r"9m1\d\d|9m_1|tow|hj_?\d|kornet|spike|milan|hot_|ss_11|akeron|pars|lahat|refleks|9m120|mim146")
_HEAT = re.compile(r"heat|3bk|m830|dm12|jm12")
_KINETIC = re.compile(r"apfsds|sabot|3bm|m829|m900|m833|m774|m735|m322|dm[1-6]3|jm33|l2[3-7]|ke_w|dtc|dtw|"
                      r"type_?93|125_1|apds|apcr|xm885|_kc")
_HE = re.compile(r"3of|^\d+mm_he|hesh|m107|artillery|rocket_launcher|_of_")


def ground_ammo_class(w: str | None) -> str:
    if not w:
        return "other"
    s = w.lower()
    m = re.match(r"^(\d+)mm_", s)
    if (m and int(m.group(1)) <= 40) or _GUN_IDS.match(s):
        return "autocannon"
    for cls, rx in (("atgm", _ATGM), ("heat", _HEAT), ("kinetic", _KINETIC), ("he", _HE)):
        if rx.search(s):
            return cls
    return "other"
