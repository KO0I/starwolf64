"""Install reviewed character sources into the existing native and browser slots."""
import hashlib
import json
import re
import struct
import zipfile
from types import SimpleNamespace

import numpy as np

from build_wolfen import ROOT, END, HEAD_LIFT, COCKPIT_DROP, cartridge_crc, crc64, manifest, inverse
from package_site_characters import DEFAULT, verify as verify_package
from site_character_krystal import focus_eyes as focus_krystal_eyes
from site_character_gfx import GLB, Compiler
from site_character_bodies import Bodies
from site_character_edits import apply_budget, triangle_count
from site_character_storage import Storage
from site_character_panther import install as install_panther_head
from extract_team_bodies import dependencies

# Original US 1.1 instructions, checked before every replacement.
AIM_PATCHES = {
    0x52D3C: (0x1546004A, 0x1000004A),
    0x52E70: (0x54C0000B, 0x2CC10003),
    0x52E74: (0x24010002, 0x10200015),
    0x52E98: (0x8CA601C4, 0x10000015),
    0x52E9C: (0x24010002, 0),
    0x52F40: (0x11A10017, 0),
    0x53020: (0x27BDFFD8, 0x080148EA),
    0x53024: (0xAFBF0014, 0),
    0x53098: (0x27BDFFD8, 0x080148EA),
    0x5309C: (0xAFBF0014, 0),
}
TITLE_PATCHES = {
    0x7E58: (0x24010011, 0x24010013),
    0x7E7C: (0x24010012, 0x24010014),
    0x7EAC: (0x24010012, 0x24010014),
    0x7EB4: (0x24010013, 0x24010015),
    0x7EE4: (0x24010013, 0x24010015),
}
POSE_REFERENCES = (
    ('peppy_idle', 0xB1728, 0xB172C, 2, 0xE830),
    ('kami_idle', 0xB1764, 0xB1768, 2, 0xE74C),
    ('peppy_jump', 0xB1904, 0xB1908, 2, 0xEC20),
    ('kami_jump', 0xB1940, 0xB1944, 2, 0xEB3C),
    ('peppy_idle', 0xB2360, 0xB23B4, 3, 0xE830),
    ('kami_idle', 0xB236C, 0xB23EC, 3, 0xE74C),
)
HEAD_SLOTS = {'wolf': 0x90, 'krystal': 0x3CE0, 'kami': 0x5AB0,
              'panther': 0x16CC0, 'vitzy': 0x1C90}


def replace_word(data, offset, old, new):
    if struct.unpack_from('>I', data, offset)[0] != old:
        raise ValueError(f'Unexpected character patch source at {offset:#x}')
    struct.pack_into('>I', data, offset, new)


