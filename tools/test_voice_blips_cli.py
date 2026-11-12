import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_inventory_preserves_the_current_playable_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            previous = b'{"directory":"previous-release","report":"report.json","artifacts":{}}\n'
            (output / 'latest.json').write_bytes(previous)
            result = subprocess.run([sys.executable, str(ROOT / 'tools/voice_blips.py'), 'inventory',
                '--game-set', 'starfox64', '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((output / 'latest.json').read_bytes(), previous)
            inventory = json.loads((output / 'inventory.json').read_text())
            report = json.loads((output / inventory['directory'] / 'report.json').read_text())
            self.assertEqual(report['status_counts']['voiced'], 725)


if __name__ == '__main__':
    unittest.main()
