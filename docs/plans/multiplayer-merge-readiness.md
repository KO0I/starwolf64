# Multiplayer merge preparation

Status: integration branch includes multiplayer 13c32931 and development d279d7b4.
The original development worktree and its uncommitted audio work are untouched.

## Chosen boundary

The native Multiplayer menu opens the browser-owned Sargasso selection screen.
BrowserSession owns confirmed pilot, ship and hue choices and WebRTC room membership.
NetworkGame owns launch/admission. WasmEngine queues native commands at worker boundaries.
Native loadouts are incarnation-scoped and included in complete scene images.
The browser roster uses confirmed selections; local drafts affect only the local editor.

Two source-grounded candidates were compared:
- Native-first selection would reuse the C drawing/input path but requires a new native roster and a second draft/confirmation protocol.
- Browser-owned selection reuses the existing portrait catalog, host validation and source-mesh wireframes. This is the base for merge preparation.
Native loadout staging and replicated laser hues are taken from the native-first design.
No independent cross-family judge was available; both architectural candidates used GPT-family models.

## Co-op story contract: four total

The host controls the native story map and mission progression. Three guests fly along.
Guests do not choose independent planets, advance their own campaign, or run local AI simulation.
Host map and cutscenes can leave guests on a waiting screen.
A host mission choice publishes a new stage descriptor and monotonically increasing epoch.
Guests load the matching assets, discard old-epoch chunks and import a fresh baseline before spawning.
Host departure ends the session; a loading or timed-out guest must not pause the host.

## Engine blockers before claiming playable campaign co-op

- Story currently allocates one Player; allocation, participation and local camera count must be separated.
- Player_Update routes non-versus controls to the main controller.
- Player_UpdatePath changes shared path/scroll/object state on every call. Slot zero must be the sole shared-path authority.
- Player_Setup resets shared hits, radio, checkpoints and mission state. Late joins need per-player setup without those resets.
- Cutscene_LevelStart advances a global frame counter. Guest player updates must not multiply cutscene or mission effects.
- Native AI wingmen need a defined policy when humans occupy their crew slots.
- Map_PlayLevel sets gCurrentLevel and enters PLAY directly. It needs the host stage descriptor/epoch hook.
- On-rails Corneria has no gScenery360 allocation; scene capture/import currently assumes one.
- Campaign starts with non-debris cutscene actors and NPC shots. The current Corneria VS codec rejects both.
- Audit actor work arrays and resource identity for each supported stage. Never copy host pointers.
- Verify the Corneria intro, rails section, all-range transition, boss, completion and return to the host map.

A selectable Co-op Story target is not proof of that engine work.
Do not merge the complete advertised co-op feature until a host and guest actually clear that route together.

## Other required follow-through

- Pilot and ship identity reach native loadout metadata; selected ship/pilot models still need resource/render dispatch.
- Native laser and charge colors use the accepted hue; ordinary offline colors retain their existing behavior.
- Ship/portrait previews use the actual assets; Vitzy remains unavailable with portrait pending.
- Public static hosting still needs a signaling service. The self-hosted Node package can serve the main site and /multiplayer/ together.
- Public ROM preparation must stay local to each user. Do not publish the private LAN archive routes as a public ROM distribution service.

## Verification

- Native build and browser main-menu activation must open Multiplayer.
- Check the same sunset-gradient stops as the main site and small italic host/join instructions.
- Keyboard/controller selection must not capture gameplay input or trap focus.
- Two browsers must agree on confirmed portraits, ship wireframes and hue, including duplicate pilots and slot reuse.
- Native world images must contain matching loadouts before input admission.
- Verify ordinary, twin and lock-on lasers and charging effects against the selected hue.
- Check preview cleanup, reduced motion and mobile layout.
- Keep main development unmerged until the remaining gameplay blockers are reviewed.

## Results from the integration build

- WASM compilation passed with the existing warnings.
- Signaling, catalog and world-protocol checks passed, including shared-site routes and directory containment.
- Four actual WASM clients passed late admission, continued host play during loading, departure, canceled admission and slot reuse.
- Native scenes carry the four accepted loadouts and distinct duplicate-pilot hues.
- Pilot changes are rejected while flying.
- Startup audio reaches its playing state, finishes boost effects, plays battle music and produces non-clipping PCM.
- The native menu displays Multiplayer and opens Sargasso through the iframe boundary.
- A delayed manifest cannot create an iframe after its room has closed.
- Queued controller updates coalesce only for the same slot and incarnation; rejected queue entries do not block retries.
- The ROM-free export includes the multiplayer modules and registered portraits; its manifest contains no game archives.

These checks cover Corneria VS and menu preparation. Campaign co-op and distinct in-game vehicle models have not passed a playable check.
