# Star Fox 64 portrait assets

Panther, Krystal, and Kami each have a closed-mouth frame and a slightly-open talking frame. The artwork follows the supplied original SF64 portrait sheet's tight framing, directional lighting, and shaded 3D forms. Krystal has a red forehead gem and green eyes. Kami has pointed teeth in her talking frame.

Panther's corrected design has near-black indigo fur, short rounded ears, a heavy dark muzzle, and narrow yellow eyes. His talking frame shows a red-pink mouth interior and two small upper canine fangs. Kami's revised eyes have round globes, half-closed purple upper lids, and pointed false lower lashes.

## Texture specification

Every individual game texture is **44 by 44 pixels**, opaque, in N64 RGBA16 format: five bits each for red, green, and blue, and one bit for alpha. Each raw frame contains **3,872 bytes**, in big-endian, top-to-bottom row-major order, with no header, padding, or compression.

| Directory | Contents |
| --- | --- |
| `native/` | Six individual PNG textures, quantized to the exact RGBA5551 values, plus an optional 88 by 132 PNG sheet. |
| `rgba16/` | Six raw `.rgba16.bin` frames for import into a ROM or texture build. |
| `include/` | Six comma-separated `u16` initializer fragments for C asset arrays. |
| `masters/` | Generated artwork before native-size conversion and mouth registration. |
| `previews/` | Native and enlarged GIFs, plus a closed-versus-talking contact sheet. |

In the PNG sheet, rows are Panther, Krystal, and Kami. The left column is closed and the right column is talking. The sheet is a convenience image, not a replacement for one 44 by 44 slot.

The exported talking frames use the closed frame's exact pixels outside the mouth region. The generated mouths are inserted within the rectangles in `manifest.json` before color conversion. This prevents camera, eye, hair, and background flicker between frames. For later production edits, use the registered native textures, rather than switching directly between the unregistered masters.

There are no baked HUD borders or screen scanlines in the textures. GIF timings are a visual demonstration; the game controls mouth timing through its radio handler.

## Import

Import the individual PNGs through your mod's texture pipeline, or use the corresponding raw bytes where an uncompressed RGBA16 texture is expected. A C fragment can be included in a `u16 portrait[44 * 44]` initializer. Preserve the target project's alignment rules.

For a Starship mod, package textures through the project's asset tools under the replacement paths for your chosen slots. This ZIP is an asset source pack, not an installable `.o2r` archive or a ROM patch. No target-slot assignments were supplied in this request. `target_slot_mapping` is therefore unset in the manifest. These frames have not been tested in-game.

## Rebuild and validation

Install Pillow, then run `python build_assets.py`. The script rebuilds the native images, binaries, C fragments, previews, manifest, and validation report from the included masters.

The checks verify all six PNG dimensions, raw byte counts, RGBA5551 encode/decode round trips, opaque alpha, changed mouth pixels, and zero changed pixels outside each mouth rectangle. `validation.json` records the results. `manifest.json` records the per-frame raw SHA-256 hashes.

## Source references

The [Starship radio handler](https://github.com/HarbourMasters/Starship/blob/main/src/engine/fox_radio.c) draws portraits as 44 by 44 RGBA16 textures and selects the adjacent frame during talking. The [US rev1 Star Wolf declarations](https://github.com/HarbourMasters/Starship/blob/main/assets/yaml/us/rev1/ast_star_wolf.yaml) independently specify the dimensions and format. The manifest retains the fetched source-file blob hashes.

Artwork was generated with the built-in image generation tool, using the user's portrait sheet as the style reference and the previous custom portraits as character references. The talking masters were generated as localized mouth edits. Native scaling, mouth registration, format conversion, and preview assembly are performed by the included script. This pack contains the new portraits, not the original-game portrait sheet.
