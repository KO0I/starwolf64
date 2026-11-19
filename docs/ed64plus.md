# Play Starwolf64 on an ED64 Plus

Use the `wolf_rom` branch, starting at `checkpoint_before_lan`
(`d279d7b4`). The first cartridge build uses standard Star Fox 64 flight.
It includes the Wolfen, reviewed characters, portraits and cartridge dialogue.
Both builds include [multi-shot upgrades and power-ups](n64-multishot.md).
The separate experimental build adds 6DOF movement, camera rotation and a
green wireframe attitude indicator with translucent ground shading.
Rival encounters use Fox, Falco, Peppy and Slippy in Arwings, with matching
radio portraits, names and voice blips. The replacement uses the original
Arwing assets inside the existing rival segment allocation.


## Load the ROM

1. Copy `starwolf64.z64` from the local release folder to the SD card you already
   use with your ED64 Plus. Use the same folder as your other N64 ROMs.
2. Insert the SD card and boot your NTSC N64 into the ED64 Plus menu.
3. Select `starwolf64.z64`. If the menu shows a save type, choose
   **EEPROM4K** (512 bytes). The original menu uses L/R to change the save type.
4. Launch the ROM. Check the title, start a game and fly the first stage.
5. After the game has saved progress or an option, press the console's
   **Reset** button to return to the ED64 Plus menu.
6. Wait for the menu to finish writing the save before switching off the console.
7. Power on again, launch the same filename and check that the saved setting or
   progress remains.

The [ED64 Plus instruction manual](https://www.emulation64.fr/pdf/N64%20-%20ED64%20Plus%20%28Anglais%29.pdf)
describes save-type selection and writing saves to SD when returning to the
menu with Reset. Menu wording can vary with firmware. Keep the existing working
SD-card setup.

## Build a candidate

Use Python with NumPy, SciPy and Pillow. Supply your existing private US 1.1
big-endian ROM, `sf64.o2r`, and its matching `audio_data/` export in the project
root. The base ROM SHA-1 must be
`09f0d105f476b00efa5303a3ebc42e60a7753b7a`. Portrait binaries are optional:
the builder can encode the tracked native PNGs and check their manifest hashes.

Run from the repository root:

```sh
make rom
```

The output is `build/rom/starwolf64.z64`. Asset and dialogue intermediates stay
under `build/rom/standard/`. The target verifies the original boot code and
cartridge checksum before publishing the stable ROM filename. It also checks
every scene asset pair against its DMA payload and rejects invalid lengths or
allocations that reach the fixed RAM buffers. Both variants
include the latest Wolfen wing-root anchoring, reduced wing sweep and closed
rear cockpit roof. Each build checks intact and damaged wings in four animation
poses, detached wing meshes, and agreement between cartridge and native models.

Use `make rom-6dof` for the experimental build, or `make roms` for both.
The 6DOF target builds the standard ROM first. Its output is
`build/rom/starwolf64-6dof.z64`.

Override `ROM_OUT` to change the output directory. Set `PYTHON` to a Python
executable with the required packages. The 6DOF build also accepts
`N64_TOOLCHAIN`, defaulting to `/opt/libdragon/bin`.

```sh
make roms ROM_OUT="build/my-roms"
make check-roms
```

The targets perform full rebuilds on each invocation and leave the browser
site and installed native mod unchanged. `make check-roms` builds both ROMs
and runs the container and scene-allocation checks; it does not launch an emulator.

A passing report confirms the original header and boot code are preserved and
the cartridge CRC is correct. It identifies the expected inherited EEPROM
format. It also checks static scene allocations. It does not test saving, runtime
RAM consumption or physical hardware.

For the standalone audio check:

```sh
node tools/check_voice_blips_browser.mjs --rom build/rom/starwolf64.z64 --core parallel_n64 --output build/ed64plus/audio-proof --voices 2050,2020,2030,2040,2220,20256
```

The exporter checks every scene's asset allocation against the original fixed
buffer boundary and writes `build/rom/standard/wolfen.characters.json`. Keep its `scene_memory`
report with the candidate. The ROM file is 16 MiB; this is cartridge storage,
not an Expansion Pak requirement. Standard 4 MiB console memory remains the
target. See [dialogue-blips.md](dialogue-blips.md) for audio details.

The checkpoint candidate passed title and menu navigation, the full Corneria
opening and advancing flight in `parallel_n64` with Expansion Pak RAM disabled.
The running ROM reported 4,194,304 bytes of RAM. Six dialogue voices also passed
playback checks. These checks cover the tested opening, not a complete playthrough.

## Scene-table regression tests

```sh
python3 -B tools/test_n64_scenes.py
```

These cover adjacent asset descriptors whose shared boundary resembles another
asset's start/end pair. Earlier builds corrupted Landmaster loads in Macbeth
and Titania, and an enemy-asset load in Aquas. The exporter now resizes complete
asset descriptors and validates all 44 scene setups.
The failing 6DOF ROM froze at Macbeth's first intro frame with a black screen.
The corrected build completed the original intros and reached advancing
gameplay in Macbeth, Titania and Aquas using 4 MiB in `parallel_n64`. These
focused tests selected the target planet and level in map RAM, then used the
original loader and intro; they did not play the preceding route or full levels.


The rival arrival was also checked in Fortuna in both standard and 6DOF ROMs
with 4 MiB RAM. The test selected Fortuna on the map, let its intro finish,
then advanced only the event clock to the normal warning sequence. The original
engine spawned all four rivals, played their introductions and returned to
active flight.

## Test on the console

Record boot, first-stage play, save retention after Reset and a power cycle,
and any graphical or audio faults. Also try crowded scenes and later stages.
Passing emulator checks does not establish physical ED64 Plus compatibility.

For the separate experimental cartridge build, see [n64-6dof.md](n64-6dof.md).
