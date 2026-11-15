from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from derive_wolf_chatter import grain, read_wav

RATE = 32000


@dataclass(frozen=True)
class ClipBank:
    name: str
    pcm: np.ndarray
    clips: tuple
    spans: tuple
    gap_frames: int
    provenance: tuple


def train(name, clips, gap_seconds, provenance):
    gap = round(gap_seconds * RATE)
    pieces = [np.zeros(32, dtype=np.int16)]
    spans = []
    cursor = 32
    for clip in clips:
        clip = np.asarray(clip, dtype=np.int16)
        spans.append(dict(start=cursor, frames=len(clip)))
        pieces.append(clip)
        silence = gap + (-(cursor + len(clip) + gap) % 16)
        pieces.append(np.zeros(silence, dtype=np.int16))
        cursor += len(clip) + silence
    sounds = {hashlib.sha256(clip.tobytes()).hexdigest() for clip in clips}
    if len(clips) != 16 or len(sounds) != 16:
        raise ValueError(name + ' needs sixteen distinct clips')
    pcm = np.concatenate(pieces)
    return ClipBank(name, pcm, tuple(clips), tuple(spans), gap, tuple(provenance))


def approved_bank(root, name):
    directory = Path(root) / 'assets/audio/chatter'
    manifest = json.loads((directory / 'bank.json').read_text())
    profile = next(p for p in manifest['characters'] if p['name'] == name)
    path = directory / (name + '.wav')
    if hashlib.sha256(path.read_bytes()).hexdigest() != profile['sha256']:
        raise ValueError('Approved clip bank hash differs: ' + name)
    audio, rate = read_wav(path)
    if rate != RATE:
        raise ValueError('Approved clip bank must use 32000 Hz')
    pcm = np.rint(audio * 32768).astype(np.int16)
    clips = [pcm[g['start']:g['start'] + g['frames']].copy() for g in profile['grains']]
    sources = [dict(approved_bank=name, grain=i, wav_sha256=profile['sha256']) for i in range(len(clips))]
    return train('starwolf_' + name, clips, profile['gapSeconds'], sources)


def source_bank(root, name, notes):
    root = Path(root)
    exported = json.loads((root / 'audio_data/manifest.json').read_text())
    samples = {sample['resource']: sample for sample in exported['samples']}
    candidates = []
    seen = set()
    source_seconds = 0
    for note in notes:
        resource = note.get('sample')
        if resource is None:
            continue
        effective_rate = round(RATE * note['tuning'] * 2 ** ((note['note'] - 39) / 12))
        key = (resource, effective_rate)
        if key in seen:
            continue
        seen.add(key)
        sample = samples[resource]
        path = root / 'audio_data' / sample['wav']
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
            raise ValueError('Original voice sample hash differs: ' + resource)
        audio, _ = read_wav(path)
        ratio = Fraction(RATE, effective_rate)
        audio = resample_poly(audio, ratio.numerator, ratio.denominator)
        audio = audio[:RATE * 6]
        width = round(.106 * RATE)
        for center in range(width // 2, len(audio) - width // 2, round(.045 * RATE)):
            block = audio[center - width // 2:center + width // 2]
            energy = float(np.sqrt(np.mean((block - block.mean()) ** 2)))
            if energy > .003:
                candidates.append((energy, audio, center / RATE, resource, sample['sha256'], effective_rate))
        source_seconds += len(audio) / RATE
        if source_seconds >= 12 and len(candidates) >= 32:
            break
    if not candidates:
        raise ValueError('No usable voiced fragments for ' + name)
    cutoff = max(.003, max(candidate[0] for candidate in candidates) * .2)
    candidates = [candidate for candidate in candidates if candidate[0] >= cutoff]
    stride = 7
    while np.gcd(stride, len(candidates)) != 1:
        stride += 1
    clips, provenance, hashes = [], [], set()
    melody = (0, -1.3, .8, -2, -.4)
    for i in range(160):
        _, audio, center, resource, digest, effective_rate = candidates[i * stride % len(candidates)]
        semitones = melody[i % len(melody)] + (i // (len(candidates) * len(melody))) * .07
        clip = np.rint(np.clip(grain(audio, center, .106, semitones), -.95, .95) * 32767).astype(np.int16)
        digest_clip = hashlib.sha256(clip.tobytes()).hexdigest()
        if digest_clip in hashes:
            continue
        hashes.add(digest_clip)
        clips.append(clip)
        provenance.append(dict(resource=resource, source_sha256=digest, center_seconds=center,
            source_playback_rate=effective_rate, pitch_shift_semitones=semitones))
        if len(clips) == 16:
            break
    return train(name, clips, .0575, provenance)
