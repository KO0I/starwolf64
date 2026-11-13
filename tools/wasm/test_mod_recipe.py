import copy
import unittest
from mod_recipe import create, apply


class ModRecipeTests(unittest.TestCase):
    def setUp(self):
        self.base = {"changed": b"original resource bytes", "shared": b"unchanged texture", "short": b"longer old data"}
        self.chatter = b"CHT2-owned-audio"
        self.target = {"changed": b"modified resource bytes added", "alias": self.base["shared"],
                       "short": b"short", "new/model": b"custom model", "empty": b"",
                       "audio/crew_chatter": bytes(68) + self.chatter}

    def test_round_trip_exact_contents_and_repeatability(self):
        recipe, literals = create(self.base, self.target, self.chatter)
        self.assertEqual(apply(recipe, literals, self.base, self.chatter), self.target)
        self.assertEqual(create(self.base, self.target, self.chatter), (recipe, literals))
        alias = next(e for e in recipe["entries"] if e["path"] == "alias")
        self.assertEqual(alias["source"]["path"], "shared")
        self.assertEqual(alias["writes"], [])
        self.assertNotIn(self.chatter, literals)

    def test_wrong_source_and_corrupt_patch_are_rejected(self):
        recipe, literals = create(self.base, self.target, self.chatter)
        with self.assertRaises(ValueError):
            apply(recipe, literals, {**self.base, "shared": b"wrong"}, self.chatter)
        with self.assertRaises(ValueError):
            apply(recipe, literals + b"wrong", self.base, self.chatter)
        damaged = copy.deepcopy(recipe)
        damaged["entries"][0]["writes"] = [[1000000, 0, 100]]
        with self.assertRaises(ValueError):
            apply(damaged, literals, self.base, self.chatter)


if __name__ == "__main__":
    unittest.main()
