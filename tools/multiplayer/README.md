# Browser-hosted WebRTC connection proof

Run in the isolated multiplayer worktree:

```sh
node tools/multiplayer/server.mjs --port 8670
```

Open `http://127.0.0.1:8670/` in two browser windows.
Create a room in one window and enter its code in the other.
The guest can send a control sample, and the host can send a world snapshot.
The page reports messages received over real WebRTC data channels.

This is the first connection milestone. It does not yet run a shared Starwolf match or connect to the WASM engine.
The single-player WASM preview is unchanged.

## How the pieces communicate

The Node service creates rooms and forwards offers, answers, and ICE candidates.
HTTP requests and a server-sent event stream provide signaling.
Control samples and snapshots travel over browser-to-browser WebRTC data channels, not through those signaling routes.

Each guest connects to the host. Guests do not connect to each other.
The room limit is eight people including the host.
That limit is not proof of eight-player gameplay performance.

The browser session uses a reliable ordered control channel and an unordered snapshot channel with retransmissions disabled.
Input sequences and snapshot ticks reject stale samples.
Snapshots in this proof are self-contained.
The transport bounds buffered data rather than accumulating unlimited stale state.

The first proof codec sends validated versioned JSON as binary UTF-8 data.
This establishes real message exchange and ownership rules. It does not freeze the future C engine-state encoding.
The engine bridge still needs complete movement-state, collision, entity-lifetime, and prediction inventories.

## Tests

```sh
node --test tools/multiplayer/server.test.mjs tools/multiplayer/protocol.test.mjs
node tools/multiplayer/check-browser.mjs --output /tmp/starwolf-webrtc-check
```

The browser check requires Chromium at `/usr/bin/chromium` and Node with a global WebSocket client.
The development environment uses Node 26. No npm dependencies are required.

The check starts its own local service and browser contexts.
It verifies one host with two guests, guest-to-host inputs, host-to-guest snapshots,
stale-message rejection, and continued exchange after one guest leaves.
It also checks that leaving the host ends the remaining guest session.
The remaining guest deliberately processes its room-close notice 300 ms late to exercise shutdown ordering.
The report includes actual data-channel counters and the selected ICE path.
Signaling traffic is inspected to ensure it carries connection setup rather than game messages.

The browser check writes its report and screenshots to the output directory.
A local direct connection does not establish TURN fallback, remote-network, Safari, or WASM gameplay support.


To check a running service, including a Tailscale HTTPS address:

```sh
node tools/multiplayer/check-browser.mjs --url https://your-node.your-tailnet.ts.net:8670/ --output /tmp/starwolf-hosted-check
```

With `--url`, the check uses the supplied service instead of starting another server.
It runs the same real WebRTC assertions and captures desktop and 390-pixel phone screenshots.

## LAN, Tailscale, and relay setup

For an intentional LAN listener:

```sh
node tools/multiplayer/server.mjs --host 0.0.0.0 --port 8670
```

Every participant opens the same reachable service address.
The default listener remains localhost.
Use HTTPS for a deployed browser game and its signaling service, including the threaded WASM player's isolation requirements.
Tailscale can supply connectivity to the service, but browser ICE routing still needs validation on the intended devices.
Behind an HTTPS reverse proxy, allow its exact public origin with `--origin https://your-game.example`.
The option can be repeated for additional trusted origins; it does not enable cross-origin CORS.


For a private Tailscale HTTPS proxy, start the backend with the exact public origin:

```sh
node tools/multiplayer/server.mjs --port 8670 --origin https://your-node.your-tailnet.ts.net:8670
tailscale serve --bg --https=8670 http://127.0.0.1:8670
```

Use the address printed by Tailscale Serve while connected to the tailnet.
The Node process must remain running; a user service can manage it.
Remove only this proxy with `tailscale serve --https=8670 off`.
See the [Tailscale Serve documentation](https://tailscale.com/docs/reference/tailscale-cli/serve).

Optional STUN or TURN settings are supplied as a JSON array:

```json
[
  {"urls": "stun:your-stun-host.example:3478"},
  {
    "urls": "turn:your-turn-host.example:3478",
    "username": "issued-user",
    "credential": "issued-credential"
  }
]
```

```sh
node tools/multiplayer/server.mjs --ice-config /path/to/ice-servers.json
```

The example hosts are placeholders.
The browser needs the configured ICE credentials to use the service.
Do not publish permanent TURN credentials as a public static asset.
For a public deployment, supply appropriate issued credentials through the service.

The session API accepts `forceRelay: true` for a relay-only check with a real TURN server.
No TURN server is installed by this proof, and TURN success must not be inferred from direct-connection success.

## Next integration step

Connect this session to the WASM game worker, which remains the only writer of game state.
Start with two-browser Corneria movement, authoritative self-state, numbered controls, and verified prediction.
Then add weapons, damage, deaths, vehicle changes, scoring, and the four-player acceptance checks.

Pilots, crew rules, duplicate appearance hues, and the eight-player Venom mode remain governed by
[ADR 0001](../../docs/adr/0001-lan-versus-multiplayer.md).
See the [browser WebRTC plan](../../docs/plans/browser-webrtc-multiplayer.md).
