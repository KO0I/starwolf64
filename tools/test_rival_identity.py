import unittest

from wolf_dialogue import replace_pilot_names


class RivalIdentityTests(unittest.TestCase):
    def test_rivals_and_friendly_crew_are_swapped_once(self):
        self.assertEqual(
            replace_pilot_names("Fox and Wolf; Falco and Leon; Peppy and Pigma; Slippy and Andrew."),
            "Wolf and Fox; Panther and Falco; Krystal and Peppy; Kami and Slippy.")

    def test_full_names_survive_original_radio_line_breaks(self):
        self.assertEqual(replace_pilot_names("Fox\nMcCloud meets Wolf O'Donnell."),
                         "Wolf O'Donnell meets Fox McCloud.")
        self.assertEqual(replace_pilot_names("Falco  Lombardi, Peppy\nHare and Slippy Toad"),
                         "Panther Caroso, Krystal and Kami")

    def test_real_rival_taunts_address_the_new_player_team(self):
        self.assertEqual(replace_pilot_names("Can't let you do\nthat, Star Fox!"),
                         "Can't let you do\nthat, Star Wolf!")
        self.assertEqual(replace_pilot_names("Peppy! Long time\nno see!"),
                         "Krystal! Long time\nno see!")

    def test_pilot_names_do_not_change_ship_or_larger_words(self):
        self.assertEqual(replace_pilot_names("Wolfen Foxglove leonine"),
                         "Wolfen Foxglove leonine")


if __name__ == "__main__":
    unittest.main()
