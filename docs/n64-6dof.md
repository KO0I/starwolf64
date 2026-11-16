# Build and test the experimental N64 6DOF ROM

Use the private inputs and Python dependencies from [ed64plus.md](ed64plus.md).
This experiment accepts the audited US 1.1 cartridge builds listed in
`tools/build_6dof_rom.py`, including the updated Wolfen model.

## Fly the experiment

1. Copy `starwolf64-6dof.z64` to your working ED64 Plus SD card.
2. Launch it with EEPROM4K selected. Flight starts in the normal mode.
3. During active Arwing flight, wait until radio messages, incoming calls and
   voices have stopped, then tap C-right.
4. Move the stick horizontally to roll. Release it to retain the bank.
5. Move the stick vertically to pitch. The vertical axis matches the checkpoint.
6. Tap C-right again while communications are idle to return to normal flight.
7. Before powering off, press Reset and wait for the cartridge menu to finish
   writing the save.

Enabling uses `NA_SE_MAP_WINDOW_OPEN`; disabling uses
`NA_SE_MAP_WINDOW_CLOSE`. The flag resets when the ROM boots and adds no fields
to the save file.

On rails, the ship stays inside the stage corridor. All-range mode permits
pitching through vertical and keeps the camera in the ship's orientation.
Original terrain collisions, ceilings and forced boundary U-turns remain.
The attitude indicator has not been ported.

Avoid combining the toggle and boost/brake in the same instant. This first
attempt handles the toggle in movement, after those two actions for that frame.

## Rebuild the ROM

Use the installed VR4300 GCC toolchain. The default location is
`/opt/libdragon/bin`; set `N64_TOOLCHAIN` for another installation with the
`mips64-elf-` programs.

```sh
make rom-6dof
```

This builds the standard ROM first, then writes
`build/rom/starwolf64-6dof.z64` and its JSON report.
Use `make roms` to request both variants explicitly.
Override `ROM_OUT` to change the output directory.

The underlying command remains available for an already prepared standard ROM:

```sh
python3 -B tools/build_6dof_rom.py --input-rom build/rom/starwolf64.z64 --output build/rom/starwolf64-6dof.z64 --build-dir build/rom/6dof
```

It refuses an unreviewed input hash, different original hook instructions,
a live voice-filter allocation, or a module larger than its 4 KiB reservation.
The report records source hashes, linked symbols and the complete ROM hash.

## Check the controls in an emulator

Use Node with Chromium installed. The checker downloads EmulatorJS 4.2.3
runtime files from its CDN and disables Expansion Pak RAM.

```sh
make test-rom-6dof
make test-rom-6dof-allrange
```

The on-rails check navigates to Corneria using controller inputs. It checks
stock and 6DOF pitch direction, persistent roll beyond 90 degrees, camera roll,
and restoration of stock steering. It writes no emulated RAM.

The all-range check selects Training using controller inputs, then sets the
course-end position and requests the game's original all-range transition.
The engine performs its normal cutscene and allocation. Subsequent pitch,
roll and toggle assertions use controller input. Its JSON explicitly records
these setup writes. This is a focused test, not a full Training-course test.
For a natural course run, invoke the checker directly with
`--all-range --natural-training --rom build/rom/starwolf64-6dof.z64`.

Both checks passed on the experimental candidate with 4,194,304 bytes of RAM.
The all-range run turned beyond vertical and retained bank after releasing
the stick. Terrain collisions still occurred during the test.
Physical N64 boot, cache behavior, sustained play and SD save persistence
remain unverified.

Implementation and memory ownership are documented in
[tools/n64/README.md](../tools/n64/README.md).
