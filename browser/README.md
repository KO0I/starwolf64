# Play Starwolf64 in a browser

Choose your unmodified Star Fox 64 US v1.1 ROM, wait for preparation, then press Play. The default browser edition runs the native Starship engine compiled to WebAssembly with WebGL 2. ROM verification, extraction, and mod assembly happen on your device.

The public site contains the engine, extractor, and a mod recipe. It contains no ROM or extracted base archive. Raw .z64, .v64, and .n64 files are supported, along with a ZIP containing exactly one ROM. The normalized ROM must match the known US v1.1 SHA-256 before extraction.

The browser edition includes the current Wolf, Panther, Krystal, Kami, and Vitzy assets, crew HUD, Medusa updates, and Panther title-eye correction. It applies the Starwolf [dialogue-blip add-on](../docs/dialogue-blips.md) after the character mod. Blips use the native audio sequence timing and voice-volume setting. Expert mode uses Vitzy's voice, and the prologue plays the full reversed narration. The older PCM chatter mixer is suppressed while the blip add-on is active.

## Build the browser edition

Prepare the pinned toolchain once:

```sh
python3 tools/wasm/run.py bootstrap
python3 tools/wasm/run.py dependencies
```

Build and export the ROM-free public site:

```sh
python3 tools/wasm/run.py public
python3 tools/export_browser_site.py --domain play.starwolf64.com
python3 browser/serve.py --port 8641
```

Open http://127.0.0.1:8641/. Both export and preview commands default to WASM. The site is written to `build/wasm/site/`. The exporter can package an existing non-preloaded build without compiling it again. Use `--output /path/to/site` for a separate output directory. It refuses to overwrite unrelated files.

Publish only the exported directory. Keep its licenses and `.nojekyll` file. The `--domain` option writes a CNAME. Omit it for project-path hosting. The WASM workflow builds the same package on `starwolf/dev` and uploads it as an artifact. It does not publish it automatically.

## Optional 6DOF flight mod

Tap **C-right** during flight to toggle **6DOF flight**. On a keyboard, use the **Right arrow**. It is off by default, and the browser remembers your choice. Incoming calls and active dialogue keep C-right for radio actions; the toggle is available once messages finish. Holding C-right toggles only once per press.

While enabled, a HUD attitude indicator shows a wireframe outline, a rotating horizon, a fixed craft marker, and a 6DOF label in the same green as the targeting reticle. A faint translucent green fill marks the ground-facing side; the sky-facing side stays clear. It disappears when the mode is disabled.

For Arwings and Wolfens, left/right continuously roll, and releasing the stick holds the roll angle. The camera rolls with the ship through sideways and inverted flight, and holds that orientation when the stick is released. Up pitches toward the craft's top and down toward its underside, including sideways and inverted flight. The native **Invert Y Axis** setting reverses pitch. All-range stages allow full rotation; on-rails stages keep their forward corridor. Shoulder banking and barrel rolls still work. Boost and brake retain their speed controls, with automatic pitch-gesture loops and U-turns disabled while this mod is active. Other vehicles retain their usual controls.

## Refresh assets and audio

After changing mod sources, supply the verified base ROM, `sf64.o2r`, and its matching `audio_data` export, then run:

```sh
python3 tools/wasm/refresh_mod.py
python3 tools/wasm/refresh_mod.py --check
```

The refresh command rebuilds the character mod and native dialogue-blip add-on, applies the add-on last, then compares every reconstructed resource before saving the recipe. Commit the source changes and all files under `assets/wasm/mod/` together. Public export and CI reject changed source inputs until the snapshot is refreshed. CI needs no private ROM or extracted assets.

See [character integration](../assets/characters/INTEGRATION.md), [the WASM build guide](../tools/wasm/README.md), and [snapshot details](../assets/wasm/README.md).

## Play and save

