"""Turns a recorded session into a match summary: lives, kills, deaths, telemetry."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field

from . import killfeed, skills
from .session import Session

ANALYZER_VERSION = 5
NOT_SPAWNED_TYPES = {"dummy_plane", ""}
KILL_KINDS = {"kill", "destroy"}
DAMAGE_KINDS = {"crit", "severe", "fire", "hit", "kill", "destroy"}
LOW_ALT_M = 300  # "on the deck" threshold for multipath-style flying


@dataclass
class Life:
    idx: int
    vehicle: str
    spawn_t: float
    end_t: float
    end_reason: str = "unknown"       # shot_down | crashed | survived | left
    killer: str | None = None
    killer_vehicle: str | None = None
    first_hit_t: float | None = None  # first damage taken in this life
    death_alt_m: float | None = None
    death_tas_kmh: float | None = None
    death_mach: float | None = None
    death_g: float | None = None
    death_nearest_enemy_km: float | None = None
    death_enemies_within_20km: int | None = None
    kills_air: int = 0
    kills_ground: int = 0
    hits_dealt: int = 0
    hits_taken: int = 0
    max_g: float | None = None
    min_g: float | None = None
    max_mach: float | None = None
    avg_alt_m: float | None = None
    avg_tas_kmh: float | None = None
    low_alt_share: float | None = None  # share of time below LOW_ALT_M
    distance_km: float | None = None
    # pre-hit defensive window (see skills.defense_window)
    def_threat_km: float | None = None
    def_aspect: float | None = None
    def_notch: float | None = None
    def_cold: float | None = None
    def_hot: float | None = None
    def_low: float | None = None
    def_max_g: float | None = None
    def_turn_deg: float | None = None
    def_tas0: float | None = None
    def_tas1: float | None = None
    def_alt0: float | None = None
    def_alt1: float | None = None
    # whole-life profile (see skills.life_profile)
    energy_m: float | None = None
    low_energy_share: float | None = None
    ab_share: float | None = None
    front_share: float | None = None

    @property
    def duration_s(self) -> float:
        return round(self.end_t - self.spawn_t, 1)


@dataclass
class Match:
    id: str
    started: str | None
    duration_s: float | None
    vehicle: str | None
    result: str                       # win | loss | unknown
    map_key: str | None
    map_size_km: float | None
    objectives: list[str] = field(default_factory=list)
    lives: list[Life] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    unknown_messages: list[str] = field(default_factory=list)


def _is_enemy(color: str | None) -> bool:
    rgb = _rgb(color)
    return rgb is not None and rgb[0] > 150 and rgb[1] < 110 and rgb[2] < 110


def _rgb(color):
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return None
    try:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None


def _map_geometry(s: Session):
    for _, d in zip(s.map_info.t, s.map_info.d):
        if isinstance(d, dict) and d.get("valid") and d.get("map_min") and d.get("map_max"):
            return d
    return None


def _objectives(s: Session) -> list[str]:
    texts: set[str] = set()
    for d in s.mission.d:
        if isinstance(d, dict):
            for o in d.get("objectives") or []:
                if isinstance(o, dict) and o.get("text"):
                    texts.add(o["text"])
    return sorted(texts)


def _map_key(s: Session, geo, objectives) -> str | None:
    h = s.map_jpg_hash()
    if h:
        return "img:" + h
    if geo is None:
        return None
    sig = repr((geo.get("map_min"), geo.get("map_max"), geo.get("grid_zero"), objectives))
    return "obj:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]


def _player_pos(frame):
    if isinstance(frame, list):
        for o in frame:
            if isinstance(o, dict) and o.get("icon") == "Player" and "x" in o:
                return o["x"], o["y"]
    return None


def _detect_lives(s: Session) -> list[Life]:
    lives: list[Life] = []
    current: Life | None = None
    for t, d in zip(s.indicators.t, s.indicators.d):
        vtype = d.get("type", "") if isinstance(d, dict) else ""
        alive = isinstance(d, dict) and d.get("valid") and vtype not in NOT_SPAWNED_TYPES
        if alive and current is None:
            current = Life(idx=len(lives), vehicle=vtype, spawn_t=t, end_t=t)
        elif alive and current is not None:
            if vtype != current.vehicle:  # vehicle changed without despawn
                lives.append(current)
                current = Life(idx=len(lives), vehicle=vtype, spawn_t=t, end_t=t)
            else:
                current.end_t = t
        elif not alive and current is not None:
            lives.append(current)
            current = None
    if current is not None:
        lives.append(current)
    return [l for l in lives if l.end_t - l.spawn_t >= 3.0]  # ignore flickers


def _life_for(lives: list[Life], t: float, slack: float = 5.0) -> Life | None:
    for l in lives:
        if l.spawn_t - 1.0 <= t <= l.end_t + slack:
            return l
    return None


def _telemetry(s: Session, life: Life, scale_m: float | None) -> None:
    gs, machs, alts, tas, times = [], [], [], [], []
    # G is only counted while flying intact: hits and impacts produce unrealistic spikes.
    g_until = (life.first_hit_t - 1.0) if life.first_hit_t is not None else life.end_t - 2.0
    for t, d in s.state.between(life.spawn_t, life.end_t):
        if not (isinstance(d, dict) and d.get("valid")):
            continue
        times.append(t)
        if (v := d.get("Ny")) is not None and t <= g_until: gs.append(v)
        if (v := d.get("M")) is not None: machs.append(v)
        if (v := d.get("H, m")) is not None: alts.append(v)
        if (v := d.get("TAS, km/h")) is not None: tas.append(v)
    if gs:
        life.max_g, life.min_g = round(max(gs), 2), round(min(gs), 2)
    if machs:
        life.max_mach = round(max(machs), 2)
    if alts:
        life.avg_alt_m = round(sum(alts) / len(alts))
        life.low_alt_share = round(sum(1 for a in alts if a < LOW_ALT_M) / len(alts), 3)
    if tas:
        life.avg_tas_kmh = round(sum(tas) / len(tas))
    if scale_m:
        dist, prev = 0.0, None
        for _, frame in s.map_obj.between(life.spawn_t, life.end_t):
            p = _player_pos(frame)
            if p and prev:
                step = math.dist(p, prev) * scale_m
                if step < 2000:  # ignore teleports / respawn jumps
                    dist += step
            prev = p or prev
        life.distance_km = round(dist / 1000, 1)


def _death_snapshot(s: Session, life: Life, t_hit: float, scale_m: float | None) -> None:
    # Messages arrive up to ~0.5 s after the fact; look a bit before.
    st = s.state.at(t_hit - 0.5)
    if isinstance(st, dict) and st.get("valid"):
        life.death_alt_m = st.get("H, m")
        life.death_tas_kmh = st.get("TAS, km/h")
        life.death_mach = st.get("M")
        life.death_g = st.get("Ny")
    frame = s.map_obj.at(t_hit - 0.5)
    me = _player_pos(frame)
    if me and scale_m and isinstance(frame, list):
        dists = [math.dist(me, (o["x"], o["y"])) * scale_m / 1000
                 for o in frame if isinstance(o, dict) and o.get("type") == "aircraft"
                 and o.get("icon") != "Player" and "x" in o and _is_enemy(o.get("color"))]
        if dists:
            life.death_nearest_enemy_km = round(min(dists), 1)
        life.death_enemies_within_20km = sum(1 for x in dists if x <= 20)


def analyze(s: Session, me: str) -> Match:
    geo = _map_geometry(s)
    scale_m = None
    if geo:
        scale_m = float(geo["map_max"][0]) - float(geo["map_min"][0])
    objectives = _objectives(s)
    statuses = [d.get("status") for d in s.mission.d if isinstance(d, dict)]
    final = statuses[-1] if statuses else None
    result = {"success": "win", "fail": "loss"}.get(final, "unknown")

    # After death / match end the game shows a parked plane (H~19 m, TAS~0); drop lives that never moved.
    lives = [l for l in _detect_lives(s)
             if max((d.get("TAS, km/h") or 0 for _, d in s.state.between(l.spawn_t, l.end_t)
                     if isinstance(d, dict)), default=0) >= 50]
    for i, l in enumerate(lives):
        l.idx = i
    m = Match(
        id=s.id,
        started=s.meta.get("started"),
        duration_s=s.meta.get("duration_s"),
        vehicle=lives[0].vehicle if lives else None,
        result=result,
        map_key=_map_key(s, geo, objectives),
        map_size_km=round(scale_m / 1000, 1) if scale_m else None,
        objectives=objectives,
        lives=lives,
    )

    seen_ids = set()
    for t, raw in s.damage:
        mid = raw.get("id")
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        ev = killfeed.parse(raw.get("msg", ""))
        if ev.kind == "noise":
            continue
        if ev.kind == "other":
            m.unknown_messages.append(ev.raw)
        me_actor = killfeed.same_player(ev.actor, me)
        me_target = killfeed.same_player(ev.target, me)
        rec = asdict(ev)
        rec.update(t=t, game_time=raw.get("time"), me_actor=me_actor, me_target=me_target)
        m.events.append(rec)

        life = _life_for(lives, t)
        if life is None:
            continue
        if me_actor and ev.kind in KILL_KINDS and ev.extra != "ai":
            # air vs ground: ground targets usually have no player name in Air RB
            life.kills_air += 1
        elif me_actor and ev.kind in KILL_KINDS:
            life.kills_ground += 1
        if me_actor and ev.kind in DAMAGE_KINDS:
            life.hits_dealt += 1
        if me_target and ev.kind in DAMAGE_KINDS:
            life.hits_taken += 1
            if life.first_hit_t is None:
                life.first_hit_t = t
        if me_target and ev.kind in KILL_KINDS:
            life.end_reason = "shot_down"
            life.killer, life.killer_vehicle = ev.actor, ev.actor_vehicle
        if me_actor and ev.kind == "crash" and life.end_reason == "unknown":
            life.end_reason = "crashed"

    for life in lives:
        _telemetry(s, life, scale_m)
        for k, v in skills.life_profile(s, life.spawn_t, life.end_t, scale_m).items():
            setattr(life, k, v)
        if life.end_reason == "shot_down" and life.first_hit_t is not None:
            for k, v in skills.defense_window(s, life.first_hit_t, scale_m).items():
                setattr(life, k, v)
        if life.end_reason in ("shot_down", "crashed"):
            _death_snapshot(s, life, life.first_hit_t or life.end_t, scale_m)
        elif life is lives[-1] and result != "unknown":
            life.end_reason = "survived"
        else:
            life.end_reason = "left"
    return m
