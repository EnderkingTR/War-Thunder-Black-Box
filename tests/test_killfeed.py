import unittest

from blackbox.killfeed import parse, split_player


class KillfeedTest(unittest.TestCase):
    def test_kill_with_tags(self):
        e = parse("^yshTR^ ENDERKING_tr (F/A-18C Late) düşürdü: -TCRM- YouSeeYouMother (MiG-35)")
        self.assertEqual((e.kind, e.actor, e.actor_squad, e.actor_vehicle), ("kill", "ENDERKING_tr", "yshTR", "F/A-18C Late"))
        self.assertEqual((e.target, e.target_squad, e.target_vehicle), ("YouSeeYouMother", "TCRM", "MiG-35"))

    def test_crit_with_symbols(self):
        e = parse("[MDRN] ⋇JETPLANERR (␗Su-30MKK) kritik hasar verdi ^yshTR^ ENDERKING_tr (F/A-18C Late)")
        self.assertEqual((e.kind, e.actor, e.actor_vehicle, e.target), ("crit", "JETPLANERR", "Su-30MKK", "ENDERKING_tr"))

    def test_name_with_spaces(self):
        e = parse("=MXS2= x (F-2000A) ağır hasar verdi ╊REBOT╋ игрок в самолёт (◌F/A-18C Late)")
        self.assertEqual((e.kind, e.target, e.target_squad, e.target_vehicle),
                         ("severe", "игрок в самолёт", "REBOT", "F/A-18C Late"))

    def test_weapon_destroyed(self):
        e = parse("windows_xP (F/A-18E) imha etti: weapons/us_aim_120c_5/short")
        self.assertEqual((e.kind, e.actor, e.extra), ("destroy_weapon", "windows_xP", "weapons/us_aim_120c_5/short"))

    def test_one_party(self):
        self.assertEqual(parse("-WTN- ⋇A102925 (▄AF/A-18A) yere çakıldı.").kind, "crash")
        self.assertEqual(parse("-WTN- ⋇A102925 (▄AF/A-18A) yere çakıldı.").actor, "A102925")
        self.assertEqual(parse("windows_xP (F/A-18E) son vuruşu yaptı!").kind, "final_blow")
        self.assertEqual(parse("=NOVRA= 籽铃 (◄EF-2000) ilk darbeyi vurdu!").kind, "first_strike")
        a = parse('=MXS2= abc (F-2000A) , "Çifte darbe!" başarımını kazandı')
        self.assertEqual((a.kind, a.actor, a.extra), ("achievement", "abc", "Çifte darbe!"))
        self.assertEqual(parse("[SEMYA] separat0r oyundan çıktı.").actor, "separat0r")
        self.assertEqual(parse("separat0rtd! kd?NET_PLAYER_DISCONNECT_FROM_GAME").kind, "noise")

    def test_unknown(self):
        self.assertEqual(parse("something completely new").kind, "other")

    def test_split_player(self):
        self.assertEqual(split_player("=NeGF= 久淋"), ("久淋", "NeGF"))
        self.assertEqual(split_player("超级无敌战雷大王"), ("超级无敌战雷大王", None))


if __name__ == "__main__":
    unittest.main()
