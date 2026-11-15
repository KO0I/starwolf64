from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from refresh_mod import source_hashes


class SnapshotSourcesTests(unittest.TestCase):
    def test_transitive_builder_and_added_assets_invalidate_snapshot(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True)
            (root / 'tools/wasm').mkdir(parents=True)
            for name, text in {
                'tools/build_wolfen.py': 'from character_builder import build\n',
                'tools/character_builder.py': 'def build(): pass\n',
                'tools/voice_blips.py': '',
                'tools/wasm/refresh_mod.py': '',
                'tools/wasm/mod_recipe.py': '',
                '.gitignore': '*.log\n',
            }.items():
                (root / name).write_text(text)
            assets = root / 'assets/portraits'
            assets.mkdir(parents=True)
            (assets / 'crew.png').write_bytes(b'first portrait')
            before = source_hashes(root)
            (root / 'tools/character_builder.py').write_text('def build(): return 1\n')
            changed = source_hashes(root)
            self.assertNotEqual(before['tools/character_builder.py'], changed['tools/character_builder.py'])
            (assets / 'new.png').write_bytes(b'new portrait')
            self.assertIn('assets/portraits/new.png', source_hashes(root))
            (assets / 'build.log').write_text('temporary diagnostic')
            self.assertNotIn('assets/portraits/build.log', source_hashes(root))


if __name__ == '__main__':
    unittest.main()
