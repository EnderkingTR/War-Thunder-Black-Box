import unittest

from blackbox import skills


class WeaponClassTest(unittest.TestCase):
    def test_classes(self):
        cases = {
            "us_aim_120c_5_default": "radar", "su_r_77_1": "radar", "cn_pl12a": "radar", "swd_rb99": "radar",
            "su_r_27er": "radar", "r_darter_default": "radar", "us_aim7m_sparrow_f_15": "radar",
            "us_aim9m_sidewinder_default": "ir", "su_r_73e": "ir", "swd_rb74m": "ir", "su_r_27et": "ir",
            "cn_pl8b": "ir", "jp_aam3": "ir",
            "165mm_vt_1": "sam", "170mm_zur_95ya6": "sam", "il_derby_er_sam": "sam", "us_rim_174_sm_6": "sam",
            "30mm_3UBR8": "gun", "ap_i": "gun", "he_frag_i": "gun",
            "us_gbu_39": "other", "120mm_m829a2": "other",
            None: "none",
        }
        for w, cls in cases.items():
            self.assertEqual(skills.weapon_class(w), cls, w)


class VerdictTest(unittest.TestCase):
    def test_radar_notch_is_defended(self):
        self.assertEqual(skills.defense_verdict("radar", {"def_notch": 0.6, "def_max_g": 3})[1], "good")

    def test_radar_hot_and_straight_is_undefended(self):
        style, verdict = skills.defense_verdict("radar", {"def_hot": 0.9, "def_max_g": 2})
        self.assertEqual((style, verdict), ("tehdide doğru", "none"))

    def test_ir_hard_turn_is_defended(self):
        self.assertEqual(skills.defense_verdict("ir", {"def_max_g": 8})[1], "good")


class GroundTest(unittest.TestCase):
    def test_battle_kind(self):
        from blackbox.importer import battle_kind
        self.assertEqual(battle_kind("air_ground_Dom"), "ground")
        self.assertEqual(battle_kind("base_dom"), "air")
        self.assertEqual(battle_kind(None, "Fetih #2"), "ground")
        self.assertEqual(battle_kind(None, "Operasyon"), "air")

    def test_vehicle_group(self):
        self.assertEqual(skills.vehicle_group("tank_destroyer", "120mm_m829a2"), "tank")
        self.assertEqual(skills.vehicle_group("SPAA", "30mm_3UBR8"), "spaa")
        self.assertEqual(skills.vehicle_group("assault", "us_gbu_39"), "air")
        self.assertEqual(skills.vehicle_group("helicopter", "su_9M127"), "heli")
        self.assertEqual(skills.vehicle_group("tank", None), "none")

    def test_ammo(self):
        cases = {"120mm_m829a2": "kinetic", "125mm_3bm46": "kinetic", "120mm_l27a1": "kinetic",
                 "130mm_9m120_1": "atgm", "152mm_tow_2": "atgm", "125mm_3bk_18m": "heat",
                 "152mm_3of25": "he", "30mm_3UBR8": "autocannon"}
        for w, cls in cases.items():
            self.assertEqual(skills.ground_ammo_class(w), cls, w)


class BasesTest(unittest.TestCase):
    def _bases(self, per_match):
        split = {"with": {"n": 5, "rp": 9000, "sl": 18000}, "without": {"n": 5, "rp": 3000, "sl": 4000}}
        return {"n": 10, "bases": round(per_match * 10), "with_bases": 5, "share": 0.5, "per_match": per_match,
                "split": split}

    def test_low_kd_with_bases_is_a_note(self):
        from blackbox.queries import _findings
        lob = {"my_k": 4, "my_d": 10, "l_k": 8, "l_d": 10, "n": 10}
        out = _findings([], None, None, lob, [], {"n": 0}, self._bases(0.9))
        kd = [f for f in out if f["title"].startswith("K/D")]
        self.assertEqual(kd[0]["kind"], "note")
        self.assertTrue(any(f["title"] == "Üs bombalamada güçlüsün" for f in out))
        self.assertTrue(any("grind" in f["title"] for f in out))

    def test_low_kd_without_bases_is_weak(self):
        from blackbox.queries import _findings
        lob = {"my_k": 4, "my_d": 10, "l_k": 8, "l_d": 10, "n": 10}
        out = _findings([], None, None, lob, [], {"n": 0}, None)
        self.assertEqual([f["kind"] for f in out if f["title"].startswith("K/D")], ["weak"])


