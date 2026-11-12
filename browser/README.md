# Play Starwolf64 in a browser

Choose your own unmodified Star Fox 64 US v1.1 ROM, then press Launch. The browser verifies the ROM, reconstructs the unchanged assets, applies the mod, and runs EmulatorJS 4.2.3 with mupen64plus_next.

The ROM stays on your device. The public site contains the emulator interface and a delta patch. It contains neither the base ROM nor a complete modified ROM. The hosted patch stores only bytes that differ after the browser reconstructs the original expanded segments. The finished game must match the build's SHA-256 digest.

The file picker accepts .z64, .v64, .n64, or a ZIP containing exactly one ROM at its root. ZIPs may use stored or DEFLATE compression and must be no larger than 16 MiB. Encrypted files, extra files, directories, links, unsafe paths, ZIP64, split archives, malformed headers, and CRC mismatches are rejected. File names must be valid UTF-8; ASCII names work with older ZIP tools.

Decompression is streamed with bounded input chunks and a strict 12 MiB output limit. The normalized ROM must match the known base ROM's SHA-1 and SHA-256 checksums before emulation. Archive contents are never executed or written to the filesystem. These checks validate an exact ROM rather than perform a general antivirus scan.

## Build and export

Put your base ROM at the project root under its existing filename and generate sf64.o2r using the upstream build instructions. Install NumPy and Pillow for the asset builder if needed.

~~~sh
python3 tools/build_wolfen.py
python3 tools/build_wolfen.py --check
python3 tools/export_browser_site.py
~~~

The build installs the reviewed Wolf, Panther, Krystal, and Kami bodies and pilot heads, plus Vitzy's Expert head. The native Expert fighter also uses her Bill cockpit module. See [character conversion](../assets/characters/INTEGRATION.md) for slot mappings, animation limits, rebuild checks, and credits.

Crew dialogue uses short voiced syllables timed to the text reveal. Wolf uses his original voice lowered three semitones with a bass boost. Panther uses Peppy's voice lowered ten semitones with a bass boost. Kami uses Vitzy's recording lowered three semitones with slower delivery. Krystal uses newly generated English-accent female snippets. Vitzy keeps her own recording at its original base pitch, in the separate Expert pilot slot. Red portrait variants keep the same voice. The prologue plays the full original narration backwards as one continuous recording, stopped when the prologue is skipped or finishes.

The native player mixes the shared 32 kHz PCM bank into Starship's audio output and follows its master and voice volumes. Settings > Audio > Crew chatter switches between chatter and silent crew dialogue. Rebuild the executable and regenerate the native mod together. The browser player reads the dialogue reveal from EmulatorJS and plays the same banks with Web Audio. It follows the browser sound control and the game's Voice Volume setting. Other speakers retain their original voices unless their dialogue text was edited.

The packaged banks and source/processing record live in assets/audio/chatter. To regenerate them from the approved preview working files, run python3 tools/build_crew_chatter.py. The native PCM player is independent of ROM addresses; the browser adapter contains the US v1.1 RAM addresses. Browser chatter requires this web player; it is not embedded in the standalone ROM.

The static site is written to browser/runtime/site. The exporter uses an explicit file list and refuses to overwrite unrelated files. It never copies either ROM, native save files, Python environments, or extracted game archives.

To export with a custom domain:

~~~sh
python3 tools/export_browser_site.py --output /tmp/starwolf64-site --domain play.starwolf64.com
~~~

Fork the repository and copy the export to your own GitHub Pages source branch. Use your own domain in --domain, or omit that option to host under your GitHub Pages project address. The page uses relative asset URLs for both arrangements. Preserve LICENSE.md, the service worker license, and Arwing-source.txt when copying it.

## Preview and verify

Preview exactly the public files:

~~~sh
python3 -m http.server 8643 --bind 127.0.0.1 --directory browser/runtime/site
~~~

The included service worker supplies the isolation headers needed by the threaded core. It reloads the page once on the first visit to HTTPS or localhost.

~~~sh
node --test browser/rom-patch.test.mjs browser/rom-file.test.mjs browser/crew-chatter.test.mjs
node browser/check-browser.mjs http://127.0.0.1:8643/
node browser/check-audio.mjs http://127.0.0.1:8643/
~~~

The browser check selects the local base ROM with the real file picker, boots the emulator, checks input and audio, locates live dialogue RAM, exercises all six chatter banks and pause/resume, and captures desktop and mobile layouts. It also checks that no ROM is served or uploaded. Supply another base ROM path as the second argument after the URL when needed.

The audio check measures the emulator's actual output signal. It verifies that mute resets on refresh, mute lasts through pause/resume within a page session, saved volume survives refresh, and keyboard and sound-button input restore suspended audio. It uses real input events without granting artificial user activation to status reads.

If audio is silent, press Enable sound. Each fresh page load starts unmuted. Mute lasts for the current page session, including pause/resume, and is not remembered after refresh. Other preferences and game saves are preserved. The sound button reflects browser audio suspension. Keyboard and touch controls also resume suspended audio; they preserve the current session's mute setting.

Keyboard, touch, and standard gamepads use the controls below the viewscreen. Save states and game saves are stored in the browser for that site's address.

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
