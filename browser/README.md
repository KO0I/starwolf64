# Play Starwolf64 in a browser

Choose your own unmodified Star Fox 64 US v1.1 ROM, then press Play. The browser verifies the ROM, reconstructs the unchanged assets, applies the mod, and runs EmulatorJS 4.2.3 with mupen64plus_next.

The ROM stays on your device. The public site contains the emulator interface and a delta patch. It contains neither the base ROM nor a complete modified ROM. The hosted patch stores only bytes that differ after the browser reconstructs the original expanded segments. The finished game must match the build's SHA-256 digest.

Extract ZIP archives first. The file picker accepts .z64, .v64, and .n64 byte orders. The normalized base ROM must have SHA-1 09f0d105f476b00efa5303a3ebc42e60a7753b7a.

## Build and export

Put your base ROM at the project root under its existing filename and generate sf64.o2r using the upstream build instructions. Install Pillow for the asset builder if needed.

~~~sh
python3 tools/build_wolfen.py
python3 tools/build_wolfen.py --check
python3 tools/export_browser_site.py
~~~

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
node --test browser/rom-patch.test.mjs
node browser/check-browser.mjs http://127.0.0.1:8643/
~~~

The browser check selects the local base ROM with the real file picker, boots the emulator, checks input and audio, exercises pause and resume, and captures desktop and mobile layouts. It also checks that no ROM is served or uploaded. Supply another base ROM path as the second argument after the URL when needed.

Keyboard, touch, and standard gamepads use the controls below the viewscreen. Save states and game saves are stored in the browser for that site's address.

## Connect the game subdomain

Use play.starwolf64.com for the game. The main site and its existing @ and www records remain unchanged.

In the starwolf64 repository's Settings, Pages, set Custom domain to play.starwolf64.com. This repository-level setting does not change the account's main GitHub Pages site.

In the Squarespace Domains dashboard, open starwolf64.com, then DNS, DNS Settings, and Custom Records. Add this one record:

| Host | Type | Data |
| --- | --- | --- |
| play | CNAME | ko0i.github.io |

Keep all existing @, www, email, and verification records. Use the default TTL. The CNAME target has no repository path and no https:// prefix. A Git submodule is not needed; the game repository has its own Pages deployment.

Enable Enforce HTTPS once GitHub has issued the certificate. DNS changes can take 24 to 48 hours to appear everywhere. To undo the DNS change, remove only the play record.

For an interactive walkthrough, run:

~~~sh
bash tools/setup-domain.sh
~~~

References:

- [GitHub custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [Squarespace DNS settings](https://support.squarespace.com/hc/en-us/articles/360002101888-Edit-your-domain-s-DNS-records)
- [EmulatorJS options](https://emulatorjs.org/docs/options/)
- [coi-serviceworker](https://github.com/gzuidhof/coi-serviceworker)
