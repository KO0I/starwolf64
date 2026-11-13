# LAN TCP multiplayer implementation plan

Status: Historical native TCP proposal. Browser-first transport was superseded by the [WebRTC plan](browser-webrtc-multiplayer.md) on 2026-11-12.
The browser connection proof is now authorized; C/WASM gameplay integration remains a later unit.
Date: 2026-11-09
Behavioral contract: [Player-hosted LAN versus multiplayer](../adr/0001-lan-versus-multiplayer.md).
Terminology: [Project glossary](../../GLOSSARY.md).

## Available RFL code

The local C implementation is available at:

- `/home/amber/proj/rfl/rfl_net.c`
- `/home/amber/proj/rfl/rfl_net.h`

The located implementation is UDP. `net_open_socket` creates `SOCK_DGRAM`, and its send/receive paths use `sendto` and `recvfrom`.
The checked C working copies under `/home/amber/proj/rfl*` contained no `SOCK_STREAM`, `TCP_NODELAY`, `SDLNet_TCP`, `TCPsocket`, or `IPPROTO_TCP` matches.
This establishes what is available in those working copies, not what might exist in archives or unexamined history.
No existing RFL C TCP implementation has been verified.

Source fingerprints at inspection time:

| File | SHA-256 |
| --- | --- |
| `rfl_net.c` | `53fd970ae300bb25c5531934ee307fa4ca80b40da9e3635e5f31ee3ae60ea00f` |
| `rfl_net.h` | `7b2bc4f2fc64fddc383c7f44b08eb37778cc5193c85021fb2ea338394fa683b2` |

RFL receives positions chosen by clients and relays poses through the host at a configured 20 Hz.
That source rate is not a selected Starship update rate.
The host also distributes RFL-specific world parameters.
This is not the authoritative controls-and-combat protocol required by Starship.

| Reuse after review | Replace or newly implement |
| --- | --- |
| Host/join flow, peer names and ID conventions | TCP listen, accept, connect, framing, and partial I/O |
| Ping, status, and join/leave event patterns | Bounded per-peer queues and slow-peer policy |
| Nonblocking socket-loop structure | Portable Linux and Windows socket operations |
| Session cleanup patterns | Explicit codec, compatibility handshake, and host-loss detection |
| Source-level lifecycle ideas | Starship controls, snapshots, outcomes, and prediction |

Keep the original RFL checkout unchanged. Any copied code needs recorded provenance and review against the actual source.
Do not carry its raw-struct wire format or its assumptions about loss-free LAN traffic into this implementation.

## Integration constraints

The [build configuration](../../CMakeLists.txt) supports C11 and C++20 and includes port C sources through `GLOB_RECURSE`.
Its `USE_NETWORKING` option currently enables an optional SDL2_net dependency path, not implemented multiplayer gameplay.
The proposed C transport needs explicit Windows socket initialization and linkage.
No SDL2_net dependency is required merely to reuse RFL's socket approach.

[`Graphics_ThreadUpdate`](../../src/sys/sys_main.c) promotes controller state and calls `Game_Update`.
[`Play_Update`](../../src/engine/fox_play.c) updates players, objects, shots, and cameras.
These are existing scheduling boundaries. Network integration must not call the game update twice.

Simulation participation currently shares `gCamCount` with viewport drawing.
Separate player participation, local control-device mapping, and local camera selection.
Physical controller storage remains distinct from eight network player slots.
Audit every player-indexed array, targeting check, projectile owner, score, HUD entry, and respawn path.
Do not blindly replace every four-element array with eight entries.

The game thread remains the only writer of gameplay state.
Networking parses messages into domain data and never edits `gPlayer`, `gActors`, or engine globals directly.
Guests must not run a second authoritative collision, AI, damage, or scoring pass.

## Caller usage and public interface

The sketches below describe future interfaces. They are not production headers, existing functions, or a final ABI.
Complete domain field inventories are required before implementation.

Host and guest setup share one entry point, with role-specific configuration:

