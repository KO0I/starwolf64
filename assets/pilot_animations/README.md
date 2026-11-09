# Pilot animations

All 26 original clips for Fox, Falco, Peppy and Slippy, across eight title and on-foot rigs.

Import `body.glb` for all clips on a rig, or an individual file under `clips/`.
Each GLB includes its model and textures. Clip names retain the original asset symbols.

| Pilot | Title and ending clips | On-foot clips |
| --- | ---: | ---: |
| Fox | 5 | 3 |
| Falco | 3 | 3 |
| Peppy | 3 | 3 |
| Slippy | 3 | 3 |

Title GLBs include original root translation for ending mode 0. Title-screen mode 1 ignores that track.
On-foot GLBs fix root translation at the limb origin, matching versus mode 5. JSON and native files retain original root samples.
body.glb contains every clip for its rig; clips/*.glb contains one named clip per file.
Textures are embedded. Models use rigid limb nodes in original N64 units with Y up.
Runtime pose overrides, scene movement, animation blending, lighting and combiners are not baked.

Per-clip JSON retains decoded source frames; `native/` preserves the original animation and rig resource bytes.
See `manifest.json` for file paths, frame counts, timing, checksums and verification details.

Recreate with `python3 tools/export_pilot_animations.py` from the repository root.
