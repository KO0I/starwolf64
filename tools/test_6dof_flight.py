#!/usr/bin/env python3
"""Exercise the production flight rotation with an independent vector oracle."""
import ctypes
import math
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def basis(pitch, yaw, roll):
    p, y, r = map(math.radians, (pitch, yaw, roll))
    cp, sp, cy, sy, cr, sr = math.cos(p), math.sin(p), math.cos(y), math.sin(y), math.cos(r), math.sin(r)
    # Engine coordinates, including its 180 degree model heading.
    right = (-cy * cr - sy * sp * sr, -cp * sr, sy * cr - cy * sp * sr)
    up = (-cy * sr + sy * sp * cr, cp * cr, sy * sr + cy * sp * cr)
    forward = (-sy * cp, sp, -cy * cp)
    return right, up, forward


def rotate_vector(vector, axis, angle):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    cross = (axis[1]*vector[2]-axis[2]*vector[1], axis[2]*vector[0]-axis[0]*vector[2], axis[0]*vector[1]-axis[1]*vector[0])
    dot = sum(a*b for a, b in zip(axis, vector))
    return tuple(v*c+x*s+a*dot*(1-c) for v, x, a in zip(vector, cross, axis))


class FlightRotation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='starship-6dof-')
        directory = Path(cls.temp.name)
        adapter = directory/'adapter.c'
        adapter.write_text('#include "src/port/Flight6DOF.h"\nvoid step(float* p,float* y,float* r,float dp,float dr){Flight6DOF_Rotate(p,y,r,dp,dr);}\n')
        library = directory/'flight.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT), str(adapter), '-lm', '-o', str(library)], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.step.argtypes = [ctypes.POINTER(ctypes.c_float)]*3+[ctypes.c_float]*2

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def step(self, angles, pitch=0, roll=0):
        values = [ctypes.c_float(v) for v in angles]
        self.library.step(*(ctypes.byref(v) for v in values), pitch, roll)
        return tuple(v.value for v in values)

    def assertBasis(self, actual, expected, tolerance=0.0001):
        for a, e in zip(basis(*actual), expected):
            for av, ev in zip(a, e):
                self.assertAlmostEqual(av, ev, delta=tolerance, msg=str(actual))

    def test_release_holds_orientation(self):
        for angles in [(20, 35, 90), (0, 0, 180), (90, 110, -70)]:
            actual = angles
            for _ in range(120):
                actual = self.step(actual)
            self.assertEqual(actual, angles)

    def test_pitch_follows_roll(self):
        for roll, expected in [(0, (0, 1, 0)), (90, (-1, 0, 0)), (180, (0, -1, 0)), (-90, (1, 0, 0))]:
            for sign in [-1, 1]:
                actual = self.step((0, 0, roll), pitch=10*sign)
                forward = basis(*actual)[2]
                for a, e in zip(forward[:2], expected[:2]):
                    self.assertAlmostEqual(a, e*math.sin(math.radians(10))*sign, delta=0.00001)

    def test_roll_never_yaws_or_pitches(self):
        angles = (37, 83, 0)
        expected = basis(*angles)[2]
        for _ in range(500):
            angles = self.step(angles, roll=3)
            for actual, target in zip(basis(*angles)[2], expected):
                self.assertAlmostEqual(actual, target, delta=0.0001)

    def test_full_pitch_loop_crosses_both_vertical_headings(self):
        angles = (0, 40, 0)
        for frame in range(1, 721):
            angles = self.step(angles, pitch=1)
            self.assertBasis(angles, basis(frame, 40, 0), tolerance=0.00015)

    def test_combined_controls_match_local_axis_rotations(self):
        rng = random.Random(674)
        angles = (25, 50, 70)
        expected = basis(*angles)
        for _ in range(2000):
            dp, dr = rng.uniform(-1.8, 1.8), rng.uniform(-3, 3)
            right, up, forward = expected
            right = rotate_vector(right, forward, -dr)
            up = rotate_vector(up, forward, -dr)
            up, forward = rotate_vector(up, right, -dp), rotate_vector(forward, right, -dp)
            expected = right, up, forward
            angles = self.step(angles, dp, dr)
            self.assertBasis(angles, expected, tolerance=0.0003)


if __name__ == '__main__':
    unittest.main()