class QueriesSmokeTest(unittest.TestCase):
    """New grind/map queries run against an empty in-memory schema."""

    def test_queries_on_empty_db(self):
        import sqlite3
        from blackbox import db, queries
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(db.SCHEMA)
        f = {"type": "air"}
        self.assertEqual(queries.maps(con, f), [])
        self.assertEqual(queries.missing_results(con, f), [])
        self.assertEqual(queries.vehicles(con, f), [])
        self.assertIsNone(queries.summary(con, f)["totals"]["rp_min"])
        self.assertEqual(queries.trend(con, f)["points"], [])
        self.assertEqual(queries.ground_vehicles(con, {"type": "ground"}), [])


class ProfileTest(unittest.TestCase):
    def test_db_paths(self):
        from blackbox import db
        self.assertEqual(db.path_for("ENDERKING_tr", True), db.DB_PATH)
        self.assertEqual(db.path_for("Kardeş Adı", False).name, "blackbox-Kardeş_Adı.db")

    def test_multipath_threshold(self):
        self.assertEqual(skills.LOW_RADIO_ALT_M, 60)


class ExportTest(unittest.TestCase):
    DATA = {
        "battle": {"session_id": "abc", "map": "Afganistan", "started": "2026-11-22T12:20:00", "mode": "Operasyon",
                   "result": "win", "kills": 2, "deaths": 0, "end_s": 915, "vehicle_name": "F/A-18C Late"},
        "kills": [{"ms": 284000, "me_killer": 1, "me_victim": 0, "killer_idx": 0, "killer_name": "ENDERKING_tr",
                   "victim_name": "Ghost", "victim_vehicle_name": "MiG-29", "weapon_name": "AIM-120C-5",
                   "destroyed_weapon": None}],
        "players": [{"idx": 0, "team": 2, "name": "ENDERKING_tr", "is_me": 1, "kills": 2, "score": 1833},
                    {"idx": 1, "team": 1, "name": "Ghost", "is_me": 0, "kills": 0, "score": 118}],
        "result": {"categories": {"Yok edilen üsler": {"count": 2, "sl": 3952, "rp": 1428}},
                   "repair_sl": None, "total_sl": 55107, "total_rp": 32463},
        "result_items": [], "lives": [],
    }

    def test_filename(self):
        from blackbox import export
        self.assertEqual(export.filename(self.DATA, "pdf"), "BlackBox_Afganistan_20261122_1220.pdf")
        self.assertEqual(export._slug("Güneydoğu Şehri"), "Guneydogu-Sehri")

    def test_csv(self):
        from blackbox import export
        text = export.to_csv(self.DATA).decode("utf-8")
        self.assertTrue(text.startswith("﻿BlackBox"))
        self.assertIn("Sonuç;Zafer", text)
        self.assertIn("4:44;Kill;Ghost;MiG-29;AIM-120C-5", text)
        self.assertIn("Yok edilen üsler;2;3952;1428", text)
        self.assertLess(text.index("Senin takımın"), text.index("Rakip takım"))

    def test_json(self):
        import json
        from blackbox import export
        d = json.loads(export.to_json(self.DATA, {"series": [[0, 1000, 500, 0.4, 1]], "track": [], "events": []}))
        self.assertEqual(d["format"], "blackbox-match")
        self.assertEqual(d["battle"]["map"], "Afganistan")
        self.assertEqual(d["telemetry"]["series_columns"][1], "alt_m")

    def test_png_to_pdf(self):
        import struct
        import zlib
        from blackbox import export
        w, h = 3, 2
        raw = b"".join(b"\x00" + bytes([200, 10, 10]) * w for _ in range(h))
        chunk = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        pdf = export.png_to_pdf(png, "BlackBox - Afganistan")
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Width 3 /Height 2", pdf)
        self.assertIn(b"/Predictor 15 /Colors 3", pdf)
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        xref = int(pdf.rsplit(b"startxref", 1)[1].split()[0])
        self.assertTrue(pdf[xref:].startswith(b"xref"))


if __name__ == "__main__":
    unittest.main()
