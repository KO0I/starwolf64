# WASM world bridge

The host browser runs the native C simulation. Guests render complete scene images from that host.
Guests do not run an independent gameplay simulation or receive streamed video.
One local camera and the single-player HUD draw the participant's native player slot.

## Ownership and messages

`NetworkGame` coordinates a room with a `WasmEngine` instance.
The engine adapter prepares a same-origin iframe, verifies archive SHA-256 values, and starts the real Emscripten main worker from a launch gesture.
The worker alone changes C gameplay state.
JavaScript submits bounded commands and scene imports through atomic shared-memory mailboxes at frame boundaries.

Protocol version 4 uses the reliable ordered WebRTC channel for controls and admission.
A guest must match the host's runtime/archive fingerprint and schema before admission.
The host sends a reliable baseline, checks its match, epoch, incarnation and tick acknowledgment, then repeats that barrier with a fresh complete image.
The host worker activates the slot after both imports. Guest controls remain disabled until the imported scene contains that incarnation.
Per-slot activation/removal commands are serialized. Failed admission cancels only that guest.

Live images use the unordered channel without retransmission.
Every image is complete, bounded to 262144 bytes and split into 8192-byte chunks.
Chunk headers carry match, epoch, tick, length and checksum.
Receivers discard incomplete older images when a newer image arrives, reject malformed metadata and import one complete image at a time.
Backpressure drops stale live publications rather than growing a queue.

Controls carry slot incarnation and increasing sequence numbers.
The host binds the claimed slot to the sending peer, and the C bridge rejects old incarnations and sequences.
Controls become neutral after 60 host frames without an update.
Removing a player clears their shots. Fresh admission resets equipment and lock-on state.
Campaign re-admission can resume the same participant's equipment after a topology change; slot reuse cannot inherit it.
Host departure ends the session.

## Native scene format

`generate-scene-schema.py` produces explicit numeric-field codecs from engine declarations.
The image covers players, all-range scenery, ordinary scenery, sprites, actors, bosses, effects, items, player shots, textured lines, radar marks, bonus text and numeric gameplay globals.
Scene format version 3 includes transforms, cameras, scores, timers and native versus state.
Corneria snapshots also include boss animation work, the current text resource ID, and music identity.

The wire format contains no C pointers or raw heap copies.
The importer decodes into temporary storage, checks identity, field ranges, object categories and draw types, then commits the scene.
Object callbacks, display-list resources and hitboxes come from the guest's matching local object table.
Player sound-source pointers are rebound to local player storage.

The schema permits audited numeric debris and Corneria actors, including scripted NPC wingmen.
Voice aliases remain separate from text identity, so muted edited dialogue still resolves on guests.
Guest radio drawing uses the host's state without advancing the local radio state machine.
An unsupported instance suspends campaign synchronization and leaves guests waiting while the host continues locally.
The host page reports the unsupported object. A VS export error ends that match.
Each additional stage needs a resource/work-field inventory and a real runtime check.

## Scope and limits

Corneria Points uses the native four-slot simulation with a single camera per browser.
The setup catalog has more pilots, aircraft, maps and room slots than this initial engine bridge can render or simulate.
The selected aircraft and hue render natively. Original Arwing assets and their dependencies are isolated under net/original.
Wolfen's native multiplayer and map resources retain the full hull, textures, UVs, and normals.
Its intact and three damaged-wing variants share isolated material dependencies under wolfen_player/detail.
Katt and Vitzy use their own hull resources. Their damaged wing variants are not authored.
Other maps, distinct pilot heads, vehicle changes, and eight-player capacity need further integration.

## Campaign ownership and handoff

Player zero owns the story map, shared path, object loading, AI, checkpoints, cutscenes, and progression.
Online story play allocates four player slots while retaining one native camera.
Companion setup initializes only personal flight, combat, camera, and inventory state.
Companion deaths respawn that companion without resetting the host's mission or lives.
Human weapons and lock-on ignore allied players and scripted wingmen.

A reliable stage descriptor carries the match, epoch, level, phase, topology, status, incarnation, and build fingerprint.
Guests wait during map selection and scripted transitions. Corneria phase zero supports rails and all-range flight.
Other missions leave guests waiting. The host continues through the native story flow.
Each flight revocation or topology change fences queued commands and world images with a new epoch.
A seqlock publishes coherent stage metadata. Bootstrap clears readiness before command acknowledgment.
A guest initializes the matching local scene and pools before importing its baseline.
World receivers restart their tick history for each epoch.
Per-slot admission records the last successful incarnation even if a stage changes while activation completes.

Snapshots arrive every other native host frame. Guests render the latest complete image; prediction and interpolation are future work.
Some native draw routines mutate gameplay state. The host's selected view remains part of the native tick.
Camera-independent targeting and effects need a later separation of those side effects from drawing.
The first bridge does not establish eight-player capacity, Safari support, TURN fallback or production Internet hardening.