```c
MpSession *host = Mp_Open(&host_config, &error);
Mp_Request(host, &select_pilot);
Mp_Request(host, &start_when_ready);

/* Separate guest process. Opening begins a nonblocking connection. */
MpSession *guest = Mp_Open(&join_config, &error);
Mp_Request(guest, &select_pilot);
Mp_Request(guest, &ready);
```

The intended integration replaces the existing frame call site, rather than adding another game update:

```c
MpFrame frame = Mp_BeginFrame(session, &local_controls, monotonic_ns);
MpBridge_ApplyFrame(&frame);

/* Existing call, once. Its play path selects host or guest behavior. */
Game_Update();

MpPublication publication;
const MpPublication *out = MpBridge_CaptureHost(&publication);
Mp_EndFrame(session, out);
```

`MpBridge_ApplyFrame` supplies validated per-player controls on the host.
On a guest it applies received authoritative state and corrections.
The guest play path predicts local movement and updates presentation, while the host play path advances shared gameplay.
`MpBridge_CaptureHost` returns no publication for a guest or a frame without new host state.

The five proposed public operations are:

```c
MpSession *Mp_Open(const MpConnect *config, MpError *error);
MpResult Mp_Request(MpSession *session, const MpRequest *request);
MpFrame Mp_BeginFrame(MpSession *session,
	const MpControls *local, uint64_t monotonic_ns);
void Mp_EndFrame(MpSession *session,
	const MpPublication *host_publication);
void Mp_Close(MpSession *session);
```

The returned frame contains role, phase, status, the assigned local slot, validated controls or host updates, and notices.
Read-only frame buffers remain valid until the next `Mp_BeginFrame`.
Requests cover lobby choices, readiness, host start, and eligible respawn choices.
The session validates whether a request is allowed in the current phase.
Pilot changes are rejected after match start.

This interface hides sockets, byte buffers, wire message tags, stream framing, retry state, and queue management.
Begin/end surround an externally owned game update because the network module does not own the simulation.
They must not become separate caller-managed transport stages.

## Data and ownership

Use a single eight-entry human participant table and a separate pool for AI and other dynamic entities.
Represent these identities separately:

| Identity or state | Meaning |
| --- | --- |
| Session identity | Identifies one hosting lifetime. |
| Match epoch | Changes when a new match begins in the session. |
| Connection identity | Changes when a peer connects again, even if a slot is reused. |
| Player slot | A human participant, independent of controller port and viewport. |
| Pilot identity | Match-fixed roster selection, including preserved originals. |
| Team identity | Multiplayer team membership, independent of campaign ally IDs. |
| Vehicle form and ship variant | Current gameplay form and aircraft appearance. |
| Spawn generation | Changes on respawn or replacement of a vehicle. |
| Dynamic entity identity | Includes a generation so reused object-pool entries cannot inherit old messages. |
| Input sequence and simulation tick | Identify controls and the host step that consumed them. |
| Event sequence and state watermark | Prevent repeated transitions and inconsistent event/snapshot application. |

Distinct C wrapper structs should prevent accidental substitution of slot, pilot, team, and spawn identities.
Validate their values at external boundaries.
Derive all network human capacities from one constant. Do not hand-maintain competing limits.

Local controller input must be captured at the existing committed-input boundary.
`Controller_UpdateInput` promotes the previously read state, while `Controller_ReadData` fills the next state.
Do not sample that next state prematurely or derive press edges twice.
Preserve brief button presses and releases rather than coalescing every control message to its final held state.

The host binds each connection to its assigned participant.
A payload cannot select another player's slot.
Controls and requests carry enough session, match, and spawn identity to reject stale work after a disconnect, rematch, or respawn.

## Selected shape and module map

Start with bounded, nonblocking socket polling on the game thread.
Use fair per-peer and total work budgets so one connection cannot monopolize a frame.
Numeric direct addresses are sufficient for the first proof.
Do not perform blocking hostname resolution or blocking connection attempts on the game thread.

