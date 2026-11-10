# Vitzy pilot head and Bill cockpit

Vitzy is an original character by [VitzyPie](https://x.com/VitzyPie). These fan-made head meshes follow the two supplied references in `references/`.

`vitzy_head.glb` contains only the head, hair, frills, facial surfaces, and six-joint pilot rig. There is no body mesh. `vitzy_bill.glb` mounts that same rig inside an angular Wolfen-style cockpit cutaway with canopy frame, seat, controls, and pilot mounting ring. This is a cockpit module, not a proposed exterior design for Bill.

Both models include Pilot idle, Talking, Look around, and Blink animations. The Rig checkbox shows the joints. Choose Rest pose to compare the front, side, back, and three-quarter views. The original radio portrait pair is retained separately.

The head budget is 216 triangles. The complete head, including hair, frills, blinking eye quads and talking mouth, uses 206 triangles. Bill uses that same head plus 744 cockpit triangles, for 950 total. Facial marks and frill rays use the embedded 512 × 512 alpha-masked atlas, also provided as `vitzy-atlas.png`. Frills and hair tips are thin double-sided silhouettes. The rebuild fails if the head exceeds its budget.

Rebuild with `python tools/vitzy_pilot.py --integrate`. The command regenerates both GLBs, their rendered previews and fallback clips, the downloadable ZIP, and the viewer entry. NumPy, Pillow, ffmpeg, and a C compiler named `cc` are required.
