.DEFAULT_GOAL := help

.PHONY: localsite help rom rom-standard rom-6dof roms check-rom check-rom-6dof check-roms test-rom-6dof test-rom-6dof-allrange test-rom-multilock test-rom-flight-bounds

PYTHON ?= python3
NODE ?= node
ROM_OUT ?= build/rom
N64_TOOLCHAIN ?= /opt/libdragon/bin
SITE_PORT ?= 8667
SITE_HTTPS_PORT ?= $(SITE_PORT)
WASM_CACHE ?=

help:
	@printf '%s\n' \
	'worktree-status   - report all registered worktree projects' \
	'status-sargasso   - report browser co-op project status' \
	'status-voline     - report selectable browser campaign status' \
	'status-kropotkin  - report reverse ROM project status' \
	'status-malatesta  - report planned couch co-op ROM status' \
	'status-dev        - report shared integration status' \
	'rom-kropotkin     - build reverse ROM in its registered worktree (6DOF on)' \
	'rom-reverse       - alias for rom-kropotkin' \
	'localsite         - build WASM and play over Tailscale HTTPS' \
	'rom               - build standard ROM' \
	'rom-6dof          - build experimental 6DOF ROM (builds standard first)' \
	'roms              - build both ROMs in $(ROM_OUT)/' \
	'check-rom         - verify standard ROM' \
	'check-rom-6dof    - verify 6DOF ROM' \
	'check-roms        - verify all ROMs' \
	'test-rom-6dof     - run 6DOF ROM tests' \
	'test-rom-6dof-allrange - run extended 6DOF ROM tests' \
	'test-rom-multilock - check multi-shot in both ROM variants' \
	'test-rom-flight-bounds - check expanded 6DOF limits and return cues'

rom: rom-standard

rom-standard:
	"$(PYTHON)" -B tools/rom_targets.py standard --output-dir "$(ROM_OUT)" --toolchain "$(N64_TOOLCHAIN)"

rom-6dof: rom-standard
	"$(PYTHON)" -B tools/rom_targets.py 6dof --output-dir "$(ROM_OUT)" --toolchain "$(N64_TOOLCHAIN)"

roms: rom-standard rom-6dof

check-rom: rom-standard
	"$(PYTHON)" -B tools/check_ed64plus.py --rom "$(ROM_OUT)/starwolf64.z64"

check-rom-6dof: rom-6dof
	"$(PYTHON)" -B tools/check_ed64plus.py --rom "$(ROM_OUT)/starwolf64-6dof.z64"

check-roms: check-rom check-rom-6dof

test-rom-6dof: rom-6dof
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --output "$(ROM_OUT)/proof/onrails"

test-rom-6dof-allrange: rom-6dof
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --all-range --output "$(ROM_OUT)/proof/allrange"

localsite:
	"$(PYTHON)" -B tools/wasm/localsite.py --port "$(SITE_PORT)" --https-port "$(SITE_HTTPS_PORT)" --cache "$(WASM_CACHE)"

test-rom-multilock: rom-6dof
	"$(PYTHON)" -B tools/test_multilock_rom.py
	"$(NODE)" tools/check_multilock_rom.mjs --rom "$(ROM_OUT)/starwolf64.z64" --output "$(ROM_OUT)/standard-multilock-proof"
	"$(NODE)" tools/check_multilock_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --output "$(ROM_OUT)/multilock-proof"

test-rom-flight-bounds: rom-6dof
	"$(PYTHON)" -B tools/test_flight_bounds_rom.py
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --bounds --output "$(ROM_OUT)/proof/rail-bounds"
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --all-range --bounds --output "$(ROM_OUT)/proof/allrange-bounds"

.PHONY: worktree-status status-sargasso status-voline status-kropotkin status-malatesta status-dev rom-kropotkin rom-reverse

worktree-status:
	"$(PYTHON)" -B tools/worktree_status.py

status-sargasso status-voline status-kropotkin status-malatesta status-dev:
	"$(PYTHON)" -B tools/worktree_status.py --target "$(@:status-%=%)"

# Resolve the registered branch instead of assuming a sibling directory name.
rom-kropotkin:
	@"$(PYTHON)" -B -c 'import json, subprocess, sys; from pathlib import Path; registry=json.loads(Path("tools/worktrees.json").read_text()); branch=next(t["branch"] for t in registry["targets"] if t["name"]=="kropotkin"); rows=subprocess.check_output(["git","worktree","list","--porcelain"],text=True).split("\n\n"); paths=[row.splitlines()[0].removeprefix("worktree ") for row in rows if "branch refs/heads/"+branch in row.splitlines()]; paths=[p for p in paths if (Path(p)/"Makefile").is_file()]; paths or sys.exit("No registered Kropotkin worktree with a Makefile found"); raise SystemExit(subprocess.call(["$(MAKE)","-C",paths[0],"rom-reverse"]))'

rom-reverse: rom-kropotkin
