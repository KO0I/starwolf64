# N64 flight patch reference

This module targets the fixed US 1.1 checkpoint candidate identified by
`AUDITED_SOURCES` in `tools/build_6dof_rom.py`. Function addresses and displaced
instructions were checked against that ROM. The host engine is not rebuilt
for N64.

`flight.c` reuses the checkpoint's `src/port/Flight6DOF.h`. It binds sine,
cosine, atan2, smooth-step, matrix and sound calls to the original game.
The only local math replacements are bounded-angle floor and an inline
square root for a unit-vector hypotenuse.

`flight_hooks.S` intercepts movement after the original function prologues.
Enabled movement skips stock steering and resumes the stock movement,
collision and bounds tail. Disabled movement replays the displaced
instructions. The on-rails camera hook overrides roll after stock eye/target
updates. The all-range hook supplies the checkpoint's full craft-frame camera.
Boost and brake gates suppress their automatic aerobatic triggers when enabled.

The HUD hook replaces the return at ROM offset `0x90a70` (RAM `0x8008fe70`).
The original epilogue has already restored RA and SP. A non-linking jump to
the loader sets kind 6; the entry tail-calls `Flight_DrawAttitude`, which
returns directly to the original HUD caller. Caller-saved registers may be
clobbered, and the C function preserves callee-saved registers.

The renderer uses original F3DEX fill rectangles, primitive RGBA and
`G_RM_CLD_SURF` blending. Its green is `(66, 255, 82)`; ground uses one
quarter of the stock HUD fade alpha. World up is projected onto a sphere
so the horizon remains correct through vertical and inverted flight.
The outer ring follows a single-pixel inner boundary. The horizon band uses
a 0.4-unit half-width, and the fixed craft marker has fine center ticks.
The ring, horizon and marker use full HUD alpha. Stock setup 76
at `0x800d4710` establishes graphics state before drawing and restores it
afterward. No textures or new heap allocations are required. The indicator
draws only during enabled, active, single-player Arwing flight with a visible
HUD. Original HUD calls already honor `gShowHud`.

## Memory ownership

| Allocation | Address | Capacity | Owner |
| --- | --- | --- | --- |
| Runtime module and state | `0x80137e90` | 4096 bytes | Retired bootstrap stack |
| Loader | Radio offset `0x1030`, RAM `0x8017a040` | 156 bytes | Retired voice filter |
| Module image | Trailing unused cartridge bytes | Checked at build | ROM builder |

The flight module and installer bridge are 3888 bytes; the radio loader remains 132 bytes.
The linker rejects growth beyond `0x80138e90`, where the idle-thread object
begins. The builder also checks the padded binary size.

The initial bootstrap SP is `0x80138e90`. It must not be overwritten during
boot. Loading occurs at the original Game_Initialize return after its permanent
radio load, on the main thread after startup. In the original ROM, the first `osStartThread` checks
`__osRunningThread` at `0x800c7eb0`, initially zero, and dispatches via
`__osDispatchThread`. Dispatch restores the new thread SP and EPC and exits
with `eret`; it does not save a resumable bootstrap thread. Source searches
find no later references to `gUnusedStack`.

The loader reuses only the former 156-byte voice filter. The standalone
dialogue-audio build has already restored the voice-lookup return and replaced
the former crew gate. Labels at radio offset `0x10cc` remain intact.
The builder requires that exact input and checks the retired filter,
the restored return and the labels before writing.

The loader copies the module using CPU reads from uncached cartridge space.
It writes back D-cache lines with operation `0x19`, invalidates I-cache lines
with `0x10`, and executes `sync` before entering the module.
See the [SDK cache definitions](https://ultra64.ca/files/documentation/online-manuals/man-v5-2/allman52/header/R4300.htm).
Hardware execution remains unverified.

The bootstrap marker is cleared by original startup BSS initialization.
After loading, the four state words are magic, enabled, toggle count and
enabled movement-update count. They are visible to the read-only assertions
in the emulator checker and are not stored in EEPROM.

## Register contracts

Movement and camera hooks enter with `s0 = Player*` after stock prologues.
Original caller return addresses remain in the original stack frames.
The gate saves its hook return address around the C call. Disabled paths
replay both displaced instructions before resuming; enabled movement restores
`f20 = 0` before entering the stock tail.

Boost/brake run before movement and must also initialize the module.
Their auxiliary loader saves `t0-t3`, original `t9` and the hook return address.
It chooses the gate from the callsite before restoring those registers.
It dispatches before modifying `a0-a2`, which contain live original locals.
The original boost branch-likely delay slot and the brake path's `a3 = 5`
assignment are reproduced explicitly.


## Multi-shot and flight envelope

The gameplay builder also installs a separate payload at 0x8027D000, bounded
by the original graphics buffers at 0x80281000. Its 12240 bytes include sidecar
target state, original-layout adapters, pickup/number geometry and the flight
bounds wrapper. The builder checks every scene allocation below this region.
The flight bridge copies it once during installation; subsequent hooks jump
directly to resident code.

See [the port design and verification](../../docs/n64-multishot.md).
The original-ROM ABI is asserted in multilock_abi.h. Hook manifests own the
expected instructions and continuation contracts. The standard variant omits
all 6DOF movement and envelope hooks.