The N64 controller supports a proportional stick, A, B, Start, L, R, Z, a D-pad, and four C buttons. Keyboard controls and standard gamepads also work. Touch gestures and Enable sound resume suspended browser audio. Fullscreen expands the flight deck.

Game saves persist in this browser for the site's address. The WASM player keeps a separate save from the legacy emulator. Choosing another ROM after reloading does not clear the WASM save. The runtime accepts a 512-byte native Starship save through its developer file picker. Browser storage restrictions can prevent persistence; the player reports that failure.

Download game creates a ZIP with your prepared assets and a Python 3 localhost launcher. Unpack it and run `python3 start.py`. Keep the prepared download for your own use. Opening its HTML through file:// is unsupported.

WebGL 2, SharedArrayBuffer, and cross-origin isolation are required. Local preview supplies isolation headers. Static HTTPS hosting uses the included service worker and can reload once on first visit. Chromium gameplay and mobile viewport checks are automated. Actual iPhone Safari behavior and complete campaign play still require device testing.

## Verify the browser build

```sh
python3 tools/test_6dof_flight.py -v
python3 tools/check_6dof_native.py --native-build build-cmake
python3 -m unittest discover -s tools/wasm -p 'test_*.py' -v
node --test tools/wasm/web/zip.test.mjs browser/rom-file.test.mjs browser/rom-patch.test.mjs
node tools/wasm/check-webgl.mjs --site --rom '/path/to/base.z64' --site-invalid --site-download --audio-session --audio-resume --touch --voice-blips --save-persistence --output build/wasm/default-browser-check
```

Add `--six-dof` to the browser check to exercise the optional flight mod in Training, including the C-right toggle, radio gating, the rendered attitude indicator, roll retention, local pitch, its saved preference, and restoring standard controls.

The browser check prepares a local ROM, validates the download, enters Training, exercises touch input, measures audio, verifies voice routing and mute, and reloads to compare persisted save bytes. It rejects upload requests.

## Use the legacy emulator

The previous EmulatorJS player remains available explicitly:

```sh
python3 tools/export_browser_site.py --runtime emulator
python3 browser/serve.py --runtime emulator --port 8642
```

Its export remains `browser/runtime/site/`. Its checks are `browser/check-browser.mjs`, `browser/check-controls.mjs`, and `browser/check-audio.mjs`.

## Connect the game domain

The game is hosted at play.starwolf64.com. The main GitHub Pages site at chipchirp.digital has its own repository and settings.

In the starwolf64 repository's Settings, Pages, set Custom domain to play.starwolf64.com. This repository-level setting leaves the account's main site unchanged.

In the Squarespace Domains dashboard, open starwolf64.com, then DNS, DNS Settings, and Custom Records. Add this record:

| Host | Type | Data |
| --- | --- | --- |
| play | CNAME | ko0i.github.io |

Use the default TTL. The CNAME target has no repository path and no https:// prefix. A Git submodule is not needed; the game repository has its own Pages deployment. Keep unrelated email and verification records.

To send visitors from starwolf64.com to the game, open Website, Domain Forwarding Rules, Add rule:

| Field | Value |
| --- | --- |
| Subdomain | @ |
| Website URL | play.starwolf64.com |
| Redirect | Temporary 302 during setup |
| Path forwarding | Remove paths |

Save the forwarding rule and retain the play CNAME. Squarespace manages the root domain's forwarding records. This rule applies to starwolf64.com, not chipchirp.digital. No change to the www record is required.

Enable Enforce HTTPS for the game repository once GitHub has issued its certificate. DNS and forwarding changes can take 24 to 48 hours to appear everywhere.

For an interactive walkthrough, run:

~~~sh
bash tools/setup-domain.sh
~~~

References:

- [GitHub custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [Squarespace DNS settings](https://support.squarespace.com/hc/en-us/articles/360002101888-Edit-your-domain-s-DNS-records)
- [EmulatorJS options](https://emulatorjs.org/docs/options/)
- [coi-serviceworker](https://github.com/gzuidhof/coi-serviceworker)
