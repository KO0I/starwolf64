# ADR 0004: Default WASM browser edition

Date: 2026-11-13

The WASM port runs Starship's native game and audio code in a browser. Its earlier frozen mod snapshot predates the completed character, HUD, ship, and dialogue-blip updates. The established export and preview commands still selected EmulatorJS.

`tools/export_browser_site.py` and `browser/serve.py` now default to WASM. `tools/wasm/run.py public` owns compilation, and the WASM exporter owns payload validation and packaging. The explicit `--runtime emulator` option preserves the legacy player. Making only the new build command canonical was rejected because existing export and preview commands would still select the older runtime.

The browser recipe combines the completed character mod with the native Starwolf dialogue-blip add-on applied last. Refreshing compares every reconstructed resource against those actual native outputs. Source hashes reject stale snapshots during public builds and exports without requiring a ROM in CI.

Successful native EEPROM writes synchronously persist the 512-byte save in browser storage. The runtime restores it before game initialization. These saves are separate from legacy emulator saves. ROM assets are prepared again after reload.

The [browser guide](../../browser/README.md) contains the build and verification commands. Chromium verification covers static-host isolation, local ROM preparation, exact native resource comparison, downloads, Training, touch input, normal and Expert blips, mute, voice completion, audio recovery, and save restoration. Physical iPhone Safari behavior remains unverified.
