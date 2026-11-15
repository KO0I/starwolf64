#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(archive_path, export_path, chatter_path):
    exported = json.loads((export_path / 'manifest.json').read_text())
    archive_hash = sha256(archive_path)
    if exported['source']['sha256'] != archive_hash:
        raise ValueError('Audio export does not match the original resource archive')
    with zipfile.ZipFile(archive_path) as archive:
        message_ids = sorted(int(match[1]) for name in archive.namelist()
            if (match := re.fullmatch(r'ast_radio/gMsg_ID_(\d+)', name)))
        table = archive.read('ast_radio/message_table')
        count = struct.unpack_from('<I', table, 64)[0]
        if len(table) != 68 + count * 12:
            raise ValueError('Unexpected native message-table layout')
        lookup_ids = {struct.unpack_from('<i', table, 68 + i * 12)[0] for i in range(count)} - {-1}
    if lookup_ids != set(message_ids):
        raise ValueError('Dialogue assets and native message lookup disagree')
    if 1 not in lookup_ids:
        raise ValueError('Expected the prologue text at message ID 1')

    def category(message_id):
        if 22000 <= message_id <= 22020:
            return 'vocal_reaction_or_item_callout'
        if 23000 <= message_id <= 23032:
            return 'training_prompt'
        return 'dialogue'

    candidates = [message_id for message_id in message_ids if message_id != 1]
    literal_speakers = defaultdict(set)
    pattern = re.compile(r'Radio_PlayMessage\(\s*gMsg_ID_(\d+)\s*,\s*(RCID_\w+)\s*\)')
    for source in sorted((ROOT / 'src').rglob('*.c')):
        for match in pattern.finditer(source.read_text()):
            literal_speakers[int(match[1])].add(match[2])
    observed = set(candidates) & set(literal_speakers)

    chatter = json.loads((chatter_path / 'bank.json').read_text())
    narration = chatter['sources']['narrator']
    narration_resources = {segment['resource'] for segment in narration['segments']}
    samples = exported['samples']
    by_resource = {sample['resource']: sample for sample in samples}
    if not narration_resources <= set(by_resource):
        raise ValueError('Narrator provenance refers to an unknown source sample')
    protected_categories = {'music', 'sfx', 'shared', 'unknown'}
    protected = narration_resources | {sample['resource'] for sample in samples
        if sample['category'] in protected_categories}
    voice_samples = [sample for sample in samples if sample['category'] == 'voice']
    provisional = [sample for sample in voice_samples if sample['resource'] not in protected]
    clips = []
    for profile in chatter['characters']:
        if profile['name'] == 'narrator':
            continue
        path = chatter_path / (profile['name'] + '.wav')
        if sha256(path) != profile['sha256']:
            raise ValueError('Chatter WAV hash differs from its manifest: ' + profile['name'])
        with wave.open(str(path), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, chatter['sampleRate']):
                raise ValueError('Unexpected chatter PCM format')
            pcm = stream.readframes(stream.getnframes())
        sounds = set()
        frames = 0
        for span in profile['grains']:
            first, last = span['start'] * 2, (span['start'] + span['frames']) * 2
            if not 0 <= first < last <= len(pcm):
                raise ValueError('Invalid chatter span')
            sounds.add(hashlib.sha256(pcm[first:last]).hexdigest())
            frames += span['frames']
        clips.append(dict(name=profile['name'], sounds=len(profile['grains']), distinct_sounds=len(sounds),
            frames=frames, sample_rate=chatter['sampleRate'], seconds=frames / chatter['sampleRate']))

    return dict(
        format='starship-voice-blips-inventory-v1',
        inputs=dict(archive_sha256=archive_hash,
            audio_manifest_sha256=sha256(export_path / 'manifest.json'),
            chatter_manifest_sha256=sha256(chatter_path / 'bank.json')),
        scope=dict(total_message_entries=len(message_ids), excluded_narration_text_ids=[1],
            preserved_narration_voice_ids=[1000], non_narration_message_entries=len(candidates),
            categories=dict(sorted(Counter(category(message_id) for message_id in candidates).items()))),
        playback_mapping=dict(status='incomplete',
            message_ids_with_literal_radio_speaker_evidence=len(observed),
            message_ids_without_literal_radio_speaker_evidence=len(set(candidates) - observed),
            notes=['Literal C calls are partial evidence, not a complete voice map.',
                   'Dynamic arrays, actor scripts, direct voice calls, and sequence-only events need tracing.',
                   'A text entry does not prove one unique original recording.']),
        source_audio=dict(categories=dict(sorted(Counter(sample['category'] for sample in samples).items())),
            voice_sample_count=len(voice_samples),
            voice_encoded_payload_bytes=sum(sample['encoded_size'] for sample in voice_samples),
            protected_narration_sample_count=len(narration_resources),
            protected_narration_encoded_payload_bytes=sum(by_resource[name]['encoded_size'] for name in narration_resources),
            provisional_non_narration_voice_sample_count=len(provisional),
            provisional_non_narration_encoded_payload_bytes=sum(sample['encoded_size'] for sample in provisional),
            safe_to_delete=False,
            removal_requirement='Prove sample reachability from every retained sequence, instrument, and event first.'),
        current_starwolf_clip_banks=clips,
        messages=[dict(id=message_id, category=category(message_id),
            literal_radio_speakers=sorted(literal_speakers.get(message_id, []))) for message_id in candidates])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'sf64.o2r')
    parser.add_argument('--audio-export', type=Path, default=ROOT / 'audio_data')
    parser.add_argument('--chatter', type=Path, default=ROOT / 'assets/audio/chatter')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inventory(args.archive, args.audio_export, args.chatter)
    encoded = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print('Wrote', args.output)
        print(json.dumps({key: report[key] for key in ('scope', 'playback_mapping', 'source_audio')}, indent=2))
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
