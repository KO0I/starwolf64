from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from voice_blips_bank import approved_bank, source_bank
from voice_blips_codec import decode, encode, loop_state
import numpy as np


def build_replacements(root, catalog, roster, game_set):
    root = Path(root)
    metadata = json.loads((root / 'audio_data/metadata.json').read_text())
    manifest = json.loads((root / 'audio_data/manifest.json').read_text())
    aliases = roster['speaker_aliases']
    overrides = roster['game_sets'][game_set]['approved_overrides']
    events = catalog['events']
    counts = Counter(e['status'] for e in events)
    if counts != {'voiced': 725, 'silent': 54, 'narration': 7, 'control': 4}:
        raise ValueError(('Unexpected catalog counts', dict(counts)))
    voiced = [e for e in events if e['status'] == 'voiced']
    samples = {s['resource']: s['pcm_sha256'] for s in manifest['samples']}
    def speech_notes(event):
        return [n for n in event['notes'] if n['sample'] and n['instrument'] is not None and n['instrument'] < 124]
    direct, hash_profiles, conflicts = {}, defaultdict(set), []
    for event in voiced:
        identity = event['id']
        raw = {e['speaker'] for e in event['speaker_evidence']}
        if raw - aliases.keys():
            raise ValueError((identity, 'Unmapped speakers', sorted(raw - aliases.keys())))
        choices = {aliases[s] for s in raw}
        override = roster['speaker_overrides'].get(str(identity))
        if len(choices) > 1:
            conflicts.append(dict(id=identity, speakers=sorted(raw), evidence=event['speaker_evidence'], override=override))
        if override:
            if choices != {'andross', 'katt'}:
                raise ValueError((identity, 'Unexpected audition evidence', choices))
            choices = {override}
        if len(choices) > 1:
            raise ValueError((identity, 'Speaker conflict', sorted(choices)))
        profile = next(iter(choices), None)
        direct[identity] = profile
        if not speech_notes(event):
            raise ValueError((identity, 'Voiced event has no speech notes'))
        if profile:
            for note in speech_notes(event):
                hash_profiles[samples[note['sample']]].add(profile)
    if any(len(profiles) > 1 for profiles in hash_profiles.values()):
        raise ValueError('Identical source audio has conflicting speakers')
    assignments, by_profile, slots = {}, defaultdict(list), {}
    for event in voiced:
        identity = event['id']
        found = set().union(*(hash_profiles[samples[n['sample']]] for n in speech_notes(event)))
        profile = direct[identity]
        if profile is None:
            if len(found) > 1:
                raise ValueError((identity, 'Duplicate source conflict', sorted(found)))
            profile = next(iter(found), f'source_{identity}')
        elif found - {profile}:
            raise ValueError((identity, 'Source speaker mismatch', profile, sorted(found)))
        assignments[identity] = profile
        for note in speech_notes(event):
            by_profile[profile].append(note)
            key = (event['font_id'], note['instrument'])
            entry = slots.setdefault(key, dict(profile=profile, notes=defaultdict(set), ids=set()))
            if entry['profile'] != profile:
                raise ValueError((key, 'Font slot speaker conflict'))
            entry['notes'][note['region']].add(note['note'])
            entry['ids'].add(identity)
    expected = {(fid, slot) for fid in range(1, 21)
                for slot, path in enumerate(metadata['soundfonts'][fid]['instruments'][:124])
                if path and (fid != 1 or slot >= 6)}
    if set(slots) != expected:
        raise ValueError(('Voice slot coverage', sorted(expected - slots.keys()), sorted(slots.keys() - expected)))
    encoded_banks, bank_reports = {}, {}
    for profile, notes in sorted(by_profile.items()):
        key = ('approved', overrides[profile]) if profile in overrides else ('source', profile)
        if key in encoded_banks:
            continue
        train = approved_bank(root, key[1]) if key[0] == 'approved' else source_bank(root, profile, notes)
        encoded = encode(train.pcm)
        decoded = decode(encoded)
        clip_hashes = {hashlib.sha256(decoded[span['start']:span['start'] + span['frames']].tobytes()).hexdigest() for span in train.spans}
        if len(clip_hashes) != 16:
            raise ValueError(('Encoded clips lost their variation', profile))
        error = np.mean((train.pcm.astype(float) - decoded.astype(float)) ** 2)
        power = np.mean(train.pcm.astype(float) ** 2)
        snr = 10 * np.log10(power / max(error, 1e-12))
        if snr < 18:
            raise ValueError(('Encoded clip quality is too low', profile, snr))
        encoded_banks[key] = dict(data=encoded.data, frames=encoded.frames, book=encoded.book,
            order=encoded.order, predictors=encoded.predictors, loop_state=loop_state(encoded, 0), loop=True)
        bank_reports[':'.join(key)] = dict(clips=len(train.clips), spans=list(train.spans),
            gap_frames=train.gap_frames, provenance=list(train.provenance), frames=encoded.frames,
            encoded_bytes=len(encoded.data), encoded_sha256=hashlib.sha256(encoded.data).hexdigest(), snr_db=round(float(snr), 3),
            distinct_decoded_clips=len(clip_hashes))
    replacements, slot_report = {}, []
    for (fid, slot), entry in sorted(slots.items()):
        path = metadata['soundfonts'][fid]['instruments'][slot]
        present = {s['region'] for s in metadata['instruments'][path]['sounds'] if s['sample']}
        observed = entry['notes']
        if set(observed) != present or any(len(notes) != 1 for notes in observed.values()):
            raise ValueError(((fid, slot), 'Region or note conflict'))
        tuning = {region: 2 ** ((39 - next(iter(notes))) / 12) for region, notes in observed.items()}
        profile = entry['profile']
        key = ('approved', overrides[profile]) if profile in overrides else ('source', profile)
        replacements[fid, slot] = dict(encoded_banks[key], region_tunings=tuning)
        slot_report.append(dict(font_id=fid, slot=slot, profile=profile, ids=sorted(entry['ids']),
            bank=':'.join(key), region_tunings=tuning))
    report = dict(game_set=game_set, counts=dict(counts), profiles=len(by_profile), replacements=len(replacements),
        source_only_ids=sorted(i for i, p in assignments.items() if p.startswith('source_')),
        assignments=[dict(id=i, profile=p) for i, p in sorted(assignments.items())],
        speaker_evidence_conflicts=conflicts, banks=bank_reports, slots=slot_report)
    return replacements, report
