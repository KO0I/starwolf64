# WASM world bridge

The host browser runs the native C simulation. Guests render complete scene images from that host.
Guests do not run an independent gameplay simulation or receive streamed video.
One local camera and the single-player HUD draw the participant's native player slot.

## Ownership and messages

`NetworkGame` coordinates a room with a `WasmEngine` instance.
The engine adapter prepares a same-origin iframe, verifies archive SHA-256 values, and starts the real Emscripten main worker from a launch gesture.
The worker alone changes C gameplay state.
JavaScript submits bounded commands and scene imports through atomic shared-memory mailboxes at frame boundaries.

Protocol version 3 uses the reliable ordered WebRTC channel for controls and admission.
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
Removing a player clears their shots; reactivation resets score, equipment and lock-on state.
Host departure ends the session.

## Native scene format

`generate-scene-schema.py` produces explicit numeric-field codecs from engine declarations.
The image covers players, all-range scenery, ordinary scenery, sprites, actors, bosses, effects, items, player shots, textured lines, radar marks, bonus text and numeric gameplay globals.
It includes transforms, cameras, scores, timers and relevant native versus state.

The wire format contains no C pointers or raw heap copies.
The importer decodes into temporary storage, checks identity, field ranges, object categories and draw types, then commits the scene.
Object callbacks, display-list resources and hitboxes come from the guest's matching local object table.
Player sound-source pointers are rebound to local player storage.

The initial schema permits audited numeric debris actors and effects without external work pointers.
An unsupported instance produces an explicit export error and ends the game instead of leaving guests on a silently frozen image.
Each additional stage needs a resource/work-field inventory and a real runtime check.

## Scope and limits

Corneria Points uses the native four-slot simulation with a single camera per browser.
The setup catalog has more pilots, aircraft, maps and room slots than this initial engine bridge can render or simulate.
Selected pilot models, aircraft, hue variants, other maps, campaign, vehicle changes and hostile AI need further engine integration.

Snapshots arrive every other native host frame. Guests render the latest complete image; prediction and interpolation are future work.
Some native draw routines mutate gameplay state. The host's selected view remains part of the native tick.
Camera-independent targeting and effects need a later separation of those side effects from drawing.
The first bridge does not establish eight-player capacity, Safari support, TURN fallback or production Internet hardening.
