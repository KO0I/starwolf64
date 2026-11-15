#!/usr/bin/env python3
"""Verify the exported audio, album metadata, source coverage and ZIP contents."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    report = json.loads((output / 'manifest.json').read_text())
    tracks = report['tracks']
    assert len(tracks) == 46
    assert [r['track'] for r in tracks] == list(range(1, 47))
    source = json.loads((Path(__file__).resolve().parents[1] / 'audio_data/manifest.json').read_text())
    music = {s['id']: s['file'] for s in source['sequences'] if s['id'] > 1}
    assert {music[r['sequence_id']] for r in tracks} == set(music.values())
    assert len(set(r['sequence_id'] for r in tracks)) == 44
    assert report['capture_music_volume'] == 85
    fingerprints = {}
    for record in tracks:
        sid, parameter = record['sequence_id'], record['bgm_parameter']
        key = f'{sid:02d}' if parameter == 255 else f'{sid:02d}-p{parameter}'
        with wave.open(str(output / 'work' / (key + '-prepared.wav'))) as stream:
            assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (32000, 2, 2)
            frames = stream.getnframes()
            reference = stream.readframes(frames)
        assert round(frames / 32000, 3) == record['seconds']
        assert record['peak'] > 100 and record['clipped_samples'] == 0
        for fmt in ('flac', 'mp3'):
            path = output / record['files'][fmt]['path']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record['files'][fmt]['sha256']
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                'stream=codec_name,sample_rate,channels:format_tags=title,album,track', '-of', 'json', str(path)]))
            stream = probe['streams'][0]
            assert (stream['codec_name'], stream['sample_rate'], stream['channels']) == (fmt, '32000', 2)
            tags = {key.lower(): value for key, value in probe['format']['tags'].items()}
            assert tags['album'] == 'Starship OST' and tags['title'] == record['title']
            assert tags['track'] == f"{record['track']}/46"
            decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 's16le', '-'])
            assert len(decoded) == len(reference), (record['title'], fmt, len(decoded), len(reference))
            if fmt == 'flac': assert decoded == reference, record['title']
        fingerprints[(sid, parameter)] = hashlib.sha256(reference[:32000 * 30 * 4]).hexdigest()
        print(f"Verified {record['track']:02d}/46 {record['title']}", flush=True)
    for sid in (19, 33): assert fingerprints[(sid, 0)] != fingerprints[(sid, 255)], 'Alternate arrangement duplicates main track'
    for fmt in ('FLAC', 'MP3'):
        playlist = (output / fmt / 'Starship OST.m3u8').read_text()
        assert playlist.count('#EXTINF:') == 46
        with zipfile.ZipFile(output.parent / f'Starship-OST-{fmt}.zip') as archive:
            assert len(archive.namelist()) == 50
            assert archive.testzip() is None
            assert json.loads(archive.read('manifest.json')) == report
            for record in tracks:
                relative = record['files'][fmt.lower()]['path']
                assert hashlib.sha256(archive.read(relative)).hexdigest() == record['files'][fmt.lower()]['sha256']
    result = dict(tracks=46, distinct_sequences=44, bonus_arrangements=2, lossless_pcm_matches=True,
        mp3_decoding_and_metadata=True, archives_verified=True, clipped_samples=0,
        duration_seconds=round(sum(r['seconds'] for r in tracks), 3))
    (output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__': main()
