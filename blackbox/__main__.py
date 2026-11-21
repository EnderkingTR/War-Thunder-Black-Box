"""War Thunder BlackBox - komut satırı.

    python -m blackbox setup ENDERKING_tr     oyuncu adını kaydet
    python -m blackbox import [--force]       yeni kayıtları analiz edip veritabanına ekle
    python -m blackbox stats [filtreler]      genel istatistikler
    python -m blackbox matches [--last N]     maç listesi
    python -m blackbox match <id>             tek maçın detayı
    python -m blackbox maps                   harita anahtarları
    python -m blackbox name-map <key> <ad>    bir haritaya isim ver
    python -m blackbox unknown                tanınmayan kill feed satırları

Filtreler: --vehicle fa_18c_late  --map Sinai  --last 20  --since 2026-11-01
"""

from __future__ import annotations

import argparse
import json
import sys

from . import analyze, db, session
from .session import ROOT

CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def require_player() -> str:
    name = load_config().get("player_name")
    if not name:
        sys.exit("Önce oyuncu adını kaydet:  python -m blackbox setup <oyun_içi_adın>")
    return name


# ---------------------------------------------------------------- helpers
def fmt(v, digits=1, suffix=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}{suffix}"
    return f"{v}{suffix}"


def mmss(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def table(rows, headers):
    rows = [[("-" if c is None else str(c)) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def where_clause(args):
    conds, params = [], []
    if getattr(args, "vehicle", None):
        conds.append("m.vehicle LIKE ?")
        params.append(f"%{args.vehicle}%")
    if getattr(args, "map", None):
        conds.append("(mp.name LIKE ? OR m.map_key LIKE ?)")
        params += [f"%{args.map}%", f"%{args.map}%"]
    if getattr(args, "since", None):
        conds.append("m.started >= ?")
        params.append(args.since)
    sql = " WHERE " + " AND ".join(conds) if conds else ""
    if getattr(args, "last", None):
        sql += (" AND " if conds else " WHERE ") + \
            "m.id IN (SELECT id FROM matches ORDER BY started DESC LIMIT ?)"
        params.append(args.last)
    return sql, params


FROM = "FROM matches m LEFT JOIN maps mp ON mp.map_key = m.map_key"


# ---------------------------------------------------------------- commands
def cmd_setup(args):
    cfg = load_config()
    cfg["player_name"] = args.name
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Oyuncu adı kaydedildi: {args.name}")


def cmd_import(args):
    me = require_player()
    con = db.connect()
    done = db.imported_versions(con)
    todo = [d for d in session.list_sessions()
            if args.force or done.get(d.name) != analyze.ANALYZER_VERSION]
    if not todo:
        print("Yeni kayıt yok.")
        return
    for i, d in enumerate(todo, 1):
        m = analyze.analyze(session.load(d), me)
        db.save_match(con, m)
        k = sum(l.kills_air + l.kills_ground for l in m.lives)
        dth = sum(1 for l in m.lives if l.end_reason in ("shot_down", "crashed"))
        print(f"[{i}/{len(todo)}] {m.id}  {m.vehicle or '?':<16} sonuç={m.result:<7} "
              f"kill={k} ölüm={dth}" + (f"  tanınmayan satır={len(m.unknown_messages)}" if m.unknown_messages else ""))
    print(f"{len(todo)} maç işlendi -> {db.DB_PATH.name}")


def cmd_stats(args):
    con = db.connect()
    w, p = where_clause(args)
    tot = con.execute(f"""SELECT COUNT(*) n, SUM(result='win') w, SUM(result='loss') l,
        SUM(kills_air) ka, SUM(kills_ground) kg, SUM(deaths) d {FROM}{w}""", p).fetchone()
    if not tot["n"]:
        print("Bu filtreyle maç yok.")
        return
    lv = con.execute(f"""SELECT AVG(l.duration_s) life, AVG(l.max_g) g, AVG(l.avg_alt_m) alt,
        AVG(l.avg_tas_kmh) tas, AVG(l.low_alt_share) low, SUM(l.hits_taken) ht, SUM(l.hits_dealt) hd
        FROM lives l JOIN matches m ON m.id = l.match_id LEFT JOIN maps mp ON mp.map_key = m.map_key{w}""",
                     p).fetchone()
    known = (tot["w"] or 0) + (tot["l"] or 0)
    kills = (tot["ka"] or 0) + (tot["kg"] or 0)
    print("=== Genel ===")
    print(f"Maç: {tot['n']}   Galibiyet: {tot['w'] or 0}   Mağlubiyet: {tot['l'] or 0}   "
          f"Sonuç bilinmiyor: {tot['n'] - known}" +
          (f"   Kazanma oranı: %{100 * (tot['w'] or 0) / known:.0f}" if known else ""))
    kd = f"{kills / tot['d']:.2f}" if tot["d"] else f"{kills}/0"
    print(f"Hava kill: {tot['ka'] or 0}   Yer kill: {tot['kg'] or 0}   Ölüm: {tot['d'] or 0}   K/D: {kd}")
    print(f"Ortalama yaşam süresi: {mmss(lv['life'])}   Ort. irtifa: {fmt(lv['alt'], 0, ' m')}   "
          f"Ort. hız: {fmt(lv['tas'], 0, ' km/h')}   Ort. maks G: {fmt(lv['g'])}")
    print(f"Alçak uçuş (<{analyze.LOW_ALT_M} m) zaman payı: {fmt((lv['low'] or 0) * 100, 0, '%')}   "
          f"Verilen/alınan isabet: {lv['hd'] or 0}/{lv['ht'] or 0}")

    print("\n=== Araç bazında ===")
    rows = con.execute(f"""SELECT m.vehicle, COUNT(*) n, SUM(result='win') w, SUM(kills_air+kills_ground) k,
        SUM(deaths) d {FROM}{w} GROUP BY m.vehicle ORDER BY n DESC""", p).fetchall()
    table([[r["vehicle"], r["n"], r["w"], r["k"], r["d"], fmt(r["k"] / r["d"], 2) if r["d"] else r["k"]]
           for r in rows], ["Araç", "Maç", "Galip", "Kill", "Ölüm", "K/D"])

    print("\n=== Harita bazında ===")
    rows = con.execute(f"""SELECT COALESCE(mp.name, m.map_key) map, COUNT(*) n, SUM(result='win') w,
        SUM(kills_air+kills_ground) k, SUM(deaths) d {FROM}{w} GROUP BY 1 ORDER BY n DESC""", p).fetchall()
    table([[r["map"], r["n"], r["w"], r["k"], r["d"], fmt(r["k"] / r["d"], 2) if r["d"] else r["k"]]
           for r in rows], ["Harita", "Maç", "Galip", "Kill", "Ölüm", "K/D"])

    print("\n=== Ölümler ===")
    rows = con.execute(f"""SELECT l.end_reason r, COUNT(*) n, AVG(l.death_alt_m) alt, AVG(l.death_tas_kmh) tas,
        AVG(l.death_nearest_enemy_km) ne, AVG(l.duration_s) life
        FROM lives l JOIN matches m ON m.id = l.match_id LEFT JOIN maps mp ON mp.map_key = m.map_key{w}
        GROUP BY 1 ORDER BY n DESC""", p).fetchall()
    names = {"shot_down": "düşürüldü", "crashed": "yere çakıldı", "survived": "hayatta kaldı", "left": "çıktı/bilinmiyor"}
    table([[names.get(r["r"], r["r"]), r["n"], mmss(r["life"]), fmt(r["alt"], 0, " m"), fmt(r["tas"], 0, " km/h"),
            fmt(r["ne"], 1, " km")] for r in rows],
          ["Bitiş", "Adet", "Ort. yaşam", "İrtifa*", "Hız*", "En yakın düşman*"])
    print("  * ilk isabet anındaki değerler (en yakın düşman = minimapte görünenler)")

    rows = con.execute(f"""SELECT l.killer_vehicle v, COUNT(*) n
        FROM lives l JOIN matches m ON m.id = l.match_id LEFT JOIN maps mp ON mp.map_key = m.map_key{w}
        {'AND' if w else 'WHERE'} l.killer_vehicle IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 10""", p).fetchall()
    if rows:
        print("\n=== Seni en çok düşüren uçaklar ===")
        table([[r["v"], r["n"]] for r in rows], ["Uçak", "Adet"])
    rows = con.execute(f"""SELECT e.target_vehicle v, COUNT(*) n FROM events e
        JOIN matches m ON m.id = e.match_id LEFT JOIN maps mp ON mp.map_key = m.map_key{w}
        {'AND' if w else 'WHERE'} e.me_actor = 1 AND e.kind IN ('kill','destroy') AND e.target_vehicle IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 10""", p).fetchall()
    if rows:
        print("\n=== En çok düşürdüğün uçaklar ===")
        table([[r["v"], r["n"]] for r in rows], ["Uçak", "Adet"])


def cmd_matches(args):
    con = db.connect()
    w, p = where_clause(args)
    rows = con.execute(f"""SELECT m.*, COALESCE(mp.name, m.map_key) map_name {FROM}{w}
        ORDER BY m.started DESC""", p).fetchall()
    table([[r["id"], r["vehicle"], r["map_name"], r["result"], mmss(r["duration_s"]),
            r["kills_air"] + r["kills_ground"], r["deaths"]] for r in rows],
          ["Maç", "Araç", "Harita", "Sonuç", "Süre", "Kill", "Ölüm"])


def cmd_match(args):
    con = db.connect()
    m = con.execute(f"SELECT m.*, mp.name map_name {FROM} WHERE m.id LIKE ? ORDER BY m.started DESC",
                    (f"%{args.id}%",)).fetchone()
    if not m:
        sys.exit("Maç bulunamadı.")
    print(f"=== {m['id']}  {m['vehicle']}  {m['result']}  süre {mmss(m['duration_s'])} ===")
    print(f"Harita: {m['map_name'] or m['map_key']} ({fmt(m['map_size_km'], 0, ' km')})")
    for o in json.loads(m["objectives"] or "[]"):
        print(f"  görev: {o}")
    for l in con.execute("SELECT * FROM lives WHERE match_id = ? ORDER BY idx", (m["id"],)):
        print(f"\nYaşam {l['idx'] + 1}: {l['vehicle']}  {mmss(l['spawn_t'])} -> {mmss(l['end_t'])} "
              f"({mmss(l['duration_s'])})  bitiş: {l['end_reason']}")
        print(f"  kill hava/yer: {l['kills_air']}/{l['kills_ground']}  isabet verilen/alınan: "
              f"{l['hits_dealt']}/{l['hits_taken']}  mesafe: {fmt(l['distance_km'], 0, ' km')}")
        print(f"  ort. irtifa {fmt(l['avg_alt_m'], 0, ' m')}  ort. hız {fmt(l['avg_tas_kmh'], 0, ' km/h')}  "
              f"maks Mach {fmt(l['max_mach'], 2)}  G {fmt(l['min_g'])}..{fmt(l['max_g'])}  "
              f"alçak uçuş %{fmt((l['low_alt_share'] or 0) * 100, 0)}")
        if l["killer"]:
            print(f"  düşüren: {l['killer']} ({l['killer_vehicle']})")
        if l["first_hit_t"] is not None:
            print(f"  ilk isabet anı {mmss(l['first_hit_t'])}: irtifa {fmt(l['death_alt_m'], 0, ' m')}, "
                  f"hız {fmt(l['death_tas_kmh'], 0, ' km/h')}, Mach {fmt(l['death_mach'], 2)}, "
                  f"G {fmt(l['death_g'])}, en yakın görünen düşman {fmt(l['death_nearest_enemy_km'], 1, ' km')}, "
                  f"20 km içinde {fmt(l['death_enemies_within_20km'])} düşman")
    print("\nSeninle ilgili olaylar:")
    for e in con.execute("""SELECT * FROM events WHERE match_id = ? AND (me_actor = 1 OR me_target = 1)
                            ORDER BY t""", (m["id"],)):
        print(f"  {mmss(e['t'])}  {e['raw']}")


def cmd_maps(args):
    con = db.connect()
    rows = con.execute("""SELECT mp.map_key, mp.name, COUNT(m.id) n, MAX(m.objectives) obj
        FROM maps mp LEFT JOIN matches m ON m.map_key = mp.map_key GROUP BY mp.map_key ORDER BY n DESC""").fetchall()
    for r in rows:
        objs = json.loads(r["obj"] or "[]")
        print(f"{r['map_key']}  ad={r['name'] or '(isimsiz)'}  maç={r['n']}")
        for o in objs[:4]:
            print(f"    görev: {o}")
    print("\nİsim vermek için:  python -m blackbox name-map <anahtar> \"Harita adı\"")


def cmd_name_map(args):
    con = db.connect()
    with con:
        cur = con.execute("UPDATE maps SET name = ? WHERE map_key LIKE ?", (args.name, f"%{args.key}%"))
    print(f"{cur.rowcount} harita güncellendi.")


def cmd_unknown(args):
    con = db.connect()
    rows = con.execute("SELECT raw, COUNT(*) n FROM events WHERE kind = 'other' GROUP BY raw ORDER BY n DESC")
    rows = rows.fetchall()
    if not rows:
        print("Tanınmayan satır yok.")
    for r in rows:
        print(f"{r['n']:>4}  {r['raw']}")


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap =argparse.ArgumentParser(prog="python -m blackbox", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(sp):
        sp.add_argument("--vehicle")
        sp.add_argument("--map")
        sp.add_argument("--last", type=int)
        sp.add_argument("--since")

    sp = sub.add_parser("setup"); sp.add_argument("name"); sp.set_defaults(f=cmd_setup)
    sp = sub.add_parser("import"); sp.add_argument("--force", action="store_true"); sp.set_defaults(f=cmd_import)
    sp = sub.add_parser("stats"); filters(sp); sp.set_defaults(f=cmd_stats)
    sp = sub.add_parser("matches"); filters(sp); sp.set_defaults(f=cmd_matches)
    sp = sub.add_parser("match"); sp.add_argument("id"); sp.set_defaults(f=cmd_match)
    sp = sub.add_parser("maps"); sp.set_defaults(f=cmd_maps)
    sp = sub.add_parser("name-map"); sp.add_argument("key"); sp.add_argument("name"); sp.set_defaults(f=cmd_name_map)
    sp = sub.add_parser("unknown"); sp.set_defaults(f=cmd_unknown)
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
