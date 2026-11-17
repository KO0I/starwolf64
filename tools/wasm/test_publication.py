import unittest
from publication import audit_contents, verify_extractor_package
from pathlib import Path
from tempfile import TemporaryDirectory
import json

class PublicationTests(unittest.TestCase):
    def test_code_and_reviewed_recipe_inputs_get_content_bound_records(self):
        files={"index.html":b"authored UI","shared/preparation.mjs":b"export const local=true;",
               "runtime/Starship.wasm":b"\0asm", "mod/literals.dat":b"changes"}
        result=audit_contents(files,{"status":"pass","resources":4})
        self.assertEqual(result["policy"],"byorom")
        self.assertEqual(set(result["files"]),set(files))
        self.assertEqual(result["files"]["mod/literals.dat"]["kind"],"reviewed-mod-input")

    def test_original_or_unreviewed_paths_cannot_be_published(self):
        for path in ["sf64.o2r","assets/original.z64","portraits/fox.png","multiplayer/ship-wireframes.json","model.glb","unknown.dat"]:
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,"Unreviewed"):
                audit_contents({path:b"copied bytes"},{"status":"pass"})

    def test_renaming_an_archive_does_not_make_it_a_mod_input(self):
        with self.assertRaisesRegex(ValueError,"archive"):
            audit_contents({"mod/literals.dat":b"PK\x03\x04copied archive"},{"status":"pass"})

    def test_integrity_without_provenance_is_insufficient(self):
        with self.assertRaisesRegex(ValueError,"provenance"):
            audit_contents({"mod/literals.dat":b"valid checksum alone"},{"status":"unknown"})


class ExtractorPackageTests(unittest.TestCase):
    def test_public_package_is_exact_and_rejects_hidden_or_changed_payloads(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            paths=["config.yml","assets/yaml/us/rev1/ast_logo.yml",
                   "port/shaders/directx/default.shader.hlsl","port/shaders/metal/default.shader.metal",
                   "port/shaders/opengl/default.shader.fs","port/shaders/opengl/default.shader.vs"]
            entries=[];data=b""
            for name in paths:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);payload=name.encode();path.write_bytes(payload)
                entries.append(dict(filename="/source/"+name,start=len(data),end=len(data)+len(payload)))
                data+=payload
            build=root/"build";build.mkdir()
            def write(records,payload):
                (build/"extractor.data").write_bytes(payload)
                (build/"extractor.mjs").write_text("loadPackage("+json.dumps(dict(files=records,remote_package_size=len(payload)))+");")
            write(entries,data)
            verify_extractor_package(build,root)
            with self.subTest("hidden original entry"):
                extra=dict(filename="/source/port/assets/stock",start=len(data),end=len(data)+3)
                write(entries+[extra],data+b"rom")
                with self.assertRaisesRegex(ValueError,"unreviewed"):verify_extractor_package(build,root)
            with self.subTest("trailing bytes"):
                write(entries,data+b"stock")
                with self.assertRaisesRegex(ValueError,"trailing"):verify_extractor_package(build,root)
            with self.subTest("changed payload"):
                write(entries,b"X"+data[1:])
                with self.assertRaisesRegex(ValueError,"changed"):verify_extractor_package(build,root)

if __name__=="__main__":
    unittest.main()
