#!/usr/bin/env python3
"""Build the optional dialogue-blip mod for native Starship and US 1.1 ROMs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import wave
import zipfile

import numpy as np

from comptool import calculate_crcs
from rom_patch import create_patch
from voice_blips_bank import approved_bank
from voice_blips_build import build_replacements
from voice_blips_catalog import build_catalog
from voice_blips_codec import encode, loop_state
from voice_blips_native import native_resources, write_archive
from voice_blips_verify import verify_native, verify_rom
from voice_blips_rom import BASE_NAME, BASE_SHA1, build_rom
from voice_blips_sequence import (expert_program, expert_sequence, install_sequence,
    lookup_order, narration_sequence, patch_starwolf_runtime)

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def targets(value):
    values = value.split(',')
    if not values or len(set(values)) != len(values) or set(values) - {'native', 'rom'}:
        raise argparse.ArgumentTypeError('Choose native, rom, or native,rom')
    return values


def starwolf_extras(replacements, report, catalog, sequence):
    bank = approved_bank(ROOT, 'vitzy')
    encoded = encode(bank.pcm)
    replacements[3, 123] = dict(data=encoded.data, frames=encoded.frames, book=encoded.book,
        order=encoded.order, predictors=encoded.predictors, loop_state=loop_state(encoded, 0),
        template_slot=5, region_tunings={'normal': 1.0, 'high': .5})
    report['expert_bank'] = dict(clips=16, frames=encoded.frames, encoded_bytes=len(encoded.data),
        provenance=list(bank.provenance))
    fox_ids = {a['id'] for a in report['assignments'] if a['profile'] == 'fox'}
    programs = {event['id']: expert_program(event, sequence) for event in catalog['events'] if event['id'] in fox_ids}
    narration_path = ROOT / 'assets/audio/chatter/narrator.wav'
    bank_manifest = json.loads((ROOT / 'assets/audio/chatter/bank.json').read_text())
    narrator = next(p for p in bank_manifest['characters'] if p['name'] == 'narrator')
    if digest(narration_path.read_bytes()) != narrator['sha256']:
        raise ValueError('Full narrator differs from its approved source')
    with wave.open(str(narration_path)) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 32000):
            raise ValueError('Expected full mono 32000 Hz narrator PCM')
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
    encoded = encode(pcm)
    replacements[1, 0] = dict(data=encoded.data, frames=encoded.frames, book=encoded.book,
        order=encoded.order, predictors=encoded.predictors, loop_state=loop_state(encoded, 0),
        loop=False, region_tunings={'normal': 1.0})
    ticks = round(len(pcm) / 32000 * 96)
    report['narration'] = dict(mode='full_reversed', frames=len(pcm), seconds=len(pcm) / 32000,
        encoded_bytes=len(encoded.data), source_sha256=narrator['sha256'], ticks=ticks)
    sequence = narration_sequence(sequence, ticks)
    sequence, mapping = expert_sequence(sequence, programs, lookup_order(ROOT))
    return sequence, mapping


def publish(output, game_set, files, report, pointer_name='latest.json'):
    output.mkdir(parents=True, exist_ok=True)
    hashes = {name: dict(sha256=digest(data), bytes=len(data)) for name, data in sorted(files.items())}
    identity = digest(json_bytes(dict(artifacts=hashes, report=report)))[:16]
    folder = game_set + '-' + identity
    destination = output / folder
    report['artifacts'] = hashes
    files = dict(files, **{'report.json': json_bytes(report)})
    with tempfile.TemporaryDirectory(prefix='.voice-blips-', dir=output) as temporary:
        staging = Path(temporary) / folder
        staging.mkdir()
        for name, data in files.items():
            (staging / name).write_bytes(data)
        if destination.exists():
            if any(not (destination / name).is_file() or (destination / name).read_bytes() != data
                   for name, data in files.items()):
                raise ValueError('Existing artifact identity has different contents')
        else:
            os.replace(staging, destination)
        pointer = Path(temporary) / pointer_name
        pointer.write_bytes(json_bytes(dict(directory=folder, report='report.json', artifacts=hashes)))
        os.replace(pointer, output / pointer_name)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['inventory', 'build'])
    parser.add_argument('--game-set', choices=['starfox64', 'starwolf64'], required=True)
    parser.add_argument('--targets', type=targets, default=['native', 'rom'])
    parser.add_argument('--input-rom', type=Path, help='Prepared Starwolf ROM; original cast uses verified US 1.1')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    output = (args.output or ROOT / 'build/dialogue-blips' / args.game_set).resolve()
    try:
        original = (ROOT / BASE_NAME).read_bytes()
        if hashlib.sha1(original).hexdigest() != BASE_SHA1:
            raise ValueError('Expected verified original US 1.1 ROM')
        export = json.loads((ROOT / 'audio_data/manifest.json').read_text())
        archive_hash = digest((ROOT / 'sf64.o2r').read_bytes())
        if archive_hash != export['source']['sha256']:
            raise ValueError('Audio export differs from original archive')
        roster_path = ROOT / 'assets/audio/voice-blips/rosters.json'
        roster = json.loads(roster_path.read_text())
        catalog = build_catalog(ROOT)
        report = dict(format='starship-dialogue-blips-v1', game_set=args.game_set,
            runtime='Starship with VoiceBlips support from mods/dialogue-blips',
            inputs=dict(base_rom_sha256=digest(original), archive_sha256=archive_hash,
                roster_sha256=digest(roster_path.read_bytes())),
            hardware_verified=False, codec='N64 codec-0, 4-bit ADPCM, zero predictor book',
            driver='Original note timing and completion with reusable looped sixteen-clip trains')
        files = {'catalog.json': json_bytes(catalog)}
        if args.command == 'inventory':
            report['status_counts'] = {status: sum(e['status'] == status for e in catalog['events'])
                for status in ('voiced', 'silent', 'narration', 'control')}
        else:
            print('Resolving and encoding', args.game_set, flush=True)
            replacements, report['coverage'] = build_replacements(ROOT, catalog, roster, args.game_set)
            sequence = original_sequence = (ROOT / 'audio_data/sequences/01_voice.m64').read_bytes()
            mapping = {}
            if args.game_set == 'starwolf64':
                sequence, mapping = starwolf_extras(replacements, report['coverage'], catalog, sequence)
            if 'native' in args.targets:
                resources, report['native'] = native_resources(ROOT, replacements, sequence, args.game_set, mapping)
                report['native_verification'] = verify_native(ROOT, resources, replacements, sequence)
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / 'addon.o2r'
                    write_archive(path, resources)
                    files[f'zz-voice-blips-{args.game_set}.o2r'] = path.read_bytes()
            if 'rom' in args.targets:
                source = args.input_rom or (ROOT / 'build/dialogue-blips/inputs/starwolf64.z64'
                    if args.game_set == 'starwolf64' else ROOT / BASE_NAME)
                if args.game_set == 'starfox64' and source.read_bytes() != original:
                    raise ValueError('Original cast requires the verified original ROM')
                source_bytes = source.read_bytes()
                report['inputs']['input_rom_sha256'] = digest(source_bytes)
                print('Repacking cartridge audio', flush=True)
                rom, report['rom'] = build_rom(source_bytes, ROOT, replacements)
                rom, report['sequence'] = install_sequence(rom, sequence, original_sequence)
                if args.game_set == 'starwolf64':
                    rom, report['runtime_patch'] = patch_starwolf_runtime(rom, mapping, lookup_order(ROOT))
                rom = bytearray(rom)
                struct.pack_into('>II', rom, 16, *calculate_crcs(rom))
                report['rom_verification'] = verify_rom(ROOT, rom, replacements, sequence)
                files[f'{args.game_set}-blips.z64'] = bytes(rom)
                files[f'{args.game_set}-blips.patch.json'] = create_patch(original, rom)
                report['rom']['padded_file_bytes'] = len(rom)
            files['expert-mapping.json'] = json_bytes(mapping)
        destination = publish(output, args.game_set, files, report,
            'inventory.json' if args.command == 'inventory' else 'latest.json')
        print(destination)
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f'voice-blips: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
