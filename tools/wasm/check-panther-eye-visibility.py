#!/usr/bin/env python3
"""Check the real WASM front-view title captures for striping inside Panther's left iris."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=Path)
parser.add_argument('--distance', choices=('near', 'far'), required=True)
args = parser.parse_args()
image = np.array(Image.open(args.image).convert('RGB'))
if image.shape[:2] != (1000, 1000):
    parser.error('Use check-webgl.mjs --panther-eyes with its default 1000x1000 viewport')
# Fixed title-rig probe position, camera and viewport; restrict the test to one eye.
x0, y0, x1, y1 = (450, 190, 550, 245) if args.distance == 'near' else (480, 269, 513, 290)
eye = image[y0:y1, x0:x1]
yellow = (eye[:, :, 0] > 180) & (eye[:, :, 1] > 140) & (eye[:, :, 2] < 100)
runs = (np.diff(np.pad(yellow.astype(int), ((0, 0), (1, 1))), axis=1) == 1).sum(axis=1)
# A single pupil can split an iris row in two. Extra runs are the observed depth stripes.
report = {'image': str(args.image), 'distance': args.distance, 'yellow_pixels': int(yellow.sum()),
          'maximum_iris_runs': int(runs.max()), 'striped_rows': int((runs > 2).sum())}
print(json.dumps(report))
minimum = 100 if args.distance == 'near' else 20
if report['yellow_pixels'] < minimum or report['striped_rows']:
    raise SystemExit('FAIL: iris is missing or contains depth stripes')
print('PASS: continuous iris with at most one pupil gap per row')
