# Play a browser-hosted match

Every browser brings its own unmodified Star Fox 64 US v1.1 ROM. Preparation, portraits, wireframes, and downloads happen locally. The signaling server never receives a ROM or serves prepared archives.

## Build and host

Use the pinned dependencies in [the WASM guide](../wasm/README.md):

```sh
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
python3 tools/wasm/export_site.py --build-dir build/wasm/game --output build/wasm/site
node tools/multiplayer/server.mjs --host 127.0.0.1 --port 8670 --site-dir build/wasm/site
```

Open http://127.0.0.1:8670/ and enter **Multiplayer / Sargasso Hideout**. Create or join a room before preparing. Choose your ROM or import a prepared ZIP, then confirm pilot, aircraft, and hue. Valid confirmations register automatically; repeated pilots receive distinct hues.

A preparing member appears as **hacking**, with procedural code rain as the anonymous portrait. Selection shows **pilot signing in…** and the draft hue. Pilot and ship stay private until confirmed. Editing before spawning withdraws confirmation. Active pilots remain fixed.

Each viewer derives confirmed portraits and hue-coordinated wireframes from their own archives. Unprepared viewers see code rain. Reduced-motion preferences use static glyphs. Main-page preparation survives entry into Sargasso and return.

**Remember this game on this device** opts into prepared archive storage. **Delete remembered game** deletes the saved copy and keeps the current in-memory game. The ROM is never retained. Individual O2Rs, an archive bundle, and a complete browser-game ZIP are generated locally. Imports must pass actual resource-set digests, even when their own manifests and hashes agree.

## Playable scope

For battle, select Corneria / Points, confirm your loadout, click **Prepare game**, then **Start game**. Guests prepare their own assets and choose **Join host game**.

For story, select **Main game co-op** and one crew. Players use that crew's matching aircraft. The host chooses missions on the native story map. Guests join once and follow supported transitions. Corneria supports rails and all-range flight with up to four total players. Other missions leave guests waiting while the host continues.

Each browser uses one camera and the single-player HUD. Arrow keys or WASD steer, Z or Space fires, X drops a bomb, Shift boosts, Ctrl brakes, and Q/E roll. Loading, timeout, or departure never pauses the host.

Selected hulls are Arwing, Wolfen, Katt's fighter, and Vitzy's fighter. Lasers use accepted hues. Arwing retains Star Fox engine colors and blue radar; other aircraft use selected engine hues and purple radar. Katt and Vitzy have intact hulls only. Vitzy's pilot is unavailable as **portrait pending**.

Rooms hold eight people; this engine admits the first four slots. Other VS maps, eight-player Venom, vehicle switching, distinct in-game pilot heads, and remaining campaign stages need further work.

## Tailscale

```sh
node tools/multiplayer/server.mjs --host 127.0.0.1 --port 8670 --origin https://your-node.your-tailnet.ts.net:8670 --site-dir build/wasm/site
tailscale serve --bg --https=8670 http://127.0.0.1:8670
```

HTTPS or localhost is required for shared WASM memory. Restart after exporting: the server pins the audited snapshot at startup. It rejects prepared sites, missing receipts, changed files, and paths outside the manifest. Legacy archive, portrait, and geometry routes stay blocked. The old --game-dir and --game-assets options are removed.

Signaling carries membership, offers, answers, and ICE candidates. WebRTC carries status, confirmed choices, controls, and native world images. Neither carries ROMs or archives. Compatibility covers runtime, schema, ROM revision, and all three semantic resource sets. ZIP compression and timestamps do not change resource identity. Optional STUN/TURN uses --ice-config /path/to/ice-servers.json; local tests do not prove connectivity through every remote network.

## Verify

Supply a running audited service and a local ROM. Chromium is required at /usr/bin/chromium.

```sh
node --test tools/multiplayer/*.test.mjs tools/shared/*.test.mjs
python3 tools/multiplayer/generate-scene-schema.py --check
node tools/multiplayer/check-game-browser.mjs --sign-in --rom /path/base.z64 --url http://127.0.0.1:8670/multiplayer/ --output build/byorom-sign-in
node tools/multiplayer/check-game-browser.mjs --ship-models --rom /path/base.z64 --url http://127.0.0.1:8670/multiplayer/ --output build/byorom-ships
node tools/multiplayer/check-game-browser.mjs --campaign --campaign-route --campaign-four --campaign-checkpoint --campaign-return-map --rom /path/base.z64 --url http://127.0.0.1:8670/multiplayer/ --output build/byorom-campaign
node tools/multiplayer/check-audio-browser.mjs --rom /path/base.z64 --url http://127.0.0.1:8670/multiplayer/ --output build/byorom-audio
```

Use --site-dir /path/to/audited/site instead of --url to have the gameplay checker start and stop its own signaling server on a free port. Reports and screenshots go to the selected directory. The campaign checkpoint starts near the end of rails. Return-map verification uses debug completion and does not prove a boss defeat. Omit those flags for an ordinary route flight. Use --native-menu to activate the actual native Multiplayer menu. The setup checker also accepts --rom and --url.

## Maintain assets

See [the recipe guide](../../assets/wasm/README.md) for source-bound mod freezing, [the bridge reference](../../docs/multiplayer-wasm-bridge.md) for scene ownership, and [merge readiness](../../docs/plans/multiplayer-merge-readiness.md) for campaign release checks. The offline wireframe exporter remains an authoring diagnostic. Its generated geometry is excluded from publication.
