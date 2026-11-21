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


if __name__ == "__main__":
    unittest.main()
