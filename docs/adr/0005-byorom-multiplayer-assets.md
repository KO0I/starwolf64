# ADR 0005: Bring your own ROM for browser multiplayer

Date: 2026-11-16
Status: Implemented; local extraction, sign-in, storage, downloads, and four-player gameplay verified.

## Context

The main browser page extracts a visitor's ROM locally. Sargasso previously downloaded a server-supplied base archive and mod, and hosted original radio portraits and source ship geometry. It also discarded main-page preparation on navigation. That conflicts with the required publication policy.

## Decision

BYOROM means bring your own ROM. Each browser prepares its own game. The ROM is validated locally and is never uploaded, stored by the site, or sent to another player. A host supplies gameplay state and admission decisions, not game assets.

One preparation service serves the main page and Sargasso. Entering Sargasso from the main page keeps its in-memory preparation owner alive. Direct entry can prepare independently. Generated archives may be stored on the device only after the player opts in. Deletion clears these archives; the ROM itself is never retained.

Players can import a prepared download when the actual resource contents match the required build. Imported manifests and self-reported hashes are not sufficient. Resource-set digests identify equivalent archives regardless of ZIP compression, timestamps, or ordering. Multiplayer compatibility also includes the runtime, network schema, and required ROM revision.

The site offers individual O2R archives, an archive bundle, and a complete prepared browser-game ZIP. These downloads are assembled locally.

## Publication boundary

The published site contains project code, extraction tools and schemas, reviewed mod changes, original artwork, and required dependency licenses. It contains no base archive, ROM, extracted original portraits, stock geometry files, or prepared game bundle.

New names do not establish original authorship. Mixed resources retain verified source lineage and are reconstructed locally using source-relative changes. Original material embedded in character packs must not pass through as an unexplained literal payload. Unknown provenance fails the release gate. Integrity and provenance are separate checks.

Radio portraits and ship wireframes are derived from each viewer's verified local archives. WebRTC carries identities, status, hue, confirmed choices, and gameplay state; it never carries ROM or archive bytes.

## Presence and registration

A connected member can prepare while the host keeps playing. Room membership, roster registration, and gameplay activation are separate states.

| State | Presentation |
| --- | --- |
| Preparing | The label is "hacking". The anonymous portrait is procedural raining glyphs. |
| Choosing | The label is "pilot signing in…". The glyphs follow the draft hue. Draft pilot and ship remain private. |
| Registered | The host validates confirmed pilot, ship, and hue using existing crew and duplicate-hue rules, then shares the accepted selection. Each viewer renders its own local portrait and coordinated ship wireframe. |

A viewer who has not prepared their own assets uses the code rain for remote portraits. Reduced-motion preferences show static glyphs.

Editing a confirmed choice before spawning withdraws registration and requires confirmation again. A spawned pilot stays fixed for the match. Vehicle changes remain reserved for the existing respawn-selection scope. Timeouts, departure, or disconnection remove registration without stopping other players.

## Alternatives and consequences

Serving extracted archives behind Tailscale was rejected because network access restrictions do not satisfy the asset-publication policy. Hosting renamed or encoded full original assets was also rejected.

Browser-only persistence requires local storage space and can be evicted by the browser. Missing, corrupt, or incompatible data requires local preparation again. A delayed guest remains outside gameplay while the host continues.

The immediate hosted-asset block was deployed before this migration. It must remain effective throughout the cutover and afterward.

## Verification

The actual WASM extractor reconstructs all 15,898 base resources, 2,742 mod resources, and four port shaders byte for byte against private references. The JavaScript suite passes 78 tests; publication and recipe checks pass 17 Python tests. Real Chromium checks cover 26 four-player ship/gameplay assertions and 22 sign-in, storage, import, download, and main-page handoff assertions. A complete downloaded game reaches the native title through its own launcher without selecting a ROM again. These checks do not establish full-campaign support or remote TURN connectivity.
