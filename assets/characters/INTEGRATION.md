# Runtime character conversion

`tools/build_wolfen.py` verifies the reviewed source archive, converts its geometry and rigid bone clips, and installs the active crew into both the native O2R and browser ROM. The original GLBs, PNGs, and animation clips stay unchanged in `starwolf64-character-assets.zip`.

| Runtime slot | Reviewed character |
| --- | --- |
| Fox | Wolf |
| Falco | Panther |
| Peppy | Krystal |
| Slippy | Kami |
| James / Expert pilot | Vitzy head |

Wolf, Panther, Krystal, and Kami have title and on-foot bodies and cockpit heads. Vitzy has her supplied 206-triangle head and Bill cockpit module. The native Expert fighter uses the module inside its existing Bill-derived exterior. The browser uses Vitzy's head in the Expert slot. Pigma and the original Star Fox lineup remain available as source assets.

The converter removes the viewer's placement normalization, retains explicit body and head scales, and updates the game skeletons, pose tables, aiming callbacks, and ending callbacks. It retains every source triangle and records requested geometry additions separately. Positions, normals, and colors use N64 precision. Large textures shrink to fit texture memory, coincident pilot-head normals are averaged, and supplied ambient hints become vertex shading. The N64 renderer does not reproduce glTF metallic, roughness, or clearcoat shading.

The game uses the imported rigid body clips and its existing cockpit-head steering. Accessory-only tracks, alternate movement presets, and facial clips remain in the source pack. They do not have separate runtime animation controllers.

Kami's body-head atlas uses only its first strip, with the eyes confined to a small band. The converter gives the front face a separate cropped texture and remaps its UVs before resizing. The remaining head facets use the larger strip. Every texture fits N64 texture memory, and the split preserves all triangles.

`tools/site_character_kami.py` adds a small faceted snout with an upturned red tip, three upper and three chunky lower lashes per eye, thicker lower eyeliner, and clearer pink horn bands. The bands follow the existing stripe locations on the horn surfaces. The title head gains 76 triangles, the on-foot head gains 62, and the cockpit head gains 88. The additions follow the existing head node and use eightfold vertex precision with a matching modelview scale so the small on-foot details survive packing. Native assets use an XML matrix wrapper; the ROM uses a standard F3DEX matrix push. Both restore the matrix after each detail material. Generated snout faces retain flat normals.

The build reuses retired character geometry and animation storage. It rejects unresolved native resources, mismatched native and ROM data, a Vitzy head over 216 triangles, and any of the 44 browser scene layouts that reaches the original frame buffers. `build-cmake/character-assets.json` records the installed rigs, source hashes, fit transforms, storage use, and scene memory headroom.

## Rebuild and verify

Use Python 3 with NumPy and Pillow, plus the existing base ROM and `sf64.o2r`.

```sh
python3 tools/package_site_characters.py --verify
python3 tools/build_wolfen.py
python3 tools/build_wolfen.py --check
cmake --build build-cmake -j 4
python3 tools/check_site_character_patches.py
python3 tools/check_kami_eyes.py
python3 tools/check_kami_details.py
python3 tools/check_site_characters.py
python3 tools/check_vitzy_fighter.py --output browser/runtime/reviewed-vitzy-proof
python3 tools/export_browser_site.py
```

The native checks need a C compiler, GDB, Xvfb, and ImageMagick. They capture the title crew, inspect the display lists drawn by all four title and on-foot slots, and exercise Vitzy's fighter. The aiming check executes the actual browser MIPS callback across 192 cases.

Preserve the archive's `CREDITS.md`, `README_TheRegressor.txt`, and `Vitzy_README.md` when distributing the conversion. The native mod includes them under `characters/`; browser exports include them beside the page.
