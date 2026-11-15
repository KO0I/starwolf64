# Edit a level for native and browser play

The local editor saves one `starwolf64-level-v1` JSON document. Both exporters compile that document into the game's existing object format and compare the decoded results before returning a build.

The first supported layout is Corneria on rails. Its palette contains the object types already used by that stage, including its event scripts. Use **Scene 3D** to preview the actual static Corneria scenery meshes and textures. Drag to orbit, shift-drag or right-drag to pan, and use the wheel to zoom. Click a model to select it, or select an entry in the object list and use **Focus selected**. Inspector edits update the rendered scene immediately. Plan and elevation views remain available for marker dragging.

The static preview currently extracts 29 scenery types. Script events, animated enemies and custom-drawn objects use markers. The ground plane uses the game's grass texture; terrain deformation, camera-facing behavior, lighting and texture-combiner effects are approximated or omitted. Use Playtest to check mission behavior and the final game rendering.

## Start the editor

Keep the original US v1.1 big-endian ROM and the extracted `sf64.o2r` in the project root, as required by the existing build. Run from the repository root:

```sh
python3 tools/level_tool.py serve
```

Open <http://127.0.0.1:8650/>. The server listens only on this machine. It reads the source assets and generates exports in memory. It does not replace installed mods, publish a site, or write layout files from the browser.

The editor uses `mods/wolfen.o2r` and `browser/wolfen.z64` as its mod baselines when they exist. Native exports retain the other archive members. Browser exports retain the other ROM changes. If a baseline is absent, that target uses original game assets. Baselines are read when the server starts; restart it after rebuilding the game mod.

Use **Files → Open layout…** to resume a saved layout. Use **Save layout** to download the editable source. Keep that JSON as the source of truth when making later changes.

## Use the editor on a phone

The editor fits the screen without page scrolling. **Preview** keeps the viewport and green **Scrub route** dock visible together. Drag the slider, type a distance, or tap Start, End and the 500-unit steps. Any scrub control opens Flight preview automatically.

Use the bottom tabs to switch between **Preview**, **Objects** and **Inspector**. Objects has separate tabs for placed objects and the add palette. Selecting a placed object opens its Inspector. **Show in preview** returns to the selected object. Inputs and buttons are sized for touch; Scene 3D supports one-finger orbit and two-finger pan and pinch-to-zoom.

**Save layout** remains in the header. **Files** holds open/new, undo/redo, exports and Playtest. In landscape the scrub dock sits beside the viewport. Camera opens a bounded settings panel so its fields remain reachable on short screens.

## Scrub the flight route

Choose **Flight preview** for a forward-facing camera. Drag the flight-distance slider, enter an exact distance, or use the start, end and 500-unit step buttons. **Focus selected** jumps to the selected object's spawn distance. Camera height and lateral X are adjustable without changing any object data.

Scrubbing works in both directions and preserves the document, undo history and selection. The preview uses the existing scenery meshes and the on-rails spawn lookahead of 200 units. It follows a straight centerline with a nominal camera height of 350 units. Scripted route turns, enemy motion, collisions and mission events are not simulated; use Playtest for those. Camera controls are editor state and are not included in either target export.

## Edit and playtest

Select an object in the viewport or object list. Drag its marker to change its path distance and lateral or vertical position. Use the inspector for exact positions, object types and rotations. Duplicate, delete, undo and redo work on the shared document.

The stock layout fills all 803 available object slots. Delete an object before adding another, or start a new layout. The editor keeps same-distance objects in their authored order because event ordering can affect formations and mission scripts.

Use **Playtest** to open a copy of the browser player with the edited level patch. Choose your unmodified base ROM there and launch the game. The patch is generated locally. The preview page uses the matching build checksum and does not serve a complete ROM. Playtest requires the existing browser site at `browser/runtime/site`; generate it with the normal browser export tool if it is missing.

A layout changes object placement and references to existing behavior. It does not author new meshes, collision shapes, enemy scripts, bosses or cutscenes. A fresh layout needs the appropriate mission events to become a complete mission. Rotating a scenery object can still be overridden by its existing draw or update code.

