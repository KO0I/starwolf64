# Browser mod inputs

The public site uses the v2 source-bound recipe in mod/recipe.json, XOR changes in mod/literals.dat, and the pinned mod/restoration.bps patch. The browser extracts the base ROM, restores the required mod model locally, and reconstructs the reviewed native resource set. It does not download prepared archives or a raw chatter bank.

mod/provenance.json records each target, its true base or restored-model inputs, and generator witnesses. Historical snapshot resources distinguish regenerated hashes from reviewed target hashes. The freeze proves exact reconstruction of the reviewed target; it does not claim every current generator reproduces that historical target. mod/archives.json identifies all three resource sets independently of ZIP encoding.

The target contains 2,742 mod resources. The port archive contains four shaders. The original 15,898 resources come from each visitor's US v1.1 ROM.

Freeze a reviewed native overlay using the existing frozen snapshot as the starting target:

```sh
python3 -B tools/wasm/freeze_public_mod.py --base /private/sf64.o2r --rom /private/base.z64 --overlay /private/wolfen.o2r --port /private/shader-only-starship.o2r --private-project /path/to/native-authoring-project
python3 -B tools/wasm/refresh_mod.py --check --base /private/sf64.o2r
python3 -B tools/wasm/refresh_mod.py --verify-sources
```

The authoring project supplies matching private audio reports and portrait source inputs. Unknown resource lineage stops the freeze. Commit reviewed source changes with recipe.json, literals.dat, restoration.bps, provenance.json, archives.json, and sources.json.

Public export needs no ROM. It verifies source hashes, resource coverage, recipe hashes, and the extractor's exact preload inventory. It refuses preloaded runtimes, unexpected extractor payloads, prepared archives, extracted portraits, and generated geometry. The older mod/chatter.dat is a legacy authoring snapshot excluded from publication.

Run the actual WASM extraction check with --reference-base, --reference-mod, and --reference-port to compare every reconstructed resource against private references.
