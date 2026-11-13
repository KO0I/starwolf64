from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import unittest
from unittest.mock import patch
from run import canonical_diff


class SourcePinTests(unittest.TestCase):
    def test_git_hash_abbreviation_and_color_do_not_change_pins(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root)
            git("init", "-q")
            (root / "source.txt").write_text("original source\n")
            git("add", "source.txt")
            git("-c", "user.name=Pin test", "-c", "user.email=pins@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "initial")
            (root / "source.txt").write_text("modified source\n")
            self.assertNotEqual(git("diff", "--abbrev=7", "HEAD"), git("diff", "--abbrev=20", "HEAD"))
            expected = canonical_diff(root)
            for length in (7, 8, 20):
                with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.abbrev",
                    "GIT_CONFIG_VALUE_0": str(length), "GIT_CONFIG_KEY_1": "color.ui", "GIT_CONFIG_VALUE_1": "always"}):
                    self.assertEqual(canonical_diff(root), expected)
            index = next(line for line in expected.decode().splitlines() if line.startswith("index "))
            old, new = index.split()[1].split("..")
            self.assertEqual((len(old), len(new)), (40, 40))


if __name__ == "__main__":
    unittest.main()
