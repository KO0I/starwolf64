# Wolf head from the supplied reference

A new low-poly interpretation of the gray wolf just right of center in the supplied Star Fox character image. Blue-gray fur, tall pointed ears, a cream muzzle, the exposed eye, and a modeled black eye patch follow the visible reference. The back and hidden side are inferred. This asset is separate from the existing game and character replacements.

- head.glb: self-contained glTF 2.0 model with flat normals and named material parts.
- head.blend: editable model, materials, studio lights, and preview cameras.
- head.obj and head.mtl: triangulated OBJ with material colors.
- preview.png and views.png: actual renders of the exported model.
- model-info.json: geometry validation and dimensions.
- wolf_reference_head.py: reproducible Blender source.

The model has 477 triangles across 23 named mesh parts. The GLB uses meters, +Y up and +Z forward. Its origin is at the base of the neck. The head is 0.30 meters tall. Colors use materials and require no image textures. The parts are separate and overlap at their attachments; this is a visual asset, not a fused watertight printing mesh. No animation rig is included.

Rebuild from the project root with python3 tools/wolf_reference_head.py. Set BLENDER_BIN to use another Blender 4.2 or newer executable.

Character design: Wolf O'Donnell / Star Fox, Nintendo. The supplied image is retained as the reference. Mesh geometry was constructed for this request; no existing game mesh is included.
