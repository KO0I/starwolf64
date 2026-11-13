from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import export_site


class PublicExportTests(unittest.TestCase):
    def test_preloaded_build_cannot_be_published(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build/wasm/private"
            build.mkdir(parents=True)
            (build / "CMakeCache.txt").write_text("STARSHIP_WASM_PRELOAD_DIRECTORY:PATH=/private/archives\n")
            with patch.object(export_site, "ROOT", root), self.assertRaisesRegex(ValueError, "non-preloaded"):
                export_site.export(build, root / "build/wasm/site")
            self.assertFalse((root / "build/wasm/site").exists())

    def test_unexpected_runtime_payload_cannot_be_published(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build/wasm/public"
            build.mkdir(parents=True)
            (root / "build/wasm/inputs").mkdir()
            (root / "build/wasm/inputs/gamecontrollerdb.txt").write_bytes(b"controller data")
            (build / "CMakeCache.txt").write_text("STARSHIP_WASM_PRELOAD_DIRECTORY:PATH=\n")
            (build / "Starship.data").write_bytes(b"unexpected game assets")
            with patch.object(export_site, "ROOT", root), self.assertRaisesRegex(ValueError, "controller database"):
                export_site.export(build, root / "build/wasm/site")
            self.assertFalse((root / "build/wasm/site").exists())


if __name__ == "__main__":
    unittest.main()
