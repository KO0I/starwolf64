#!/usr/bin/env python3
"""Check that the packaged prologue contains the full original narration backwards."""
import json
import wave

import numpy as np
from build_crew_chatter import narrator_source
from derive_wolf_chatter import ROOT

original, _ = narrator_source(ROOT / "audio_data")
expected = np.rint(np.clip(original[::-1], -.95, .95) * 32767).astype("<i2")
with wave.open(str(ROOT / "assets/audio/chatter/narrator.wav"), "rb") as stream:
    assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1, 2, 32000)
    actual = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
assert np.array_equal(actual, expected), "Narrator PCM must equal the full recording reversed"
manifest = json.loads((ROOT / "assets/audio/chatter/bank.json").read_text())
narrator = next(profile for profile in manifest["characters"] if profile["name"] == "narrator")
assert narrator["playback"] == "continuous" and narrator["gapSeconds"] == 0
assert all(span == {"start": 0, "frames": len(expected)} for span in narrator["grains"])
print(f"PASS: full reversed narrator, {len(actual) / 32000:.2f} seconds, exact PCM match")