| Proposed file | Responsibility |
| --- | --- |
| `include/multiplayer.h` | Public domain types and the five session operations. |
| `src/port/multiplayer/session.c` | Session/lobby state, control sequencing, validated requests, liveness, and queue policy. |
| `src/port/multiplayer/tcp.c` | Private stream sockets and platform differences. |
| `src/port/multiplayer/codec.c` | Private bounded framing, explicit encoding, and validation. |
| `src/engine/multiplayer_bridge.c` | Sole translation between session domain data and the existing engine. |
| Existing movement and rendering code | Shared movement boundary, authoritative host updates, guest presentation, and local-view selection. |
| Existing resource tooling and lookup | Preserved pilot resources and the authoritative pilot/ship catalog. |

Private transport details stay out of the public header.
Keep one selected implementation. Do not ship simultaneous polling and worker backends.

## TCP protocol obligations

Each connection carries a versioned, length-prefixed message stream.
Use an explicit maximum frame size derived from the encoded schema and supported entity budgets.
Handle fragmented headers, fragmented bodies, multiple frames in one read, partial writes, interruption, EOF, and would-block.

The handshake checks protocol compatibility, supported game/rule versions, and required pilot/ship catalog identities.
Only lobby connections may enter the participant set.
A ready/start/load barrier ensures required assets are available before authoritative match ticks begin.

Encode fields individually with defined widths and byte order.
Do not send native enum sizes, padding, pointers, or raw C structures.
Numeric input and state fields need finite/range validation.
Clients receive state only through their established host connection.

Use independent bounded queues per peer.
A partly written frame must finish before another frame is written.
Data already accepted by TCP cannot be taken back.
Coalesce only completely unsent, self-contained snapshots.
Do not coalesce required button transitions, lifecycle requests, or confirmed outcome events.
If an essential queue cannot accept work or a peer stays backlogged, disconnect that peer without stopping the host.

Begin with self-contained dynamic-world snapshots rather than dependent delta chains.
Include the recipient's own authoritative player state and the last processed input sequence.
RFL's behavior of omitting the recipient's own relayed pose cannot support reconciliation.

Snapshots own absolute replicated health, scores, and entity state.
Confirmed events report transitions and presentation effects.
A guest must not add damage or points again when an event describes state already present in a snapshot.
Use event sequences and snapshot watermarks to suppress duplicate application.

Simulation ticks drive movement, cooldowns, AI, and match outcomes.
Monotonic wall time drives connection attempts, heartbeats, queue age, and disconnect deadlines.
Keep transport liveness separate from evidence that the host simulation is progressing.
A live connection is not proof that gameplay is advancing.

