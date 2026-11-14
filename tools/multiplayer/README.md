# Play a browser-hosted match

Build the WASM game with the pinned SDK and dependencies described in [the WASM guide](../wasm/README.md).
Supply your existing local sf64.o2r, starship.o2r and wolfen.o2r archives in one directory.

```sh
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
node tools/multiplayer/server.mjs --port 8670 --game-dir build/wasm/game --game-assets /absolute/path/to/archives
```

Open http://127.0.0.1:8670/ in a browser. Create a room, save Corneria / Points, click **Prepare game**, then **Start game**.
Guests enter the room code, click **Prepare game**, then **Join host game**.
The host keeps playing while a guest downloads archives and imports the current world.

Each participant sees one camera with the single-player HUD for their local pilot.
Arrow keys or WASD steer, Z or Space fires, X drops a bomb, Shift boosts, Ctrl brakes, and Q/E roll.
The embedded player also provides touch controls and a fullscreen button.
Leave and create another room to start a fresh match.

The first engine bridge supports four players on Corneria Points.
Rooms still hold eight people; the remaining slots cannot enter this engine build.
Other VS maps, campaign, AI, eight-player Venom, vehicle switching and selected pilot/aircraft/hue rendering remain future integration.
The setup page preserves those choices and previews their actual radio portraits and source-mesh wireframes.
Vitzy stays visible and unavailable as "portrait pending".

## Use the existing private tailnet address

Keep the Node service on loopback and configure the allowed page origin:

```sh
node tools/multiplayer/server.mjs --port 8670 --origin https://your-node.your-tailnet.ts.net:8670 --game-dir build/wasm/game --game-assets /absolute/path/to/archives
tailscale serve --bg --https=8670 http://127.0.0.1:8670
```

Open the HTTPS address while connected to the tailnet.
Cross-origin isolation and shared WASM memory require HTTPS or localhost.
The server exposes only explicit runtime, archive, page and portrait routes.
Restart it after rebuilding; each process pins its runtime files and archive fingerprints.
Game archives remain local deployment inputs and are not committed.

Signaling forwards only offers, answers and ICE candidates.
Inputs and complete native world images travel over WebRTC between browsers.
Optional STUN/TURN settings remain available through `--ice-config /path/to/ice-servers.json`.
A local direct test does not establish TURN fallback or connectivity across every remote network.

## Verify the bridge

```sh
node --test tools/multiplayer/catalog.test.mjs tools/multiplayer/server.test.mjs tools/multiplayer/protocol.test.mjs tools/multiplayer/world-protocol.test.mjs
python3 tools/multiplayer/generate-scene-schema.py --check
node tools/multiplayer/check-browser.mjs --output build/multiplayer-setup-check
node tools/multiplayer/check-game-browser.mjs --url http://127.0.0.1:8670/ --output build/multiplayer-game-check
```

The gameplay check requires a running configured service and Chromium at /usr/bin/chromium.
It launches actual WASM host/guest workers, sends controls into a distinct native slot, imports live scenes, and records both cameras.
It also covers interrupted admission, guest departure, slot reuse, stale-incarnation rejection and host departure.
Reports and screenshots are written to the chosen output directory.
The setup checker continues to verify portraits, ship previews, crew policies and synchronized choices.

For a bounded real-input combat flight:

```sh
node tools/multiplayer/check-combat-browser.mjs --url http://127.0.0.1:8670/ --output build/multiplayer-combat-check
```

This flight uses ordinary steering, fire and bomb inputs. It never writes health, scores or player positions.
A successful flight must observe replicated projectiles, damage, native scoring and a subsequent respawn.

## Maintain assets and the scene schema

Regenerate the selector wireframes from existing local game assets:

```sh
python3 tools/multiplayer/export-wireframes.py --source-root /path/to/local/game-assets
```

Regenerate the numeric field inventory after changing engine declarations:

```sh
python3 tools/multiplayer/generate-scene-schema.py
```

Read [the bridge reference](../../docs/multiplayer-wasm-bridge.md) before adding a stage or entity type.
