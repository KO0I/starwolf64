# Wolf bomber jacket and rearward cheek tufts

The existing Wolf title and on-foot rigs now use black-violet leather on the jacket exterior and eggshell sheepswool on the existing exposed lining. The trousers retain their previous runtime treatment. The cheek tufts are moved 14 model units back, compared with 6 in the preceding revision, and their front-to-back depth is 18 units, compared with 10. The wider head, enlarged ears, fur crown, and marked strap layout remain in place.

wolf-title.glb and wolf-on_foot.glb are editable glTF 2.0 models with the original rig nodes and animation clips. head.glb is the updated separate cockpit head. Images are embedded in every GLB. comparison.png compares the previous jacket with the new materials on the same geometry. wolf-bomber.png and views.png render the actual delivered title GLB.

The leather uses roughness 0.42; the shearling uses 0.98. The game receives 32 by 32 CI4 palette textures with four leather colors and six wool colors. The textures use simple blocky shapes and nearest filtering; modern glTF viewers also use the roughness values. The jacket edit changes materials only, with no changes to mesh positions, UVs, or animation.

textures/ contains the small game-ready tiles; texture-sources/ contains the generated low-detail source art. The built-in image_gen tool produced both tiles; prompts.json records the final generation prompts and palette settings.

From the project root, encode the textures with python3 tools/prepare_wolf_materials.py, then rebuild the previews with python3 tools/preview_wolf_jacket.py. Verify with python3 tools/check_wolf_jacket.py --compiled. Retain the included source credits when distributing.
