"""War Thunder BlackBox - komut satırı.

    python -m blackbox setup ENDERKING_tr       oyuncu adını kaydet
    python -m blackbox import [--force]         telemetri + replay + sonuç metinlerini işle
    python -m blackbox add-results <dosya>      kopyalanmış sonuç metinlerini içeren dosyayı ekle
    python -m blackbox stats [filtreler]        genel istatistikler
    python -m blackbox battles [filtreler]      maç listesi
    python -m blackbox battle <oturum|tarih>    tek maçın detayı
    python -m blackbox maps                     haritalar ve isimleri
    python -m blackbox name-map <map_id> <ad>   bir haritaya isim ver
    python -m blackbox unknown                  tanınmayan kill feed satırları
    python -m blackbox web                      web arayüzünü aç (http://127.0.0.1:8765)

Filtreler: --vehicle fa_18c  --map İspanya  --last 20  --since 2026-11-01  --type air|ground|all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, importer
from .names import weapon as wname
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
        return f"{v:,.{digits}f}{suffix}".replace(",", ".") if digits == 0 else f"{v:.{digits}f}{suffix}"
    return f"{v}{suffix}"


def num(v):
    return "-" if v is None else f"{int(round(v)):,}".replace(",", ".")


def mmss(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def pct(a, b):
    return f"%{100 * a / b:.0f}" if b else "-"


def ratio(k, d):
    if k is None:
        return "-"
    return f"{k / d:.2f}" if d else f"{k}/0"


def table(rows, headers, indent="  "):
    rows = [[("-" if c is None else str(c)) for c in r] for r in rows]
    if not rows:
        print(indent + "(veri yok)")
        return
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print(indent + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print(indent + "  ".join("-" * w for w in widths))
    for r in rows:
        print(indent + "  ".join(c.ljust(w) for c, w in zip(r, widths)))


def where(args, alias="b"):
    conds, params = [], []
    kind = getattr(args, "type", "air")
    if kind in ("air", "ground"):
        conds.append(f"{alias}.kind = ?")
        params.append(kind)
    if getattr(args, "vehicle", None):
        conds.append(f"{alias}.vehicle LIKE ?")
        params.append(f"%{args.vehicle}%")
    if getattr(args, "map", None):
        conds.append(f"({alias}.map LIKE ? OR {alias}.map_id LIKE ?)")
        params += [f"%{args.map}%", f"%{args.map}%"]
    if getattr(args, "since", None):
        conds.append(f"{alias}.started >= ?")
        params.append(args.since)
    if getattr(args, "last", None):
        conds.append(f"{alias}.session_id IN (SELECT session_id FROM battles ORDER BY started DESC LIMIT ?)")
        params.append(args.last)
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def section(title):
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------- commands
def cmd_setup(args):
    cfg = load_config()
    cfg["player_name"] = args.name
    if args.replay_dir:
        cfg["replay_dir"] = args.replay_dir
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Kaydedildi: {cfg}")


def cmd_import(args):
    me = require_player()
    replay_dir = Path(load_config().get("replay_dir") or importer.DEFAULT_REPLAY_DIR)
    print("İçe aktarılıyor...")
    out = importer.run_import(me, replay_dir, args.force)
    print(f"Telemetri: {out['telemetry']} yeni   Replay: {out['replays']} yeni   "
          f"Sonuç metni: {out['results']} yeni   Toplam maç: {out['battles']}")


def cmd_add_results(args):
    n = importer.add_results_file(Path(args.file))
    print(f"{n} yeni sonuç eklendi -> {importer.RESULTS_DIR}. Şimdi: python -m blackbox import")


def cmd_stats(args):
    con = db.connect()
    w, p = where(args)
    B = f"FROM battles b{w}"
    t = con.execute(f"""SELECT COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(ground_kills) gk, SUM(deaths) d, SUM(assists) a, AVG(score) sc, SUM(missile_evades) me,
        AVG(1.0 * (lobby_pos - 1) / (n_players - 1)) lp, SUM(has_replay) hr {B}""", p).fetchone()
    if not t["n"]:
        print("Bu filtreyle maç yok. Önce: python -m blackbox import")
        return
    known = (t["w"] or 0) + (t["l"] or 0)
    section("Genel")
    print(f"  Maç: {t['n']}  (replay: {t['hr'] or 0})   Galibiyet: {t['w'] or 0}   Mağlubiyet: {t['l'] or 0}   "
          f"Sonucu bilinmeyen: {t['n'] - known}   Kazanma oranı: {pct(t['w'] or 0, known)}")
    print(f"  Kill: {t['k'] or 0}   (yer hedefi: {t['gk'] or 0})   Ölüm: {t['d'] or 0}   K/D: {ratio(t['k'] or 0, t['d'])}"
          f"   Asist: {t['a'] or 0}")
    lobby = f"%{100 * t['lp']:.0f} (0 = lobinin en iyisi, 100 = en kötüsü)" if t["lp"] is not None else "-"
    print(f"  Ortalama skor: {num(t['sc'])}   Füzeden kaçış: {t['me'] or 0} "
          f"(maç başı {fmt((t['me'] or 0) / t['n'], 1)})   Ortalama lobi dilimi: {lobby}")

    # ---- lobby comparison
    section("Lobiyle kıyas (aynı maçlardaki oyuncular)")
    bw = w + (" AND" if w else " WHERE") + " b.has_replay = 1"
    lob = con.execute(f"""
        WITH bs AS (SELECT session_id FROM battles b{bw})
        SELECT
          AVG(CASE WHEN rp.is_me = 1 THEN rp.score END) my_score,
          AVG(CASE WHEN rp.is_me = 0 THEN rp.score END) lobby_score,
          SUM(CASE WHEN rp.is_me = 1 THEN rp.kills END) my_k, SUM(CASE WHEN rp.is_me = 1 THEN rp.deaths END) my_d,
          SUM(CASE WHEN rp.is_me = 0 THEN rp.kills END) l_k, SUM(CASE WHEN rp.is_me = 0 THEN rp.deaths END) l_d,
          AVG(CASE WHEN rp.is_me = 1 THEN rp.missile_evades END) my_ev,
          AVG(CASE WHEN rp.is_me = 0 THEN rp.missile_evades END) l_ev
        FROM replay_players rp JOIN bs ON bs.session_id = rp.session_id""", p).fetchone()
    top = con.execute(f"""
        WITH bs AS (SELECT session_id FROM battles b{bw}),
        ranked AS (SELECT rp.*, ROW_NUMBER() OVER (PARTITION BY rp.session_id ORDER BY rp.score DESC) rn
                   FROM replay_players rp JOIN bs ON bs.session_id = rp.session_id)
        SELECT AVG(score) sc, SUM(kills) k, SUM(deaths) d, AVG(missile_evades) ev FROM ranked WHERE rn <= 3""",
                      p).fetchone()
    table([["Sen", num(lob["my_score"]), ratio(lob["my_k"], lob["my_d"]), fmt(lob["my_ev"], 2)],
           ["Lobi ortalaması", num(lob["lobby_score"]), ratio(lob["l_k"], lob["l_d"]), fmt(lob["l_ev"], 2)],
           ["Her maçın ilk 3'ü", num(top["sc"]), ratio(top["k"], top["d"]), fmt(top["ev"], 2)]],
          ["", "Ort. skor", "K/D", "Füzeden kaçış/maç"])

    # ---- grind
    g = con.execute(f"""SELECT COUNT(*) n, AVG(total_sl) sl, AVG(total_rp) rp, AVG(repair_sl) rep,
        SUM(total_sl) ssl, SUM(total_rp) srp, SUM(played_s) ps, AVG(activity) act
        {B}{' AND' if w else ' WHERE'} b.has_result = 1""", p).fetchone()
    section(f"Grind (sonuç metni olan {g['n']} maç)")
    if g["n"]:
        mins = (g["ps"] or 0) / 60
        print(f"  Maç başı net SL: {num(g['sl'])}   Maç başı RP: {num(g['rp'])}   Ort. tamir: {num(g['rep'])} SL"
              f"   Ort. aktivite: %{fmt(g['act'], 0)}")
        print(f"  Toplam: {num(g['ssl'])} SL, {num(g['srp'])} RP" +
              (f"   Oynanan dakika başı: {num(g['ssl'] / mins)} SL, {num(g['srp'] / mins)} RP" if mins else ""))
        for res, label in (("win", "Galibiyette"), ("loss", "Mağlubiyette")):
            r = con.execute(f"""SELECT COUNT(*) n, AVG(total_sl) sl, AVG(total_rp) rp {B}
                {' AND' if w else ' WHERE'} b.has_result = 1 AND b.result = ?""", p + [res]).fetchone()
            if r["n"]:
                print(f"  {label} ({r['n']}): {num(r['sl'])} SL, {num(r['rp'])} RP")
    else:
        print("  Sonuç metni yok. Hangarda savaş sonucu bildirimini kopyala; recorder açıksa otomatik kaydedilir.")

    # ---- per vehicle / map
    section("Araç bazında")
    rows = con.execute(f"""SELECT vehicle, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(deaths) d, AVG(score) sc, AVG(total_rp) rp, AVG(total_sl) sl {B} GROUP BY vehicle ORDER BY n DESC""",
                       p).fetchall()
    table([[r["vehicle"], r["n"], pct(r["w"] or 0, (r["w"] or 0) + (r["l"] or 0)), r["k"], r["d"],
            ratio(r["k"], r["d"]), num(r["sc"]), num(r["rp"]), num(r["sl"])] for r in rows],
          ["Araç", "Maç", "Kazanma", "Kill", "Ölüm", "K/D", "Ort. skor", "RP/maç", "SL/maç"])

    section("Harita bazında")
    rows = con.execute(f"""SELECT map, COUNT(*) n, SUM(result='win') w, SUM(result='loss') l, SUM(kills) k,
        SUM(deaths) d, AVG(score) sc, AVG(1.0 * (lobby_pos - 1) / (n_players - 1)) lp
        {B} GROUP BY map ORDER BY n DESC""", p).fetchall()
    table([[r["map"], r["n"], pct(r["w"] or 0, (r["w"] or 0) + (r["l"] or 0)), r["k"], r["d"],
            ratio(r["k"], r["d"]), num(r["sc"]), f"%{100 * r['lp']:.0f}" if r["lp"] is not None else "-"]
           for r in rows], ["Harita", "Maç", "Kazanma", "Kill", "Ölüm", "K/D", "Ort. skor", "Lobi dilimi"])

    # ---- weapons
    K = f"FROM replay_kills k JOIN battles b ON b.session_id = k.session_id{w}{' AND' if w else ' WHERE'}"
    section("Kill'lerin, silaha göre (oyuncular + AI hedefler)")
    rows = con.execute(f"SELECT weapon, COUNT(*) n {K} k.me_killer = 1 AND k.destroyed_weapon IS NULL "
                       "GROUP BY weapon", p).fetchall()
    _weapon_table(rows)
    section("Ölümlerin (seni vuran silah)")
    rows = con.execute(f"SELECT weapon, COUNT(*) n {K} k.me_victim = 1 GROUP BY weapon", p).fetchall()
    _weapon_table(rows)
    section("Seni en çok düşüren uçaklar")
    rows = con.execute(f"""SELECT killer_vehicle v, COUNT(*) n {K} k.me_victim = 1
        GROUP BY v ORDER BY n DESC LIMIT 10""", p).fetchall()
    table([[r["v"] or "(kaza / bilinmiyor)", r["n"]] for r in rows], ["Uçak", "Adet"])
    section("En çok düşürdüğün uçaklar")
    rows = con.execute(f"""SELECT victim_vehicle v, COUNT(*) n {K} k.me_killer = 1 AND k.destroyed_weapon IS NULL
        GROUP BY v ORDER BY n DESC LIMIT 10""", p).fetchall()
    table([[r["v"] or "(AI hedef / bilinmiyor)", r["n"]] for r in rows], ["Hedef", "Adet"])

    # ---- when do I die
    rows = con.execute(f"SELECT k.ms {K} k.me_victim = 1", p).fetchall()
    if rows:
        section("Ölüm zamanı (maç başından itibaren)")
        buckets = {"0-2 dk": 0, "2-3 dk": 0, "3-4 dk": 0, "4-6 dk": 0, "6+ dk": 0}
        for r in rows:
            m = r["ms"] / 60000
            key = "0-2 dk" if m < 2 else "2-3 dk" if m < 3 else "3-4 dk" if m < 4 else "4-6 dk" if m < 6 else "6+ dk"
            buckets[key] += 1
        table([[k, v, "#" * v] for k, v in buckets.items()], ["Zaman", "Ölüm", ""])

    # ---- telemetry
    tel = con.execute(f"""SELECT COUNT(*) n, AVG(l.death_alt_m) alt, AVG(l.death_tas_kmh) tas,
        AVG(l.death_nearest_enemy_km) ne, AVG(l.avg_alt_m) aalt, AVG(l.avg_tas_kmh) atas, AVG(l.max_g) g,
        AVG(l.low_alt_share) low
        FROM lives l JOIN battles b ON b.match_id = l.match_id{w}""", p).fetchone()
    if tel["n"]:
        section(f"Uçuş verisi (telemetrisi olan {tel['n']} yaşam)")
        print(f"  Ort. irtifa {fmt(tel['aalt'], 0, ' m')}   Ort. hız {fmt(tel['atas'], 0, ' km/h')}   "
              f"Ort. maks G {fmt(tel['g'])}   300 m altında geçen zaman %{fmt((tel['low'] or 0) * 100, 0)}")
        print(f"  İlk isabet anında: irtifa {fmt(tel['alt'], 0, ' m')}, hız {fmt(tel['tas'], 0, ' km/h')}, "
              f"minimapte görünen en yakın düşman {fmt(tel['ne'], 1, ' km')}")


def _weapon_table(rows):
    agg = {}
    for r in rows:
        name = wname(r["weapon"]) if r["weapon"] else "(silahsız: kaza/manevra kill'i)"
        agg[name] = agg.get(name, 0) + r["n"]
    total = sum(agg.values())
    table([[k, v, pct(v, total)] for k, v in sorted(agg.items(), key=lambda x: -x[1])], ["Silah", "Adet", "Pay"])


def cmd_battles(args):
    con = db.connect()
    w, p = where(args)
    rows = con.execute(f"SELECT * FROM battles b{w} ORDER BY started DESC", p).fetchall()
    res = {"win": "zafer", "loss": "yenilgi"}
    table([[r["session_id"], (r["started"] or "")[:16].replace("T", " "), r["map"], r["vehicle"],
            res.get(r["result"], "?"), r["kills"], r["deaths"], r["score"],
            f"{r['lobby_pos']}/{r['n_players']}" if r["lobby_pos"] else "-", num(r["total_sl"]), num(r["total_rp"]),
            ("R" if r["has_replay"] else "-") + ("S" if r["has_result"] else "-") + ("T" if r["has_telemetry"] else "-")]
           for r in rows],
          ["Oturum", "Tarih", "Harita", "Araç", "Sonuç", "K", "Ö", "Skor", "Lobi", "SL", "RP", "Veri"])
    print("  Veri: R = replay, S = sonuç metni, T = telemetri")


def cmd_battle(args):
    con = db.connect()
    b = con.execute("SELECT * FROM battles WHERE session_id LIKE ? OR started LIKE ? OR match_id LIKE ? "
                    "ORDER BY started DESC", (f"%{args.id}%",) * 3).fetchone()
    if not b:
        sys.exit("Maç bulunamadı.")
    sid = b["session_id"]
    res = {"win": "ZAFER", "loss": "YENİLGİ"}.get(b["result"], "sonuç bilinmiyor")
    print(f"=== {b['map']}  {b['mode'] or b['battle_class'] or ''}  {res} ===")
    print(f"Oturum {sid}   {(b['started'] or '')[:16].replace('T', ' ')}   Araç: {b['vehicle']}   "
          f"Süre: {mmss(b['end_s'])}")
    print(f"Kill {b['kills']}  Ölüm {b['deaths']}  Asist {b['assists']}  Skor {b['score']}  "
          f"Füzeden kaçış {b['missile_evades']}  Lobi sırası {b['lobby_pos']}/{b['n_players']}  "
          f"Takım sırası {b['team_pos']}")
    if b["has_result"]:
        print(f"Kazanç: {num(b['total_sl'])} SL net (tamir {num(b['repair_sl'])}), {num(b['total_rp'])} RP, "
              f"aktivite %{b['activity']}")

    kills = con.execute("SELECT * FROM replay_kills WHERE session_id = ? AND (me_killer = 1 OR me_victim = 1) "
                        "ORDER BY ms", (sid,)).fetchall()
    if kills:
        print("\nSeninle ilgili:")
        for k in kills:
            if k["me_killer"]:
                what = f"vurdu: {wname(k['destroyed_weapon'])} füzesi" if k["destroyed_weapon"] else \
                    f"düşürdün: {k['victim_name']} ({k['victim_vehicle']})"
                print(f"  {mmss(k['ms'] / 1000)}  {wname(k['weapon']) or '(silahsız)'} ile {what}")
            else:
                print(f"  {mmss(k['ms'] / 1000)}  ÖLDÜN: {k['killer_name'] or '?'} ({k['killer_vehicle']}) "
                      f"{wname(k['weapon']) or ''}")

    if b["match_id"]:
        for l in con.execute("SELECT * FROM lives WHERE match_id = ? ORDER BY idx", (b["match_id"],)):
            print(f"\nUçuş (telemetri): ort. irtifa {fmt(l['avg_alt_m'], 0, ' m')}, ort. hız "
                  f"{fmt(l['avg_tas_kmh'], 0, ' km/h')}, maks Mach {fmt(l['max_mach'], 2)}, "
                  f"G {fmt(l['min_g'])}..{fmt(l['max_g'])}, mesafe {fmt(l['distance_km'], 0, ' km')}")
            if l["first_hit_t"] is not None:
                print(f"  İlk isabet anı: irtifa {fmt(l['death_alt_m'], 0, ' m')}, hız {fmt(l['death_tas_kmh'], 0, ' km/h')}, "
                      f"G {fmt(l['death_g'])}, en yakın görünen düşman {fmt(l['death_nearest_enemy_km'], 1, ' km')}")

    players = con.execute("SELECT * FROM replay_players WHERE session_id = ? ORDER BY team, score DESC",
                          (sid,)).fetchall()
    if players and args.lobby:
        print("\nLobi:")
        table([[("» " if p["is_me"] else "") + (p["name"] or ""), p["team"], p["vehicle"], p["mrank"], p["kills"],
                p["deaths"], p["assists"], p["score"], p["missile_evades"]] for p in players],
              ["Oyuncu", "Takım", "Araç", "Rütbe", "K", "Ö", "A", "Skor", "Kaçış"])
    elif players:
        print("\n(Lobinin tamamı için: --lobby)")


def cmd_maps(args):
    con = db.connect()
    rows = con.execute("""SELECT b.map_id, b.map, COUNT(*) n, mn.source FROM battles b
        LEFT JOIN map_names mn ON mn.map_id = b.map_id GROUP BY b.map_id ORDER BY n DESC""").fetchall()
    table([[r["map_id"], r["map"], r["n"], r["source"] or "otomatik"] for r in rows],
          ["map_id", "İsim", "Maç", "Kaynak"])
    print("\nİsim vermek için:  python -m blackbox name-map <map_id> \"Harita adı\"")


def cmd_name_map(args):
    con = db.connect()
    with con:
        con.execute("INSERT OR REPLACE INTO map_names VALUES (?, ?, 'manual')", (args.map_id, args.name))
    importer.rebuild_battles(con)
    print("Kaydedildi.")


def cmd_web(args):
    from . import web
    me = require_player()
    replay_dir = Path(load_config().get("replay_dir") or importer.DEFAULT_REPLAY_DIR)
    web.serve(me, replay_dir, port=args.port, open_browser=not args.no_browser)


def cmd_unknown(args):
    con = db.connect()
    rows = con.execute("SELECT raw, COUNT(*) n FROM events WHERE kind = 'other' GROUP BY raw ORDER BY n DESC").fetchall()
    if not rows:
        print("Tanınmayan satır yok.")
    for r in rows:
        print(f"{r['n']:>4}  {r['raw']}")


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m blackbox", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(sp):
        sp.add_argument("--vehicle")
        sp.add_argument("--map")
        sp.add_argument("--last", type=int)
        sp.add_argument("--since")
        sp.add_argument("--type", choices=["air", "ground", "all"], default="air",
                        help="hava (varsayılan), kara veya hepsi")

    sp = sub.add_parser("setup"); sp.add_argument("name"); sp.add_argument("--replay-dir"); sp.set_defaults(f=cmd_setup)
    sp = sub.add_parser("import"); sp.add_argument("--force", action="store_true"); sp.set_defaults(f=cmd_import)
    sp = sub.add_parser("add-results"); sp.add_argument("file"); sp.set_defaults(f=cmd_add_results)
    sp = sub.add_parser("stats"); filters(sp); sp.set_defaults(f=cmd_stats)
    sp = sub.add_parser("battles"); filters(sp); sp.set_defaults(f=cmd_battles)
    sp = sub.add_parser("battle"); sp.add_argument("id"); sp.add_argument("--lobby", action="store_true")
    sp.set_defaults(f=cmd_battle)
    sp = sub.add_parser("maps"); sp.set_defaults(f=cmd_maps)
    sp = sub.add_parser("name-map"); sp.add_argument("map_id"); sp.add_argument("name"); sp.set_defaults(f=cmd_name_map)
    sp = sub.add_parser("unknown"); sp.set_defaults(f=cmd_unknown)
    sp = sub.add_parser("web"); sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-browser", action="store_true"); sp.set_defaults(f=cmd_web)
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
