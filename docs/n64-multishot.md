# N64 multi-shot

Both cartridge builds include the multi-shot upgrade. The experimental build
also includes 6DOF flight and its attitude indicator.

## Pick up and use the upgrade

A blue pickup with a white M increases target capacity from one to two, then
three. Hold A to charge and acquire targets. Press A again to fire one homing
charge shot at each retained target. Numbered markers show acquisition order;
the marker at the current capacity is yellow.

Press B with a pending lock to send one homing bomb to the most recently
acquired target. It consumes one bomb and uses the original reserved bomb slot.
Collecting an M does not add a bomb.

While capacity is below three, 20% of silver-ring enemy drops become M pickups.
Laser drops also become M pickups when the player already has hyper lasers.
Ordinary bombs remain bombs. The upgrade supports single-player Arwing and
Landmaster gameplay, excluding Training, Aquas and turret mode.

Stage changes clear pending locks and transient item/shot ownership while
retaining capacity. Death and new-game menu paths reset capacity to one.
Actor slot reuse invalidates old target identities. A full projectile pool
leaves the pending volley intact.

## Build

Use the private inputs described in [ed64plus.md](ed64plus.md).

    make roms

The asset/dialogue build produces an audited intermediate at
`build/rom/standard/starwolf64-audited.z64`. Both gameplay variants start from
that same intermediate. Outputs are `build/rom/starwolf64.z64` for standard
flight and `build/rom/starwolf64-6dof.z64` for the 6DOF toggle. Each has a JSON
report containing the input/output hashes, symbols, hooks and source hashes.

The underlying gameplay builder accepts an audited intermediate directly:

    python3 -B tools/build_6dof_rom.py --input-rom build/rom/standard/starwolf64-audited.z64

Add `--standard-flight` and an explicit output path to request standard flight.

## Verify

    python3 -B tools/test_multilock_rom.py
    python3 -B tools/test_flight_bounds_rom.py
    make test-rom-multilock
    make test-rom-flight-bounds

The host checks compile the production ROM adapters against fixed-layout
fixtures. They cover drop probabilities, exclusions, collection, generation
reuse, stock-shot migration, per-target firing, full-pool behavior, bombs,
resets and the 6DOF envelope.

The emulator checker uses EmulatorJS 4.2.3 and Chromium with Expansion Pak RAM
disabled. It navigates to Corneria, then declares enemy fixtures in emulated
RAM. The original actor death/drop, item collection, charge/search, firing,
homing and impact paths execute in the ROM. The checker does not write
capacity, item tags, target locks or shot bindings. Its JSON records fixture
writes and identifies the tested ROM by SHA256.

The `--bounds` option on `tools/check_6dof_rom.mjs` positions the craft outside
stock limits but inside the expanded envelope, then uses C-right to test the
return and directional flags. `--all-range --bounds` checks the ceiling-only
variant. Without `--bounds`, the on-rails control check writes no emulated RAM.

For workspaces with long paths, use a short temporary directory for Chromium:

    TMPDIR=/a/short/writable/path node tools/check_multilock_rom.mjs --rom build/rom/starwolf64-6dof.z64

Static checks cover all 44 scene allocations. Emulator checks exercise selected
gameplay paths, not a full campaign. Physical N64/ED64 Plus execution and SD
save persistence remain unverified.

## Implementation and design decision

The original ROM keeps its fixed object layouts: actors are 0x2F4 bytes,
items 0x6C bytes, and player shots 0x70 bytes. Extra generations, locks,
item tags, shot bindings and captured view positions live in a sidecar state
block. No original pool or structure is resized.

| Storage | Address | Limit |
| --- | --- | --- |
| Flight code/state and installer bridge | 0x80137E90 | 4096 bytes |
| Existing permanent radio loader | 0x8017A040 | 156 bytes |
| Multi-shot code, state, graphics and bounds adapter | 0x8027D000 | 16384 bytes |
| Original graphics buffers begin | 0x80281000 | Unchanged |

Game_Initialize installs both payloads after loading permanent radio data and
after the bootstrap thread has retired. The original loader still occupies
132 bytes. Its flight payload occupies 3888 bytes, including a secondary copy
loop. The multi-shot image occupies 12240 bytes, including initialized state,
glyph vertices and zero-filled BSS.

The audited scenes end no higher than 0x8027C7C0, leaving 2112 bytes before the
reservation. The builder rejects scene growth into this region and rejects
payload growth past either linker bound. Stock runtime allocation uses the
separate low memory buffer; the original RSP buffers start at 0x80281000.
Selected scene loads and gameplay have been exercised in the emulator.

The loader writes back data cache lines, invalidates instruction cache lines,
and synchronizes before entering copied code. All later hooks enter resident
adapters directly. The hook manifests contain expected original instructions;
a mismatch aborts the build. Mid-function assembly gates preserve their
original register and delay-slot contracts.

Target selection bypasses the stock single-target scan only for owned shots.
The stock steering, acceleration and collision tail still runs. Owned-shot
impact bypasses the stock loop that clears every actor's locks.

The pickup uses the original sphere display list and ported M vertices.
The glyph size and front/back planes fit the original N64 mesh, and reverse
faces are culled. Target markers retain the original red reticle with ported
number glyphs.

Pstack compared a combined relocated payload with a separate multi-shot
payload. The separate payload preserves the existing Flight state address and
keeps its behavior checks usable. One builder owns both variants, ROM
placement, scene checks, expected hook bytes and CRC generation. All available
review models were from the GPT-6 family, so cross-family judging was
unavailable. Source review and artifact checks supplied the verification.
