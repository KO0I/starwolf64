# Tested WASM mod snapshot

`mod/recipe.json` and `mod/literals.dat` reconstruct the exact native mod used by
the working private preview. Base resources are referenced by path and content
hash, with only changed byte ranges stored in the patch. Identical resources under
new mod names reuse the extracted base data. New mod resources are patch data.
`mod/chatter.dat` is the reviewed CHT2 crew-chatter bank used by that preview; it
is separate from the older native-authoring bank on this branch.

The snapshot contains 1,668 resources. Its canonical resource-set SHA-256 is
`8f6cfeca601ec080f9bfbaaa34f5feadb7ce30b1c7c80f591e3c9e01f7a4d542`.
This preserves the existing characters, ships, title cards, chatter and Panther
eye correction. ZIP timestamps and compression can differ; every resource's
actual bytes must match.

The browser's pinned Torch extractor supplies the original game assets from the
user's ROM. No base archive or ROM is stored here. The recipe is the versioned mod
input for the browser build, so a fresh CI build does not need either private file.

To update the snapshot from a reviewed native mod:

```sh
python3 tools/wasm/mod_recipe.py --base /path/sf64.o2r --mod /path/wolfen.o2r --chatter /path/reviewed-bank.bin --output assets/wasm/mod
```

The generator reconstructs and compares every resource before writing the new
recipe. Repeat with `--check` to verify an existing snapshot. Include the changed
recipe, literals and chatter together in the source commit. The browser's asset
fingerprint identifies which snapshot a prepared game uses.