Consider `TCP_NODELAY` for interactive messages.
It does not remove TCP's ordered retransmission delays.
A missing earlier byte can hold up newer state on that connection.
See [TCP's ordered byte-stream service](https://www.rfc-editor.org/rfc/rfc9293.html)
and [TCP socket options](https://man7.org/linux/man-pages/man7/tcp.7.html).

## Prediction gate

Local prediction is required for the approved responsive-control experience, but its state boundary is not yet proven.
Inventory movement fields, global timers, control history, collision inputs, and random or presentation side effects.
A copy of `Player` alone is not established as sufficient.

Extract or isolate a movement step that both host and guest can use.
The guest may replay its own unacknowledged movement inputs after a correction.
It must not replay damage, scoring, AI decisions, resource loads, or audio effects against live engine globals.
Do not introduce full-engine rollback as an assumed shortcut.

Run this investigation alongside the simulation/presentation separation.
The first accepted playable milestone requires verified prediction and reconciliation.
An earlier host/guest replication experiment is an internal checkpoint, not completion of that milestone.

## Incremental delivery and proof

Each unit ends with observable evidence before the next integration step.

| Unit | Work | Exit evidence |
| --- | --- | --- |
| 1. Portable session proof | Adapt reviewed RFL lifecycle ideas to the C TCP session, codec, and a separate-process harness. | Fragmented and combined frames work; malformed frames fail safely; partial writes preserve ordering; memory and queues stay bounded; a slow peer cannot block another; both platforms build and connect. |
| 2. Engine boundary and prediction spike | Separate simulation slots, local input, presentation, and host/guest responsibilities. Inventory replay state. | One local full-screen view retains other participants; rendering does not change authoritative state; local movement can be corrected without duplicated side effects. |
| 3. First two-PC fight | Host/join, lobby, readiness, Corneria Points, firing, damage, score, death, vehicle selection, respawn, and match completion. | Two PCs agree on outcomes, the local guest responds through prediction, and snapshots include authoritative self-state and input acknowledgments. |
| 4. Four-player acceptance | Exercise the complete first milestone with mixed Arwing/Wolfen, operating systems, and connection conditions. | Linux hosts Windows and vice versa; actual Wi-Fi and Tailscale play works acceptably; menus do not pause; guest loss leaves play and respawns running; host loss ends the session. |
| 5. Pilot and ship resources | Integrate preserved originals and the requested replacement roster and variants. | Original pilot keys resolve with the mod loaded; pilots stay fixed; duplicate portrait/marker/laser hues agree across peers; Vitzy is a Star Wolf axolotl with a private pink/magenta Bill fighter; Katt and Bill originals remain unchanged. |
| 6. Eight-player Venom | Finish gameplay-capacity expansion, four-on-four rules, Venom VS loading, and separately budgeted hostile AI. | Slots four through seven work throughout targeting, ownership, HUD, and respawns; AI attacks both teams; human kills score, AI kills do not, and teamkills subtract one; allies never lock; the original campaign mission still works. |

New domain state and protocol identities accommodate eight from the start.
A four-player first proof must not freeze a four-player wire format or reuse controller indices as participant identities.

Loopback processes prove transport behavior but cannot prove cross-platform combat or Tailscale responsiveness.
Record queue age, correction behavior, input-to-authority timing, and the gap between network polls under normal play and stage loading.
No acceptable latency, throughput, or stall limit has been measured in this planning task.
Choose and validate numerical release thresholds during the proof rather than presenting invented results.

Every implementation unit also checks existing offline play.
Exact AI counts, snapshot rates, timeout durations, and presentation palettes remain engineering tuning work.

## Alternatives and synthesis

Two read-only architect candidates were produced, one by `gpt-6-astra` and one by `gpt-6.1-terra`.
Each considered main-thread polling and an I/O worker.

| Criterion | Main-thread polling | Dedicated I/O worker |
| --- | --- | --- |
| Game-state ownership | One thread owns both scheduling and simulation; no gameplay handoff. | Main thread still owns gameplay, but immutable handoffs need explicit ownership and lifetime rules. |
| TCP framing and bounded backpressure | Can satisfy the stream and fairness requirements. | Can satisfy the same requirements independently of frame scheduling. |
| Interface and implementation load | Small domain interface with fewer lifecycle states. | Same domain interface can hide more machinery, including thread startup, saturation, and shutdown. |
| Progress during engine stalls | Polling pauses with engine work. This needs a measured gate. | Socket progress continues, but simulation still stalls and needs a separate progress deadline. |
| First useful proof | Fewer new mechanisms before two-PC combat. | Additional concurrency machinery before the same combat proof. |

Use the Terra candidate as the base.
Carry over the Astra candidate's distinct identity types, immutable frame ownership, incarnation checks, and explicit distinction between connection and simulation progress.
Both candidates require a real prediction-state investigation.

The Astra candidate preferred a worker to keep network progress independent of rendering.
That is a credible alternative, but the current evidence does not establish that its added lifecycle and queue machinery is needed for the first proof.
If observed poll gaps prevent correct liveness or responsive play, return to this design decision and select the worker shape behind the same public interface.
Do not claim that a worker fixes simulation stalls, or keep both implementations in parallel.

No cross-family judge was available in the enabled model pool.
The candidates are different GPT-family model perspectives, not an independent cross-family review.
The Codex overseer compared both against source correctness, state ownership, stream correctness, reader load, and verifiable delivery.

The sketch was screened for transport types leaking into the public API, multiple gameplay writers, duplicate capacity lists, and caller-managed socket stages.
This is a design review, not a compiled or playtested implementation.

## Next implementation unit

After implementation is requested, build the portable TCP session proof and its separate-process stream tests while auditing the engine/prediction boundary.
Keep production stubs and placeholder game behavior out of the planning change.
