# Current WASM mod snapshot

`mod/recipe.json` and `mod/literals.dat` reconstruct the current character mod with the Starwolf dialogue-blip add-on applied last. Base resources are referenced by path and content hash. Changed byte ranges and new mod resources are stored as patch data.

`mod/chatter.dat` matches `assets/audio/chatter/bank.bin`. The archive retains that PCM bank, but the dialogue-blip marker selects native sequence playback and suppresses the legacy mixer. The current snapshot includes the crew HUD, Medusa launch updates, reviewed character refinements, and Panther title-eye correction.

The browser's pinned Torch extractor supplies the original game assets from the visitor's ROM. No base archive or ROM is stored here. The recipe contains each resource hash and a canonical resource-set SHA-256. ZIP timestamps and compression may differ; reconstructed resource bytes must match.

To rebuild and verify the snapshot from current sources:

```sh
python3 tools/wasm/refresh_mod.py
python3 tools/wasm/refresh_mod.py --check
```

These commands require the verified base ROM, `sf64.o2r`, and its matching `audio_data` export. The refresh command runs the existing character and audio builders, combines their resource maps in native load order, and compares every reconstructed resource before writing the recipe.

`mod/sources.json` records SHA-256 hashes of versioned asset inputs and the builders' transitive local Python imports. Public export and CI verify these inputs without a ROM:

```sh
python3 tools/wasm/refresh_mod.py --verify-sources
```

Commit source changes with the recipe, literals, chatter, and source hashes. The browser's asset fingerprint identifies the snapshot in prepared downloads.
