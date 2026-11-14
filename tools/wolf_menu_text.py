"""Text-only STARWOLF branding and magenta palette for the US 1.1 ROM."""
import struct

RANKING_ORIGINAL = b"S T A R F O X     R A N K I N G\0"
RANKING_TITLE = b"S T A R W O L F   R A N K I N G\0"
RANKING_OFFSET = 0x26524
DEFAULT_NAMES_OFFSET = 0xD5928
DEFAULT_NAMES_ORIGINAL = b"FOXPEPSLPFALWLFLONPIGANRBILKAT"
DEFAULT_NAMES = b"WLFFOXSLPFALKRYLONPIGKAMBILKAT"

# Immediate color loads in ranking/name-entry text, map labels and life digits.
MENU_GOLD = (
    (0x7BC, 0x7C0), (0x95C, 0x960), (0xA3C, 0xA40),
    (0xFFC0, 0xFFC4), (0x10848, 0x1084C), (0x10978, 0x1097C),
    (0x11014, 0x11018), (0x113B0, 0x113B4), (0x15CE4, 0x15CE8),
    (0x229F0, 0x229F4), (0x22F80, 0x22F84), (0x24694, 0x24698),
    (0x26380, 0x26384), (0x263F8, 0x263FC),
)
HUD_GOLD = ((0x86E58, 0x86E5C), (0x8832C, 0x88330),
            (0x8B9C8, 0x8B9CC), (0x8F094, 0x8F098))

# The blue shift in each text-only flashing-red draw. Green keeps animating,
# giving the same white-to-magenta pulse. Arrow and engine-glow draws stay intact.
TEXT_BLUE_SHIFTS = (
    0x856C, 0x8628,                           # Press Start / No Controller
    0xD964, 0xD9D8, 0xDA4C, 0xDAC0,          # sound labels
    0xF618, 0xF6AC,                          # data confirmation labels
    0x125CC,                                # handicap labels
    0x13788, 0x139F0, 0x13C48, 0x14154,      # versus options / OK
)


def word(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


def gold_changes(data, pairs):
    for high, low in pairs:
        lui, ori = word(data, high), word(data, low)
        register = lui >> 16 & 31
        if (lui >> 21 != 0x1E0 or lui & 0xFFFF != 0xFFFF or
                ori >> 26 != 13 or ori >> 21 & 31 != register or
                ori >> 16 & 31 != register or ori & 0xFFFF != 0xFF):
            raise ValueError(f"Unexpected text color instructions at {high:#x}")
        yield high, struct.pack(">I", lui), struct.pack(">I", lui & 0xFFFF0000 | 0xFF00)
        yield low, struct.pack(">I", ori), struct.pack(">I", ori | 0xFFFF)


def apply_menu(builder):
    menu = builder.segments["ovl_menu"]
    changes = list(gold_changes(menu, MENU_GOLD))
    changes.append((RANKING_OFFSET, RANKING_ORIGINAL, RANKING_TITLE))
    # The extra WOLF letter uses the old space before 64. Keep both digits clear.
    changes.append((0x818, struct.pack(">I", 0x3C014314), struct.pack(">I", 0x3C01431C)))
    for offset in TEXT_BLUE_SHIFTS:
        instruction = word(menu, offset)
        if instruction >> 26 or instruction & 63 or instruction >> 6 & 31 != 8:
            raise ValueError(f"Unexpected flashing-text instruction at {offset:#x}")
        target = instruction >> 11 & 31
        changes.append((offset, struct.pack(">I", instruction),
                        struct.pack(">I", 0x34000000 | target << 16 | 0xFF00)))
    changes += [
        (0xF884, struct.pack(">I", 0x3C0AFF20), struct.pack(">I", 0x3C0AFF00)),
        (0xF888, struct.pack(">I", 0x354A20FF), struct.pack(">I", 0x354AFFFF)),
    ]
    # Red team letters and versus player numbers, independently of radar colors.
    old = struct.pack(">9i", 255, 0, 30, 30, 179, 30, 0, 67, 255)
    new = struct.pack(">9i", 255, 0, 30, 0, 179, 30, 255, 67, 255)
    changes.extend((offset, old, new) for offset in (0x27BB0, 0x2F5BC))
    changes.append((0x27D0C,
                    struct.pack(">12i", 177, 255, 0, 30, 242, 30, 255, 30, 12, 0, 67, 255),
                    struct.pack(">12i", 177, 255, 0, 30, 242, 0, 255, 30, 12, 255, 67, 255)))
    for offset, original, replacement in changes:
        if len(original) != len(replacement) or menu[offset:offset + len(original)] != original:
            raise ValueError(f"Unexpected original menu text at {offset:#x}")
        menu[offset:offset + len(replacement)] = replacement
    # Existing whole-overlay verification restores all declared changes and
    # compares unrelated bytes with the original ROM.
    builder.menu_color_changes.extend(changes)


def patch_rom(builder, rom):
    if rom[DEFAULT_NAMES_OFFSET:DEFAULT_NAMES_OFFSET + 30] != DEFAULT_NAMES_ORIGINAL:
        raise ValueError("Unexpected original default ranking names")
    builder.hud_text_changes = list(gold_changes(rom, HUD_GOLD))
    builder.hud_text_changes.append((DEFAULT_NAMES_OFFSET, DEFAULT_NAMES_ORIGINAL, DEFAULT_NAMES))
    for offset, original, replacement in builder.hud_text_changes:
        rom[offset:offset + len(replacement)] = replacement


def verify(builder, rom):
    if builder.segments["ovl_menu"][RANKING_OFFSET:RANKING_OFFSET + len(RANKING_TITLE)] != RANKING_TITLE:
        raise ValueError("Ranking title is not STARWOLF")
    for offset, _, expected in builder.hud_text_changes:
        if rom[offset:offset + len(expected)] != expected:
            raise ValueError(f"HUD text is not magenta at {offset:#x}")
