# Multiplayer merge preparation

The campaign implementation builds on c061ac20, which already includes development d279d7b4.
The development worktree and its uncommitted assets and audio remain untouched.

## Implemented

Sargasso owns pilot, aircraft, hue, room membership, and WebRTC signaling.
The native Multiplayer menu opens that browser selection screen.
Confirmed loadouts select the original Arwing, Wolfen, Katt's fighter, or Vitzy's fighter.
Original Arwing display lists and their dependencies use the separate net/original resource namespace.
Lasers use the accepted hue. Arwing engines retain Star Fox's red planet glow and blue space glow.
Other aircraft engines use the accepted hue. Arwing radar uses the original blue window and white frame; other all-range radar stays purple.
Katt and Vitzy have intact hull models only.
Vitzy remains unavailable as a pilot while her radio portrait is pending.

Corneria story co-op has one host and up to three human companions.
Player zero owns the native story map, shared path, AI, checkpoints, cutscenes, and progression.
The native camera count stays one. Each browser draws its own player and the single-player HUD.
Scripted NPC wingmen keep their original story roles.
Companions have independent controls, weapons, damage, cameras, and respawns.
Allied players and NPC wingmen are excluded from friendly weapon hits and lock-on.

Stage descriptors, native commands, and complete world images carry an epoch.
Guests wait during map selection and scripted transitions, initialize the matching local scene,
then import a fresh baseline before entering flight.
The rails-to-all-range handoff re-admits the same connected companions without resetting their equipment.
A replacement peer in the same slot starts fresh.
Guest loading, departure, and timeouts do not pause the host.
A campaign export failure suspends guest synchronization and reports the unsupported object while the host keeps playing.

Radio synchronization carries a canonical text resource ID separately from the voice ID.
Muted edited dialogue keeps its silent voice alias.
Guests display the host's radio state without advancing the local radio state machine.

Shared local BYOROM preparation, anonymous code rain, private draft hues, automatic confirmed registration, local portraits and wireframes, verified imports, optional storage, and deletion are implemented. See [ADR 0005](../adr/0005-byorom-multiplayer-assets.md).

## Supported scope

The playable routes are Corneria Points and Corneria story phase zero, including rails and all-range topology.
Other story missions keep guests waiting while the host continues through the native campaign.
Every additional stage needs an actor work-field audit, local scene bootstrap, and real browser verification.
The codec never sends raw C pointers.

Other VS maps, eight-player Venom, vehicle switching, distinct pilot heads, and authored damaged-wing variants for Katt and Vitzy remain pending.

## Verification

The multiplayer unit suite covers protocol validation, server routes, loadout policies, stage coherence,
old-epoch rejection, activation races, peer replacement, slow preparation, and input release during waiting.
The generated numeric scene schema is checked against native declarations.
The WASM build passes with the existing compiler warnings.

The four-browser VS check verifies all four selected hulls, accepted hues, live controls, late admission,
interrupted transfer, departure, slot reuse, stale input rejection, and host departure.
A two-browser flight has traversed the actual Corneria intro and rails section into all-range.

The campaign browser check also supports four participants, the existing native checkpoint,
and the existing completion debug control for the return-map handoff.
Its report records checkpoint and debug-completion use.
A debug completion does not prove a boss defeat.
See [the multiplayer guide](../../tools/multiplayer/README.md) for reproducible commands and artifact locations.

Before the BYOROM migration, the gameplay run passed 43 unit tests, 38 setup-browser assertions, 20 four-ship VS assertions,
16 four-player campaign assertions, and six audio assertions.
The campaign report records all four active slots in rails and all-range, followed by native map state 4.
That return-map check uses debug completion. The full earlier two-browser rails flight used the ordinary story route.

The ROM exporters now resize only complete scene asset descriptors. This ports the ROM branch's
Landmaster entry fix for Macbeth and Titania and the adjacent Aquas asset fix.
Nine regression tests pass. A dry run against the original US 1.1 ROM validates all 44 scenes
and preserves the tank and Aquas descriptors during asset growth.
These checks cover ROM export data, not native or WASM Landmaster gameplay.

## Gates before a full campaign merge

- Verify an ordinary boss defeat through completion and return to the host map.
- Audit and enable the remaining story stages.
- Check a native desktop build and ordinary offline play.
- Keep the BYOROM publication gate enabled. Every player prepares locally; the audited server blocks archives and extracted presentation files.

The current implementation is a Corneria co-op increment. It does not establish full-campaign completion,
eight-player capacity, Safari support, or TURN fallback across remote networks.

## BYOROM verification

The migration passes 78 JavaScript tests and 17 Python publication/recipe tests. Actual WASM extraction matches 15,898 base resources, 2,742 mod resources, and four shaders byte for byte. Real-browser runs verify 26 four-player gameplay assertions and 22 sign-in, import, cache deletion, complete-download launch, and shared main-page preparation assertions. The audited export contains no prepared archives or extracted portrait/geometry routes.

Four actual browsers also pass 20 co-op assertions through the host map, checkpoint-assisted rails, all-range handoff, and debug completion back to the map. The final main-page check passes invalid-ROM rejection, prepared download verification, native title/menu launch, and actual audio without hosted image requests.
