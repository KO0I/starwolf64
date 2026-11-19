.DEFAULT_GOAL := help

.PHONY: localsite help rom rom-standard rom-6dof roms check-rom check-rom-6dof check-roms test-rom-6dof test-rom-6dof-allrange test-rom-multilock

PYTHON ?= python3
NODE ?= node
ROM_OUT ?= build/rom
N64_TOOLCHAIN ?= /opt/libdragon/bin
SITE_PORT ?= 8667
SITE_HTTPS_PORT ?= $(SITE_PORT)
WASM_CACHE ?=

help:
	@printf '%s\n' \
	'localsite         - build WASM and play over Tailscale HTTPS' \
	'rom               - build standard ROM' \
	'rom-6dof          - build experimental 6DOF ROM (builds standard first)' \
	'roms              - build both ROMs in $(ROM_OUT)/' \
	'check-rom         - verify standard ROM' \
	'check-rom-6dof    - verify 6DOF ROM' \
	'check-roms        - verify all ROMs' \
	'test-rom-multilock - run cartridge Multilock tests' \
	'test-rom-6dof     - run 6DOF ROM tests' \
	'test-rom-6dof-allrange - run extended 6DOF ROM tests'

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

test-rom-multilock: rom-standard
	"$(NODE)" tools/check_multilock_rom.mjs --rom "$(ROM_OUT)/starwolf64.z64" --output "$(ROM_OUT)/proof/multilock"

test-rom-6dof: rom-6dof
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --output "$(ROM_OUT)/proof/onrails"

test-rom-6dof-allrange: rom-6dof
	"$(NODE)" tools/check_6dof_rom.mjs --rom "$(ROM_OUT)/starwolf64-6dof.z64" --all-range --output "$(ROM_OUT)/proof/allrange"

localsite:
	"$(PYTHON)" -B tools/wasm/localsite.py --port "$(SITE_PORT)" --https-port "$(SITE_HTTPS_PORT)" --cache "$(WASM_CACHE)"
