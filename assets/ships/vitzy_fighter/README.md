# Fly Vitzy's fighter

Build the mod assets and native executable from the repository root:

~~~sh
python3 tools/vitzy_fighter.py
python3 tools/build_wolfen.py
cmake --build build-cmake -j 4
~~~

Choose Expert mode in the native game. Vitzy replaces the James / sunglasses pilot slot. Normal mode keeps Wolf. The former Vitzy preview checkbox has been removed.

Vitzy's Bill-derived hull is 30% larger than its first version, with a uniform scale of 1.04 instead of 0.8. The Wolfen cockpit and Slippy placeholder head keep their original sizes. Broken wings retain their inner sections.

Vitzy's engine is pink on planets and in space. Her single and twin lasers are yellow, including their charge glow; hyper lasers retain the original blue material. Other Star Wolf fighters use pink exhaust in space and retain their existing planet exhaust. The original blue engine palette remains available for Arwings.

The private resources use `ships/vitzy_fighter/`. Bill and Katt keep their original ship resources. The native James cutscene ship also uses Vitzy's hull.

These Vitzy appearances and color rules currently apply to the native build. The browser patch retains its existing Wolfen setup. Multiplayer pilot and ship selection remain separate work. Replace the private `HeadDL` build source in [vitzy_fighter.py](../../../tools/vitzy_fighter.py) when Vitzy's head model is ready.

Verify the installed resources and capture the native draw calls:

~~~sh
python3 tools/build_wolfen.py --check
python3 tools/vitzy_fighter.py --check
python3 tools/check_vitzy_fighter.py
~~~

The native check needs the configured Ninja build, a C compiler, Xvfb, GDB, ImageMagick's `import`, and permission to attach to its own child game process. It checks Expert and normal ship selection, broken wings, yellow single/twin lasers, blue hyper lasers, charge colors, and planet/space exhaust colors for Vitzy, Wolfen, and Star Wolf NPCs. It also checks the original blue engine palette.

The check writes screenshots and a draw-path report to a fresh temporary directory. The asset manifest records the hull scale, palette, mesh counts, and resource hashes.

[Ship preview](preview.png) and [open cockpit with Slippy placeholder](cockpit-preview.png).
