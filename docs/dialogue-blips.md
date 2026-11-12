# Dialogue blips

This optional mod replaces recorded dialogue with short character clips in both native Starship and a standalone US 1.1 ROM. It supports the original Star Fox cast and Starwolf64. Each voice bank has sixteen distinct clips. Starwolf64 keeps the approved Wolf, Panther, Kami, Krystal, and Expert Vitzy clips, including Krystal’s lower-fidelity processing.

The builder covers 725 recorded dialogue events. Of these, 724 have ordinary dialogue text and one is an unused recording, ID 20256. Another 54 text entries have no recorded voice. Their existing silent or training-beep behavior remains intact. Thirty-two recordings have no reliable speaker attribution. Each receives clips derived from its own source recording, labelled by source ID. The coverage report preserves the evidence and every assignment.

Original Star Fox retains its complete narration. Starwolf64 plays the complete reversed narration, about 62 seconds. Music and non-vocal sound effects remain intact, including the radio crackle and chirps.

The builder requires Python 3, NumPy, and SciPy. Build from this worktree after supplying its verified original US 1.1 ROM, `sf64.o2r`, and the matching `audio_data` export. The Starwolf build additionally needs the prepared Starwolf ROM. It defaults to the isolated snapshot at `build/dialogue-blips/inputs/starwolf64.z64`. Use `--input-rom` to select another prepared Starwolf input with the supported audio and dialogue layout.

```sh
python3 tools/voice_blips.py inventory --game-set starfox64
python3 tools/voice_blips.py build --game-set starfox64 --targets native,rom
python3 tools/voice_blips.py build --game-set starwolf64 --targets native,rom
```

Each build prints its release directory under `build/dialogue-blips/<game-set>/`. `latest.json` identifies the current playable release. Inventory commands update a separate `inventory.json` pointer. A release contains the ROM, a JSON delta compatible with `browser/rom-patch.mjs`, a native O2R add-on, the complete catalog, Expert mappings, and a coverage and storage report. Files are validated in memory before publication. Successful results live in immutable directories; the current-release pointer changes only after the complete requested result succeeds. Repeating the same build reproduces its artifacts and report.

For native play, build Starship from this branch and install the generated `zz-voice-blips-<game-set>.o2r` in its `mods` directory. Use one blip edition at a time and restart after installing or removing it. Keep the Starwolf character mod installed when using the Starwolf edition. The runtime loads mod archives in filename order, allowing the `zz-` add-on to override the Starwolf voice lookup. The ordinary voice-volume control applies. The audio menu displays that the blip mod is loaded and suppresses the older crew PCM player.

The standalone `.z64` contains its playback and clips. It needs no WAV files or external chatter player. Disable the older external crew-chatter overlay if using an existing browser page that adds that player. The generated JSON delta reconstructs this ROM from the unmodified US 1.1 base. Original recordings remain available in the source archive; this optional ROM removes the replaced speech payloads.

Measured voice-bank storage for the verified builds is:

| Edition | Added encoded clips and narration | Free space in the original voice-bank range | Padded ROM file |
| --- | ---: | ---: | ---: |
| Star Fox 64 | 2,590,830 bytes | 2,768,560 bytes, about 2.64 MiB | 16 MiB |
| Starwolf64 | 3,754,170 bytes | 1,674,752 bytes, about 1.60 MiB | 16 MiB |

The native add-ons are about 1.25 MiB and 1.93 MiB compressed. They do not shrink the original base archive. ROM free space is distinct from the padded ROM file size. The report also accounts for soundfont metadata and Starwolf’s extended sequence and routing code.

The cartridge driver cycles a shared sixteen-clip train while preserving the original note durations, voice IDs, and completion behavior. It restarts when a new voice event starts. This cadence follows the original voice sequence rather than individual text glyphs. The driver comparison confirmed that repeatedly restarting the logical voice prevents ordinary completion.

The converter uses codec-0 N64 ADPCM with a valid zero predictor book. All encoded banks retain sixteen distinct decoded clips and pass a minimum 18 dB signal-to-noise check against their source trains. The actual game decoder is the codec test oracle. The writers share the exact encoded samples, predictor books, and logical endpoints.

Verification is available through:

```sh
python3 -m unittest discover -s tools -p 'test_voice_blips*.py' -v
python3 tools/check_voice_blips_native.py --game-set starwolf64 --engine-assets /path/to/starship.o2r --output build/dialogue-blips/native-proof
node tools/check_voice_blips_browser.mjs --rom /path/to/starwolf64-blips.z64 --output build/dialogue-blips/rom-proof --voices 2050,2020,2030,2040,2220,20256
```

The native probe requires Linux, GDB, Xvfb, and a compiled `build-native/Starship`. It creates a fresh session for each run and captures the actual engine’s PCM before the legacy mixer. The browser probe uses a private local server, Chromium, and EmulatorJS 4.2.3. Both `mupen64plus_next` and `parallel_n64` were exercised. It reads game state for assertions and never instantiates the external chatter player. Generated proofs remain under `build/dialogue-blips/run/` in this worktree. [The verification record](plans/dialogue-blips-verification.json) identifies the final releases, input checks, source fingerprints, and playback evidence.

Physical N64 hardware has not been tested. The software checks establish emulator and native-engine behavior; cartridge hardware compatibility remains unverified.