class SiteCharacters:
    def __init__(self, builder):
        self.builder = builder
        self.package_verification = verify_package(DEFAULT)
        for stem, data in [('ast_title', builder.original_title),
                           ('ast_versus', builder.character.original['ast_versus'])]:
            del builder.segments[stem][len(data):]
        self.original = {stem: bytes(data) for stem, data in builder.segments.items()}
        self.storage = Storage(builder)
        builder.character_storage = self.storage
        builder.character_allocate = self.storage.allocate
        self.bodies = Bodies(builder)
        self.heads = {}
        self.pose_addresses = {}
        self.rom_patches = dict(AIM_PATCHES)
        self.head_patches = []
        self.head_compiler = Compiler(builder, 'ast_arwing', 'characters/pilots')

    def read(self, path):
        with zipfile.ZipFile(DEFAULT) as archive:
            return GLB(archive.read(path))

    @staticmethod
    def bounds(glb):
        world = glb.world_matrices()
        points = []
        for index, node in enumerate(glb.doc['nodes']):
            if 'mesh' not in node:
                continue
            for part in glb.doc['meshes'][node['mesh']]['primitives']:
                xyz = glb.accessor(part['attributes']['POSITION'])
                points.extend((np.c_[xyz, np.ones(len(xyz))] @ world[index].T)[:, :3])
        points = np.array(points)
        return points.min(axis=0), points.max(axis=0)

    def build_heads(self):
        wolf = self.read('heads/wolf/head.glb')
        low, high = self.bounds(wolf)
        center = (low + high) * 2.5
        for name, offset in HEAD_SLOTS.items():
            source = f'heads/{name}/head.glb'
            if name == 'kami':
                derived = self.bodies.pilot_heads[name]
                glb, details = derived['glb'], derived['generated_details']
                source = 'characters/kami/title/body.glb'
                reduction = None
            else:
                glb = wolf if name == 'wolf' else self.read(source)
                details = None
                reduction = apply_budget(glb, name, 'pilot')
                if name == 'krystal':
                    focus_krystal_eyes(glb)
                if name == 'panther':
                    details = install_panther_head(glb, 'pilot')
            glb.doc.setdefault('asset', {}).setdefault('extras', {})['runtime_smooth_head_normals'] = True
            trim = glb.doc.get('asset', {}).get('extras', {}).get('runtime_hair_trim')
            low, high = np.asarray(trim['fit_bounds']) if trim else self.bounds(glb)
            scale = min(5.0, * (np.array([554., 623., 636.]) / (high - low)))
            if name == 'panther':
                scale *= 1.1
            if name in ('wolf', 'panther', 'krystal', 'kami'):
                scale *= .9
            fit = np.eye(4)
            fit[:3, :3] *= scale
            fit[:3, 3] = center - (low + high) * .5 * scale
            world = glb.world_matrices()
            meshes = [(index, fit @ world[index]) for index, node in enumerate(glb.doc['nodes']) if 'mesh' in node]
            path = 'ast_arwing/' + self.builder.assets['ast_arwing', offset][0]
            address, native, triangles = self.head_compiler.emit(glb, meshes, path)
            before = bytes(self.builder.segments['ast_arwing'][offset:offset + 8])
            struct.pack_into('>II', self.builder.segments['ast_arwing'], offset, 0x06010000, address)
            self.head_patches.append((offset, before, address))
            if name == 'kami' and triangles > 512:
                raise ValueError(f'{name} cockpit head exceeds 512 triangles')
            self.heads[name] = {'source': source, 'triangles': triangles,
                                'fit': fit.tolist(), 'path': path, 'address': address,
                                'generated_details': details, 'triangle_reduction': reduction, 'hair_trim': trim}
            if name == 'vitzy':
                if triangles > 216:
                    raise ValueError('Vitzy exceeds the supplied 216-triangle budget')
                self.builder.gfx('ships/vitzy_fighter/HeadDL', native)
                self.install_cockpit(fit)

    def install_cockpit(self, fit):
        """Use the supplied module inside the existing Bill fighter exterior."""
        b = self.builder
        fighter = b.vitzy_fighter
        glb = self.read('cockpits/vitzy/bill.glb')
        world = glb.world_matrices()
        # The game draws pilot heads in 1/70.925 ship units at this mount.
        mount = np.eye(4)
        mount[:3, :3] /= 70.925
        mount[:3, 3] = [0, 6.4 - COCKPIT_DROP + HEAD_LIFT, -16.5]
        body_inverse = np.array(inverse(fighter.matrices[0x9B60]))
        module = [(i, body_inverse @ mount @ fit @ world[i]) for i, n in enumerate(glb.doc['nodes'])
                  if n.get('name') == 'Bill_Wolfen_cockpit_module']
        if len(module) != 1:
            raise ValueError('Missing reviewed Bill cockpit module')
        private = SimpleNamespace(base=b.base, resources=b.resources, gfx=b.gfx, segments={'ast_arwing': bytearray()})
        self.cockpit_compiler = Compiler(private, 'ast_arwing', 'characters/vitzy/cockpit')
        _, cockpit, triangles = self.cockpit_compiler.emit(glb, module, 'characters/vitzy/CockpitDL')
        _, hull = fighter.emit([fighter.hull(body_inverse.tolist(), 'body')], 'reviewed_hull')
        # Both component streams restore their own material state.
        b.gfx('ships/vitzy_fighter/BodyDL', hull[:-1] + cockpit)
        b.gfx('ships/vitzy_fighter/CanopyDL', [END])
        full_module = [(i, mount @ fit @ world[i]) for i, n in enumerate(glb.doc['nodes'])
                       if n.get('name') == 'Bill_Wolfen_cockpit_module']
        _, full_cockpit, _ = self.cockpit_compiler.emit(glb, full_module, 'characters/vitzy/CockpitFullDL')
        full_sources = [fighter.hull(np.eye(4).tolist(), side) for side in ('body', 'left', 'right')]
        _, full_hull = fighter.emit(full_sources, 'reviewed_full_hull')
        b.gfx('ships/vitzy_fighter/HullDL', full_hull[:-1] + full_cockpit)
        for path, resource in fighter.resources.items():
            b.resources.setdefault(path, resource)
        self.cockpit_triangles = triangles

    def build_poses(self):
        b = self.builder
        data = b.segments['ast_versus']
        for mode, source_offset in [('idle', 0x2E56C), ('jump', 0x2E95C)]:
            path = f'ast_versus/D_versus_3{source_offset:06X}'
            source = b.base.read(path)
            count = struct.unpack_from('<I', source, 64)[0]
            # Setup copies 30 entries, including unused pose-buffer slots.
            payload = source[68:68 + min(count, 30) * 12].ljust(30 * 12, b'\0')
            values = struct.unpack('<90f', payload)
            raw = struct.pack('>90f', *values)
            data.extend(b'\0' * (-len(data) % 8))
            address = 0x03000000 | len(data)
            data.extend(raw)
            for name, target in [('peppy', 0x2E830 if mode == 'idle' else 0x2EC20),
                                 ('kami', 0x2E74C if mode == 'idle' else 0x2EB3C)]:
                target_path = f'ast_versus/D_versus_3{target:06X}'
                b.resources[target_path] = source[:64] + struct.pack('<I', 30) + payload
                self.pose_addresses[name + '_' + mode] = address
        for key, hi, lo, register, old in POSE_REFERENCES:
            address = self.pose_addresses[key]
            old_hi = 0x3C000000 | register << 16 | 0x303
            old_lo = 0x24000000 | register << 21 | register << 16 | old
            new_hi = old_hi & 0xFFFF0000 | ((address + 0x8000) >> 16)
            new_lo = old_lo & 0xFFFF0000 | address & 0xFFFF
            self.rom_patches[hi] = old_hi, new_hi
            self.rom_patches[lo] = old_lo, new_lo

    def build(self):
        self.bodies.build()
        ending = self.builder.segments['medusa_ending']
        for offset, old, new in [(0x2768, 0x2D210014, 0x2D210015),
                                  (0x27A8, 0x8C296504, 0x8C299EC8),
                                  (0x2948, 0x1441006B, 0)]:
            replace_word(ending, offset, old, new)
        if hashlib.sha256(ending[0x29A8:0x29FC]).hexdigest() != '1746fe91eb0b3773db2d76fa9f3776425bf0263e85d8502fe27f81b3950004cb':
            raise ValueError('Unexpected original ending callback storage')
        default = 0x8018A018
        table = [0x80189CD4, 0x80189D38, default, default, default, default, default,
                 0x80189D9C, default, default, 0x80189E00, default, default, default,
                 default, default, default, default, 0x80189E64, 0x80189F98, 0x80189F34]
        struct.pack_into('>21I', ending, 0x29A8, *table)
        self.build_heads()
        self.build_poses()
        for offset, (old, new) in TITLE_PATCHES.items():
            replace_word(self.builder.segments['ovl_menu'], offset, old, new)
        with zipfile.ZipFile(DEFAULT) as archive:
            for name in ['CREDITS.md', 'README_TheRegressor.txt', 'Vitzy_README.md']:
                self.builder.resources['characters/' + name] = archive.read(name)
        for stem in self.storage.original:
            data = self.builder.segments[stem]
            data.extend(b'\0' * (-len(data) % 16))
        self.final_segments = {name: bytes(data) for name, data in self.builder.segments.items()}
        self.final_resources = dict(self.builder.resources)

    def patch_rom(self, rom):
        self.bodies.patch_rom(rom)
        virtual, _ = manifest('ast_arwing')
        old_end = virtual + len(self.builder.original_arwing)
        needle = struct.pack('>II', virtual, old_end)
        self.scene_ranges = []
        for offset in range(0xCAFB4, 0xCC9D4, 4):
            if self.builder.rom[offset:offset + 8] == needle:
                new_end = virtual + len(self.builder.segments['ast_arwing'])
                replace_word(rom, offset + 4, old_end, new_end)
                self.scene_ranges.append((offset, virtual, new_end))
        if len(self.scene_ranges) != 33:
            raise ValueError('Unexpected Arwing scene table references')
        self.scene_memory = []
        offset = 0xCAFB4
        source = (ROOT / 'src/engine/fox_load_inits.c').read_text()
        for name, count in re.findall(r'Scene (\w+)\[(\d+)\]', source):
            for index in range(int(count)):
                words = struct.unpack_from('>38I', rom, offset)
                used = (words[1] - words[0]) + (words[3] - words[2]) if words[0] else 0
                used += sum(words[j + 1] - words[j] for j in range(8, 38, 2) if words[j])
                end = 0x80187520 + used
                self.scene_memory.append({'scene': name, 'setup': index, 'end': end,
                                          'free_bytes': 0x80281000 - end})
                if end > 0x80281000:
                    raise ValueError(f'Reviewed assets overlap fixed buffers in {name}[{index}] by {end - 0x80281000} bytes')
                offset += 0x98
        if offset != 0xCC9D4:
            raise ValueError('Unexpected scene table length')
        for offset, (old, new) in self.rom_patches.items():
            replace_word(rom, offset, old, new)

    def verify(self, rom):
        b = self.builder
        self.storage.verify()
        self.bodies.verify(rom)
        for stem, source in self.final_segments.items():
            table = 0xDE480 + b.table_indices[stem] * 16
            _, start, end, compressed = struct.unpack_from('>IIII', rom, table)
            if stem != 'ast_star_wolf' and (compressed or rom[start:end] != source):
                raise ValueError(f'Reviewed native/browser segment mismatch: {stem}')
        for offset, (_, value) in self.rom_patches.items():
            if struct.unpack_from('>I', rom, offset)[0] != value:
                raise ValueError('Missing reviewed character code patch')
        if struct.unpack_from('>II', rom, 0x10) != cartridge_crc(rom):
            raise ValueError('Reviewed ROM checksum mismatch')
        for offset, _, address in self.head_patches:
            if struct.unpack_from('>II', b.segments['ast_arwing'], offset) != (0x06010000, address):
                raise ValueError('Reviewed cockpit head redirect mismatch')
        with zipfile.ZipFile(DEFAULT) as archive:
            manifest_doc = json.loads(archive.read('manifest.json'))
        for name, head in self.heads.items():
            if name == 'kami':
                expected = triangle_count(self.bodies.pilot_heads[name]['glb'])
            else:
                removed = (head['triangle_reduction'] or {}).get('removed_triangles', 0)
                expected = manifest_doc['pilot_heads'][name]['triangles'] - removed
                expected += (head['generated_details'] or {}).get('added_triangles', 0)
            if head['triangles'] != expected:
                raise ValueError(f'Reviewed head lost triangles: {name}')
        for offset, raw, path, native, header in self.head_compiler.blocks:
            if bytes(b.segments['ast_arwing'][offset:offset + len(raw)]) != raw:
                raise ValueError('Reviewed cockpit source block changed')
            if path and native is not None and b.resources[path][header:] != native:
                raise ValueError('Reviewed cockpit native block differs')
        if b.resources != self.final_resources:
            raise ValueError('Reviewed native resource set changed during ROM generation')
        hashes = {crc64(path) for path in set(b.base.namelist()) | set(b.resources)}
        for path, resource in b.resources.items():
            if resource[4:8][::-1] in (b'SKEL', b'LIMB', b'ODLT'):
                if any(reference not in hashes for reference in dependencies(resource)):
                    raise ValueError(f'Unresolved reviewed native dependency: {path}')

    def report(self):
        return {'source': self.package_verification, 'runtime_conversion_complete': True,
                'active_crew': ['wolf', 'panther', 'krystal', 'kami'],
                'expert_pilot': 'vitzy', 'pilot_heads': self.heads,
                'vitzy_cockpit_triangles': self.cockpit_triangles,
                'scene_memory': self.scene_memory,
                'storage': self.storage.stats(),
                'bodies': self.bodies.rigs,
                'notes': ['Original source GLBs, clips, and PNGs remain unchanged in the source archive.',
                          'Viewer placement normalization is removed for runtime body units.',
                          'Rigid body clips drive the game skeletons; accessory-only tracks remain in the source pack.',
                          'Pilot meshes use the game head steering; facial animation clips remain in the source pack.',
                          'Large atlases are reduced to the N64 texture memory budget.',
                          'Verified runtime selections limit Krystal/Kami title bodies to 768 and the Kami cockpit head to 512 triangles.',
                          'Krystal cockpit geometry retains the original 520-triangle source head.',
                          'Kami cockpit geometry is taken directly from her prepared title body head.']}

    def summary(self):
        return 'Wolf, Panther, Krystal, Kami; five reviewed pilot heads; Vitzy Bill cockpit'
