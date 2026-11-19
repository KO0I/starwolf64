# Run reverse Titania

The experimental branch is `starwolf/reverse-titania`. It replaces Titania's Goras battle with an escort. At launch, choose a Wolfen flight or the original Landmaster approach.

Build the native preview from this worktree:

```sh
python3 tools/preview_reverse_titania.py --native-build /home/amber/proj/Starship/build-cmake
```

The helper reuses the existing native dependencies, compiles this worktree's changed sources, and creates a separate runtime directory. The runtime has its own save, configuration, and portrait archive.

Launch the preview:

```sh
SHIP_HOME=/home/amber/proj/Starship-reverse-titania/build/reverse-titania/runtime /home/amber/proj/Starship-reverse-titania/build/reverse-titania/Starship
```

Choose Titania in the level selector. The original VS panel shows A for Wolfen and B for Landmaster. Press either button to choose and launch. Finish the approach, then destroy the Cornerian fighters before their lasers hit Goras. The escort takes 70 seconds. Player fire can also damage Goras.

If Goras survives, he releases Slippy and the full supplied dialogue plays before departure. If Goras dies, Slippy dies with him. The Great Fox attacks in six-second barrages, then exposes four systems for four seconds. Destroy all four systems to finish that route. ROB64 speaks for the Great Fox.

Run the automated native checks:

```sh
python3 tools/check_reverse_titania.py --native-build /home/amber/proj/Starship/build-cmake --vehicle wolfen
python3 tools/check_reverse_titania.py --native-build /home/amber/proj/Starship/build-cmake --vehicle landmaster
```

The checks use Xvfb and GDB to reach the encounter, exercise real laser collisions, and verify both outcomes. Screenshots and `verification-wolfen.json` and `verification-landmaster.json` are written to `build/reverse-titania`.

This is a native prototype. Dialogue uses subtitles and static portraits. Goras has no portrait, and the reunion uses existing ship models. Browser and ROM builds have not been produced for this branch.
