#!/usr/bin/env python3
"""Apply the reverse campaign's speaker colors without replacing worktree-specific radio code."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = '''    /* The playable crew flies Wolfens; radio static keeps the same allegiance. */
    switch ((s32) gRadioMsgRadioId) {
        case RCID_FOX: case RCID_FOX_RED: case RCID_FOX_EXPERT:
        case RCID_FALCO: case RCID_FALCO_RED:
        case RCID_SLIPPY: case RCID_SLIPPY_RED:
        case RCID_PEPPY: case RCID_PEPPY_RED:
        case RCID_KATT: case RCID_ROB64: case RCID_ROB64_RED: case RCID_ROB64_2:
        case RCID_ROB64_TITLE:
        case RCID_GEN_PEPPER: case RCID_GEN_PEPPER_TITLE: /* Allied Andross in this campaign. */
            sRadioUseRedBox = true;
            break;
        case RCID_WOLF: case RCID_WOLF_2:
        case RCID_LEON: case RCID_LEON_2:
        case RCID_PIGMA: case RCID_PIGMA_2:
        case RCID_ANDREW: case RCID_ANDREW_2:
            sRadioUseRedBox = STAR_WOLF_COLOR;
            break;
        case RCID_JAMES: case RCID_BILL:
        case RCID_ANDROSS: case RCID_ANDROSS_RED: /* Enemy Pepper in this campaign. */
        case RCID_BOSS_CORNERIA: case RCID_BOSS_CORNERIA2: case RCID_BOSS_METEO:
        case RCID_BOSS_AREA6: case RCID_CAIMAN_AREA6: case RCID_BOSS_ZONESS:
        case RCID_BOSS_SECTORX: case RCID_BOSS_SECTORY: case RCID_BOSS_MACBETH:
            sRadioUseRedBox = false;
            break;
    }
'''
MARKER = POLICY.splitlines()[0]


def radio_source(source):
    color = '!VenomMission_IsArena()' if 'VenomMission_RadioPortrait' in source else 'true'
    policy = POLICY.replace('STAR_WOLF_COLOR', color)
    if MARKER in source:
        if source.count(MARKER) != 1 or policy not in source:
            raise ValueError('Unrecognized existing radio color policy')
        return source
    anchor = '    if ((radioPortraitTex != NULL) && (gRadioPortraitScaleY != 0.0f)) {'
    if source.count(anchor) != 1:
        raise ValueError('Radio portrait draw boundary is not unique')
    return source.replace(anchor, policy + anchor, 1)


def titania_source(source):
    if 'bool redBox;' in source:
        if 'if (line->redBox)' not in source:
            raise ValueError('Titania speaker color is declared but not drawn')
        return source
    declaration = '    s32 portrait;\n} ReverseTitaniaLine;'
    if source.count(declaration) != 1:
        raise ValueError('Unrecognized Titania dialogue structure')
    source = source.replace(declaration, '    s32 portrait;\n    bool redBox;\n} ReverseTitaniaLine;', 1)
    end = source.index('static f32 sRTFighterHitbox')
    data, rest = source[:end], source[end:]
    allied = {'Andross', 'Wolf', 'Panther', 'Kami', 'Krystal', 'Leon', 'Pigma', 'Andrew', 'Katt'}
    rows = re.compile(r'(\{\s*"([^"\n]+)",\s*"(?:[^"\\]|\\.)*",\s*(?:RCID_[A-Z0-9_]+|-1))\s*\}')
    data, count = rows.subn(lambda m: m[1] + ', ' + ('true' if m[2] in allied else 'false') + ' }', data)
    if count != 23:
        raise ValueError(f'Expected 23 Titania dialogue rows, found {count}')
    source = data + rest
    old = '    gDPSetPrimColor(gMasterDisp++, 0, 0, 20, 25, 55, 210);'
    if source.count(old) != 1:
        raise ValueError('Unrecognized Titania dialogue background')
    return source.replace(old, '''    if (line->redBox) {
        gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 25, 25, 170);
    } else {
        gDPSetPrimColor(gMasterDisp++, 0, 0, 20, 25, 55, 210);
    }''', 1)


def source_worktrees():
    output = subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], cwd=ROOT, text=True)
    for record in output.strip().split('\n\n'):
        fields = dict(line.split(' ', 1) for line in record.splitlines() if ' ' in line)
        path = Path(fields['worktree'])
        if 'prunable' not in fields and (path / 'src/engine/fox_radio.c').is_file():
            yield path


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-worktrees', action='store_true')
    parser.add_argument('--worktree', action='append', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write the preflighted changes; default checks only')
    args = parser.parse_args()
    if args.all_worktrees and args.worktree:
        parser.error('Choose --all-worktrees or explicit --worktree paths')
    paths = list(source_worktrees()) if args.all_worktrees else [p.resolve() for p in (args.worktree or [ROOT])]
    plans, report = [], []
    script = Path(__file__).read_bytes()
    for root in paths:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=root, text=True).strip()
        changes = []
        for relative, transform in [('src/engine/fox_radio.c', radio_source),
                                    ('src/overlays/ovl_i5/reverse_titania.inc', titania_source)]:
            path = root / relative
            if not path.exists():
                continue
            before = path.read_bytes()
            after = transform(before.decode()).encode()
            if before != after:
                plans.append((path, before, after))
                changes.append(relative)
        path = root / 'tools/sync_radio_colors.py'
        before = path.read_bytes() if path.exists() else None
        if before != script:
            if before is not None:
                raise ValueError('Existing synchronizer differs: ' + str(path))
            plans.append((path, before, script))
            changes.append('tools/sync_radio_colors.py')
        report.append(dict(worktree=str(root), branch=branch, changes=changes))
    for path, before, _ in plans:
        if (path.read_bytes() if path.exists() else None) != before:
            raise RuntimeError('Worktree changed after preflight: ' + str(path))
    if args.apply:
        output = ROOT / 'build/radio-colors'
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = [dict(path=str(p), before=base64.b64encode(b).decode() if b is not None else None,
                       before_sha256=digest(b), after_sha256=digest(a)) for p, b, a in plans]
        (output / ('backup-' + stamp + '.json')).write_text(json.dumps(backup, indent=2) + '\n')
        for path, before, after in plans:
            if (path.read_bytes() if path.exists() else None) != before:
                raise RuntimeError('Worktree changed before write: ' + str(path))
            path.write_bytes(after)
        (output / 'worktrees.json').write_text(json.dumps(report, indent=2) + '\n')
    for item in report:
        action = 'updated' if args.apply and item['changes'] else 'needs update' if item['changes'] else 'current'
        print(f"{item['branch']}: {action}" + (' [' + ', '.join(item['changes']) + ']' if item['changes'] else ''))
    print(f'{len(paths)} source worktrees; {len(plans)} file updates' + (' applied' if args.apply else ' pending'))
    return 0 if args.apply or not plans else 1


if __name__ == '__main__':
    raise SystemExit(main())
