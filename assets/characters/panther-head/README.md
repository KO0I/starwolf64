# Panther head reconstruction

[head.glb](head.glb) contains the 172-triangle replacement fitted into Panther's cockpit head coordinates. The game builder generates the same skull for the title and on-foot rigs, with shorter necks to seat it on the shoulder collar. [views.png](views.png) shows eight views. [comparison.png](comparison.png) compares the original source with the replacement.

[reference.jpg](reference.jpg) is the supplied model sheet. The views are artist renderings rather than calibrated orthographic images. `tools/site_character_panther.py` uses manually registered silhouette landmarks and diagonal projection constraints to reconstruct the skull. It samples 71 horizontal sections, then removes redundant sections while preserving the projected contours. The skull has 76 triangles. Ears, fitted facial markings, the neck, and the gold collar bring the complete head to 172 triangles.

The ear bases lie inside the skull. The pupils sit near the centers of the irises, and all three runtime heads are ten percent smaller than the initial reconstruction. The palette accounts for the native game's default gamma boost.

The source archive remains unchanged. Runtime replacements preserve the existing head nodes, transforms, bone ownership, and animation clips. [reconstruction.json](reconstruction.json) records the registered profiles and reduction counts. The original distribution credits in the parent archive still apply.

[fur.png](fur.png) is the 64×64 fur tile applied to the skull, outer ears, and neck in all three rigs. Short angular tufts modulate the existing purple palette. The tile repeats around the sides with a seam at the back and a planar projection on the caps. Native and browser builds use opaque CI4 textures with nearest filtering. The facial markings and collar retain their flat colors, and the mesh remains at 172 triangles.

[fur-source.png](fur-source.png) is the imagegen master. [fur-prompt.txt](fur-prompt.txt) records the built-in tool prompts. Resize the master to 64×64 with Pillow's Lanczos filter to reproduce the runtime tile.

## Rebuild the head and previews

Run these commands from the repository root:

```sh
python3 tools/site_character_panther.py
python3 tools/preview_panther_head.py
python3 tools/wasm/refresh_mod.py
python3 tools/check_panther_head.py
```

To capture the actual native game from three angles, run:

```sh
python3 tools/check_site_characters.py --panther-closeup --output browser/runtime/panther-head-proof
```

The geometry check reads all three compiled display lists. It verifies nonzero triangle areas after N64 vertex packing, closed skull topology, embedded ear bases, pupil placement, and unchanged rig nodes and clips.
