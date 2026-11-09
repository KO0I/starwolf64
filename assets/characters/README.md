# Reviewed character and pilot-head sources

The [character asset archive](starwolf64-character-assets.zip) contains the reviewed models from the Star Wolf 64 Characters Site, with Kami body updates from the supplied `Kami_models.zip` on November 9, 2026. Its [manifest](starwolf64-character-assets.manifest.json) records the original Site revision, supplied update hashes, model counts, animation clips, textures, laser defaults, and file checksums.

The archive contains these assets:

- Nine full characters, each with title and on-foot variants: Wolf, Krystal, Kami, Panther, Pigma, Fox, Falco, Peppy, and Slippy.
- Ten separate pilot heads, including Vitzy. Vitzy has no full-body asset. Her head has a 216-triangle budget.
- Vitzy's Bill cockpit, with the same animated pilot head.
- Original PNG texture bytes, shared by checksum across models.
- Creator credits and the supplied usage terms.

Inside the archive, `characters/<name>/<variant>/body.glb` contains a complete character. `heads/<name>/head.glb` contains a cockpit head. `cockpits/vitzy/bill.glb` contains Bill's cockpit. Textures are embedded in every GLB and also available under `textures/`.

The package preserves the reviewed geometry, node transforms, skins, materials, and animations byte for byte. Wolf's full-character scale and separate cockpit-head scale remain distinct. The manifest lists each head's default laser color.

These GLBs are editable source assets. The current game uses converted `.o2r` or `.otr` resources. Import and convert the sources through the mod asset pipeline before runtime use. This package does not change the existing ROM-derived exports, native resource tables, or runtime pilot assignments.

Kami's title and on-foot bodies use the supplied replacements. Their GLB bytes and `Kami_CREDITS.md` are preserved in the archive. The distribution credits include the supplied credits.

## Verify and unpack

From the repository root, run:

```sh
python3 tools/package_site_characters.py --verify --extract-to build/character-assets
```

The command checks the ZIP contents, SHA-256 hashes, GLB structure, triangle counts, and texture mappings before extraction. Python 3 is sufficient.

## Rebuild from the Site export

Use a checked-out Site `dist/index.html` with both embedded character and pilot-head catalogs. Supply its exact source commit:

```sh
python3 tools/package_site_characters.py --viewer /path/to/site/dist/index.html --site-commit SITE_COMMIT --site-version SITE_VERSION
```

The builder copies the GLB and PNG bytes into a reproducible ZIP. It also refreshes the adjacent JSON manifest. The source Site's credits, Krystal usage terms, and Vitzy README must be present beside the viewer.

Include `CREDITS.md` and `README_TheRegressor.txt` from the archive when distributing these modified rigs. Vitzy is an original character by [VitzyPie](https://x.com/VitzyPie). Star Fox characters and original game assets are Nintendo's.
