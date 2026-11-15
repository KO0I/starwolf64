"""Standing title poses for the two Fox-derived crew rigs, in game units."""
import math
import numpy as np


def rotation(angles):
    x, y, z = angles
    sx, sy, sz = np.sin(angles)
    cx, cy, cz = np.cos(angles)
    return np.array([[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                     [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx],
                     [-sy, cy*sx, cy*cx]])


def angles(matrix):
    y = math.asin(np.clip(-matrix[2, 0], -1, 1))
    return np.array([math.atan2(matrix[2, 1], matrix[2, 2]), y,
                     math.atan2(matrix[1, 0], matrix[0, 0])])


def align(source, target):
    source, target = source / np.linalg.norm(source), target / np.linalg.norm(target)
    axis = np.cross(source, target)
    cosine = np.dot(source, target)
    if cosine < -0.999999:
        raise ValueError('Title pose requires an ambiguous half-turn')
    skew = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + skew + skew @ skew / (1 + cosine)


def standing_pose(character, frames, translations, parents):
    """Replace only standing limb rotations; leave root motion and other clips alone."""
    if character not in ('kami', 'krystal'):
        return
    pose = frames[0, 1:].copy()
    original = pose.copy()
    world = {}

    def update():
        world.clear()
        def visit(index):
            if index in world:
                return world[index]
            local = np.eye(4)
            local[:3, :3] = rotation(pose[index])
            local[:3, 3] = translations[index]
            parent = parents[index]
            world[index] = local if parent is None else visit(parent) @ local
            return world[index]
        for index in range(len(pose)):
            visit(index)

    def turn(index, matrix):
        parent = parents[index]
        parent_rotation = np.eye(3) if parent is None else world[parent][:3, :3]
        pose[index] = angles(parent_rotation.T @ matrix)
        update()

    def chain(upper, lower, end, target, bend):
        start = world[upper][:3, 3].copy()
        length1 = np.linalg.norm(translations[lower])
        length2 = np.linalg.norm(translations[end])
        delta = np.asarray(target) - start
        distance = np.linalg.norm(delta)
        if not abs(length1-length2) < distance < length1+length2:
            raise ValueError('Unreachable title-pose hand or foot')
        direction = delta / distance
        bend = np.asarray(bend) - start
        bend -= direction * np.dot(bend, direction)
        bend /= np.linalg.norm(bend)
        along = (length1**2 - length2**2 + distance**2) / (2*distance)
        elbow = start + direction*along + bend*np.sqrt(length1**2-along**2)
        current = world[lower][:3, 3] - start
        turn(upper, align(current, elbow-start) @ world[upper][:3, :3])
        current = world[end][:3, 3] - world[lower][:3, 3]
        turn(lower, align(current, np.asarray(target)-world[lower][:3, 3]) @ world[lower][:3, :3])

    update()
    if character == 'kami':
        # Elbows alongside the torso, wrists meeting behind the lower back.
        chain(4, 3, 2, [10, 205, -48], [70, 242, -38])
        chain(7, 6, 5, [-10, 205, -48], [-70, 242, -38])
        # Bring the feet together beneath the clasped-hands stance.
        chain(10, 9, 8, [-19, 22, -6], [-30, 100, 15])
        chain(13, 12, 11, [19, 22, -6], [30, 100, 15])
    else:
        # Establish the mirrored upper-body pose before rolling the hip toward it.
        turn(21, rotation([0, 0, math.radians(7)]) @ world[21][:3, :3])
        turn(20, rotation([0, 0, math.radians(-10)]) @ world[20][:3, :3])
        # Pose the right glove with fingers down along the outer seam.
        chain(7, 6, 5, [-74, 238, 24], [-106, 260, 7])
        turn(5, align(world[5][:3, 0], np.array([0., -1., .08])) @ world[5][:3, :3])
        # Roll the pelvis into the glove while preserving the upper-body angle.
        torso = world[20][:3, :3].copy()
        turn(21, rotation([0, 0, math.radians(-8.25)]) @ world[21][:3, :3])
        turn(20, torso)
        # Keep both feet planted after the hip adjustment.
        chain(13, 12, 11, [44, 30, -6], [58, 102, 30])
        chain(10, 9, 8, [-12, 22, -6], [-42, 100, 35])
    changed = np.any(np.abs(pose-original) > 1e-8, axis=1)
    # Hold the posed joints so the inherited idle preserves hip/glove contact.
    # Untouched joints retain their original idle motion.
    frames[:, 1:][:, changed] = pose[changed]
