# N64 Multilock pickup

Both cartridge targets include the blue smart-bomb-shaped M pickup. Capacity
starts at one, each M adds one reusable target slot, and three is the maximum.
Death and a new campaign restore one slot. Successful stage transitions keep
the capacity; capacity is not written to the save file.

Hold A to charge and sweep across different enemies. Release and press A
again to fire one charge shot at each marked enemy, using the retail firing
control. Lost marks refund their slots and the remaining numbers close gaps.
Each projectile follows its original enemy and incarnation. If that enemy is
lost, the projectile continues forward without acquiring a replacement.

Numbers sit outside the lower-right corner of the red target square. Earlier
slots are red; the final available slot is yellow: 2 at capacity two, or 3 at
capacity three. The second lock tone rises three semitones and the third rises
seven semitones from the original tone. B sends one smart bomb to the last
valid mark, consumes one bomb, and clears the pending volley.

Only enemy drops change. While below capacity three, 20% of spawned silver
rings become M. Enemy laser drops become M when the player already has hyper
lasers. At the cap, the original drops remain. Placed pickups retain their
original behavior. Campaign Arwing and Landmaster gameplay is supported on
rails and in all-range mode. Aquas, Training, versus and turret mode retain
their original behavior.

## Build and check

The private US 1.1 ROM, sf64.o2r and audio_data inputs are the same as the
[ED64 Plus build](ed64plus.md). Both targets need the MIPS toolchain at
/opt/libdragon/bin, overridable with N64_TOOLCHAIN.

~~~sh
make roms
make test-rom-multilock
~~~

The outputs are build/rom/starwolf64.z64 and
build/rom/starwolf64-6dof.z64. The standard asset and dialogue baseline stays
at build/rom/standard/starwolf64-base.z64. The flight patch consumes this
baseline, and Multilock is applied afterward. The builder also accepts a
checked existing flight image:

~~~sh
python3 -B tools/build_multilock_rom.py \
  --input-rom path/to/flight.z64 \
  --output build/rom/starwolf64-6dof-multilock.z64
~~~

The input must match the audited standard assets and either original flight
or the recognized 6DOF patch allocations. Unrelated input modifications,
changed hook instructions, and applying Multilock twice are rejected.
The companion JSON records source and output hashes, all hook/trampoline
addresses, module allocation and the compiled state layout.

The emulator check boots the real ROM with 4 MiB RDRAM and uses normal
controller input for charging, firing and bombing. Focused scenarios seed
enemy and item state, including search projectiles and collection flags;
the proof JSON records those fixtures. Capacity, acquisition and volley
counters are changed by the cartridge code. Screenshots and native display
commands check the red numbers and yellow final slot. The check also covers
duplicate prevention, cap/refund, enemy incarnation changes, separate
projectiles, the single last-target bomb, and reset on death.

These are focused emulator checks, not a complete campaign or a physical
N64/ED64 Plus test. Save persistence is not tested.

## Cartridge allocation

The patch uses stock object sizes, with compile-time offset/size assertions.
Upgrade flags, pending marks, actor generations and projectile identities live
in a separate state block. No retail array stride or player allocation grows.

The module occupies the aligned interior 0x8015b320..0x8015f310 of the unused
retail RMON IO stack. The exact rmonIOStack declaration is in
src/libultra/rmon/rmonmisc.c. Retail startup does not start that debug thread.
A checked, unused 416-byte rmonMain code allocation at 0x8002e040 holds the
lazy loader. Enabling development RMON is incompatible with this allocation.

The loader copies the complete initialized module, writes back the data
cache, invalidates the instruction cache, and dispatches to the selected
wrapper without changing the original call arguments or return address.
The linker enforces the RAM limit. Every displaced instruction pair is
verified against the original ROM and replayed by its trampoline.
The builder preserves an existing flight module's full declared ROM extent,
including trailing zero state, before allocating Multilock.

The graphics wrappers capture each target's camera position only in the
normal draw pass. Capturing reflected water passes would replace the valid
positions with the renderer's unset-position marker and hide the numbers.
The retail gReflectY field is a signed 16-bit value at 0x80161410.