## Export both targets

**Export native** downloads a combined `corneria-level.o2r`. It includes the current native mod plus the edited object resource. To install it, keep the original mod as a backup outside the active `mods` directory and use the combined archive in its place. Avoid loading two archives that override the same resources, because directory iteration does not define their load order.

**Export browser** downloads `corneria-level.patch.json`. It uses the existing `starwolf64-delta-v1` patch format and applies to the original US v1.1 ROM. Playtest loads it directly. When packaging it into another browser player, that player's `STARWOLF_build` value must match the patch's target SHA-256 prefix. The command-line build also produces a complete local ROM for use with the existing site exporter.

To build outside the editor:

```sh
python3 tools/level_tool.py import --output /tmp/corneria.json
python3 tools/level_tool.py validate /tmp/corneria.json
python3 tools/level_tool.py build /tmp/corneria.json --output-dir /tmp/corneria-build
```

The output directory receives the combined native archive, the browser ROM, the browser delta patch and `build-report.json`. The report records the object count and target hashes. Source ROMs and archives remain unchanged.

To choose different source paths, put the global options before the command:

```sh
python3 tools/level_tool.py --native-mod /path/to/wolfen.o2r --browser-rom /path/to/wolfen.z64 serve --port 8651
```

## Document reference

```json
{
  "format": "starwolf64-level-v1",
  "name": "My Corneria route",
  "layout": "corneria-on-rails",
  "objects": [
    {
      "uid": "arch-1",
      "objectId": 0,
      "pathDistance": 1000,
      "offset": {"x": 0, "y": 0, "z": 0},
      "rotation": {"x": 0, "y": 0, "z": 0}
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `format` | Version of the shared document. |
| `layout` | Stage and mode whose object list is being replaced. Version 1 currently supports `corneria-on-rails`. |
| `name` | Authoring name, from 1 to 120 characters. |
| `uid` | Stable authoring identity, unique within the file. It is not stored in game records. |
| `objectId` | An existing Corneria palette entry, including supported event-script IDs. |
| `pathDistance` | Nonnegative path distance at which the object becomes eligible to spawn, stored as float32. |
| `offset` | Signed 16-bit integer placement values. X and Y are lateral and vertical coordinates. Z is the original spawn offset. Runtime world Z is `-pathDistance - 3000 + offset.z`. |
| `rotation` | Signed 16-bit integer X, Y and Z rotations in degrees. Object-specific behavior may interpret them further. |

Object array order breaks ties between equal path distances. Exports sort by path distance without changing that tie order. Unknown fields, duplicate UIDs, duplicate JSON keys, nonfinite numbers and values outside the game fields' ranges are rejected. Values such as `100.1` are normalized to the actual float32 value before compilation.

Corneria's existing ROM allocation holds 804 records including its terminator. Both targets use the shared 803-object limit. Checkpoints require at least 40 preceding objects because the original game's reload logic reads that many earlier entries. The exporter rejects unsupported object types and unsafe checkpoint layouts.

Native records use little-endian 18-byte payloads under an ObjectInit resource header. ROM records use big-endian 20-byte records, including padding. Addresses and byte order belong to the exporters and are not stored in the authored JSON. The ROM exporter expands and relocates the existing Corneria segment when needed, updates its DMA entry and recalculates the cartridge checksum.

## Verify changes

```sh
python3 -m unittest discover -s tools -p 'test_level*.py'
node tools/check-level-exports.mjs http://127.0.0.1:8650/
node tools/check-level-editor.mjs http://127.0.0.1:8650/
node tools/check-level-mobile.mjs http://127.0.0.1:8650/
```

The Python checks compare real imported records, edit both targets, preserve unrelated mod resources and reconstruct the exact browser ROM from its delta patch. The browser check exercises the visual controls, document downloads and both export routes.

The shared-document design keeps saves independent of either runtime. Direct game-memory editing would require separate runtime integrations and would lose the authored layout on restart. This first exporter keeps the original object allocation rather than changing hardcoded pointers and increasing the stage's RAM requirements.
