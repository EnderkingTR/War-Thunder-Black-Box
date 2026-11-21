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


if __name__ == "__main__":
    unittest.main()
