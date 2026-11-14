# Hosted pilot setup and joining during play

Date: 2026-11-14
Status: Corneria Points launches real WASM host/guest workers with authoritative world replication and joining during play. Four native player slots and the local single-player HUD are implemented. See [the bridge reference](../multiplayer-wasm-bridge.md) for current limits.
Related decisions: [ADR 0001](../adr/0001-lan-versus-multiplayer.md), [WebRTC plan](browser-webrtc-multiplayer.md).

## Player flow

The host creates a room before choosing a pilot. The setup page shows the actual radio portrait, starting aircraft, and preferred hue.
The host then chooses an existing VS map and supported match type, or the main-game co-op target and one crew.
The intended next action starts the real game while leaving the room open.
Other players enter the room code, choose their own pilot, load the current stage, synchronize, and receive a host-authorized spawn.
Loading or timing out one guest never pauses the host or other active players.

This replaces the earlier lobby-only admission rule.
Each participant fixes their pilot before their first spawn in that match.
Vehicle switching after death remains allowed.
The host can start Corneria Points alone.

Vitzy remains visible and unavailable with the label "portrait pending", as the user requested.
Her existing fighter and voice do not substitute for a radio portrait.
Original Fox, Falco, Slippy, and Peppy keep distinct logical IDs and their unmodified radio PNGs.

## Current implementation

The existing 1990s page provides synchronized setup over the real reliable WebRTC control channel.

- [catalog.mjs](../../tools/multiplayer/web/catalog.mjs) defines pilots, actual portrait assets, aircraft, hues, map/rule combinations, and pure selection policies.
- [session.mjs](../../tools/multiplayer/web/session.mjs) owns accepted choices and match configuration in the playing host's browser.
- [protocol.mjs](../../tools/multiplayer/web/protocol.mjs) validates version 3 selection requests, confirmations, and complete room setup messages.
- [app.mjs](../../tools/multiplayer/web/app.mjs) renders drafts and confirmed choices. A draft never becomes another player's authoritative selection.
- [server.mjs](../../tools/multiplayer/server.mjs) serves explicit portrait routes and continues to relay connection setup only.

The public additions are `selectLoadout(selection)` and `configureMatch(match)`.
Guests propose selections; only the host commits them.
The host reserves a distinct hue for repeated pilots and returns the accepted appearance.
Reconfirming the same preference retains its assigned hue.
Departures and slot reuse do not recolor remaining players or reuse the old peer's input acknowledgment.

A newly connected guest receives the current complete setup after the channel handshake.
Late setup synchronization is followed by a reliable native baseline and fresh-world acknowledgment before the host activates a guest.

VS choices preserve native combinations: Corneria with Points or Battle; Katina with Time; Sector Z with Points, Battle, or Time.
Main-game setup selects one crew. Star Fox normally uses Arwings, with Katt using her own fighter. Star Wolf normally uses Wolfens, with Vitzy's separate signature fighter exception when her pilot becomes available.
Changing the crew during setup clears incompatible unspawned choices and allows players to choose again.

The Start action launches the actual WASM engine for Corneria Points. Other map and appearance choices remain saved setup targets.

## Architecture decision

Pstack's architect workflow compared two independent candidates against engine ownership, live-join correctness, selection rules, interface size, and verifiable delivery.

| Candidate | Ownership | Benefit | Cost |
| --- | --- | --- | --- |
| A, integrated session | One browser session owns transport, setup, admission, and future worker commands. | One lifecycle owner handles peer loss and in-flight admission. | The session implementation grows. |
| B, separate pure coordinator | A pure state machine emits effects that a transport/worker driver executes. | Policy transitions can run without browsers or WASM. | Two asynchronous lifecycle owners must cancel and correlate the same admission. |

Candidate A is the base. The existing session remains the single asynchronous owner.
Candidate B contributed pure catalog and appearance policy helpers, which have behavior tests.
There is no separately mutable coordinator and no server-side game authority.
All callable subagent models were in the GPT family, so an independent cross-family judge was unavailable; no such judgment is claimed.

## Missing engine boundary

The inspected WASM source at commit `63783904` exposes `Wasm_SetControllerState` for controller zero.
Its launcher prepares archives and invokes `Module.callMain([])`.
It has no network stage-launch command, participant activation/removal API, world export/import, or guest simulation mode.
Its diagnostic player-zero coordinates are not a world snapshot.

`Play_Init` uses `gCamCount` for player allocation, simulation participation, and local view count.
Campaign controls assume one main controller.
Drawing changes some gameplay state, versus clocks depend on drawing, and random initialization uses wall-clock time.
The bridge keeps four simulation slots and renders one local view. Guests import complete scenes and skip native gameplay updates. The remaining draw side effects are documented in the bridge reference.

The native transitions in `Versus_StartMatch` and `Map_PlayLevel` supply the launch behavior to reuse.
Commands must enter a bounded queue and run on the C game worker at simulation boundaries.
The worker remains the only writer of game state.

## Required live-join contract

Transport membership and active participation are separate states.

1. Check protocol, engine build, rules, and required gameplay asset fingerprints.
2. Bind a participant identity and incarnation to the admitted peer. Reserve its stable appearance.
3. Load assets while the host keeps simulating.
4. Capture a consistent current-world baseline on a host simulation tick.
5. Transfer bounded checked chunks reliably. Include match ID, stage epoch, baseline ID, participant incarnation, tick, and schema version.
6. Import the baseline on the guest worker. Acknowledge its exact identity and apply subsequent changes through a catch-up barrier.
7. Have the host worker activate the ship and confirm spawn generation. Only then accept gameplay controls for that incarnation.

The baseline must cover stage/script progress, players, active entities, AI, projectiles, scores, clock, spawn generations, and relevant timers/random state.
Serialize fields and entity identities, never C pointers or the entire WASM heap.
The original sample snapshot codec remains a link test; native gameplay uses the separate complete-scene codec.

Stage changes invalidate transfers. Old acknowledgments cannot activate a participant in a newer match or reused slot.
A transfer that exceeds bounded catch-up history restarts from a fresh baseline or fails only that guest.
Guest removal cancels its pending spawn. Host departure closes the session.

## Verification and next delivery

The setup checks cover actual 44x44 portraits, original asset identities, unavailable Vitzy, valid native maps, co-op selection rules, duplicate hue stability, and strict message validation.
The real Chromium check uses the visible controls, accepts guests after earlier setup changes, tests disconnection and slot reuse, and captures desktop/phone screenshots.
HTTPS hosting and an actual non-secure HTTP context are separate browser checks.
Selection request IDs use `getRandomValues`, which is available in non-secure contexts; `randomUUID` is not. See the [Web Cryptography specification](https://www.w3.org/TR/webcrypto/).

The first playable gate is Corneria Points.
The host must start alone, move, fire, and score; a guest must join that running world, see existing objects, and control a different ship.
Verify one full-screen view per participant, mixed aircraft, deaths/vehicle changes, stale admissions, and uninterrupted host play during guest loading.
Then extend the verified engine bridge to all existing VS combinations, campaign co-op, and eventually eight-player Venom with extra hostile AI.

Katt uses the distinct katt_fighter identity and original ast_allies/aKattShipDL resource. Vitzy keeps vitzy_fighter, the private magenta-and-pink Bill-derived fighter. Signature pilot selection suggests her ship; PvP retains free aircraft choice, while co-op preserves signature assignments.
