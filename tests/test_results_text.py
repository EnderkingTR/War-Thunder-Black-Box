import unittest

from blackbox import names
from blackbox.results_text import parse_text

SAMPLE = """[Operasyon] İspanya görevinde zafer!

Yok edilen uçaklar          1    10112 SL    1197 RP
    2:44    F/A-18C Late    AIM-120C-5    Su-27SM     450 görev puanı    — (tam ödül)    4494 + (PA)2247 + (Takviye)3371 = 10112 SL    299 + (PA)599 + (Tılsımlar)299 = 1197 RP

Oynanan Süre             2:28                2625 RP
    F/A-18C Late    69%    2:28    656 + (PA)1313 + (Tılsımlar)656 = 2625 RP

Kazanma ödülü                     6617 SL

Kazanılan: 20784 SL, 4109 CRP
Faaliyet: 69%
Bütün araçların otomatik tamiri: -3169 SL

Araştırılan birim:
F-15E: 4109 RP

Oturum: 72c412c10016d34a
Toplam: 17615 SL, 4109 CRP, 4109 RP

[Harekat] Danimarka görevinde yenilgi!

Yok edilen üsler           1    1976 SL     688 RP
    2:37    F/A-18C Late    Mk 77    26 kg    25900 hasar    83 görev puanı    1317 + (PA)659 = 1976 SL    172 + (PA)344 + (Tılsımlar)172 = 688 RP

Kazanılan: 9705 SL, 4953 CRP
Oturum: 72c412c10016eb58
Toplam: 6514 SL, 4953 CRP, 4953 RP
"""


class ResultsTextTest(unittest.TestCase):
    def test_two_battles(self):
        a, b = parse_text(SAMPLE)
        self.assertEqual((a.session_id, a.mode, a.map_name, a.result), ("72c412c10016d34a", "Operasyon", "İspanya", "win"))
        self.assertEqual((a.total_sl, a.total_rp, a.repair_sl, a.activity, a.played_s), (17615, 4109, -3169, 69, 148))
        self.assertEqual(a.research_vehicle, "F-15E")
        kill = a.items[0]
        self.assertEqual((kill.time_s, kill.vehicle, kill.weapon, kill.target, kill.sl, kill.rp),
                         (164, "F/A-18C Late", "AIM-120C-5", "Su-27SM", 10112, 1197))
        self.assertNotIn("F-15E: 4109 RP", a.categories)
        self.assertEqual((b.map_name, b.result), ("Danimarka", "loss"))
        self.assertEqual((b.items[0].weapon, b.items[0].target), ("Mk 77", None))


class NamesTest(unittest.TestCase):
    def test_weapons(self):
        cases = {"us_aim_120c_5_default": "AIM-120C-5", "su_r_77_1": "R-77-1", "cn_pl12a": "PL-12A",
                 "us_aim9m_sidewinder_default": "AIM-9M", "swd_rb99": "RB 99",
                 "us_aim_120c_5_default_switzerland": "AIM-120C-5"}
        for raw, want in cases.items():
            self.assertEqual(names.weapon(raw), want)
        self.assertTrue(names.weapon("he_frag_i").startswith("Top/mermi"))

    def test_map(self):
        self.assertEqual(names.map_name("air_grand_canyon"), "Grand Canyon")


if __name__ == "__main__":
    unittest.main()
