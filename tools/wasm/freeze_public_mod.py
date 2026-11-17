#!/usr/bin/env python3
"""Freeze the reviewed mod as source-bound local reconstruction instructions."""
import argparse
import copy
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools"), str(ROOT/"tools/wasm")]
import mod_recipe as codec
import build_wolfen as bw
from extract_team_bodies import dependencies
from package_site_characters import DEFAULT
from site_character_gfx import GLB, Compiler
from site_characters import SiteCharacters
from site_character_bodies import focus_kami_face
import crew_portraits

sha1 = lambda b: hashlib.sha1(b).hexdigest()
sha256 = lambda b: hashlib.sha256(b).hexdigest()

class Freeze:
    def __init__(self, base, target, private):
        self.base, self.target, self.private = base, target, private
        self.bindings = {}
        self.all = base | target
        self.hashnames = {bw.crc64(p):p for p in self.all}
        self.model = (ROOT/"assets/medusa/battleship.f3d").read_bytes()
        assert sha256(self.model) == "9874b8d4b440c676fffb1eab0bff6a552a21b17dbcb63f2e54b82bf4dd719734"
        self.pack = zipfile.ZipFile(DEFAULT)
        self.pack_hash = sha256(DEFAULT.read_bytes())

    def source(self, path, kind="base", offset=0, length=None, destination=None):
        data = self.base[path] if kind == "base" else self.model
        if kind == "project":
            assert path == "restoration-model.bin"
        length = len(data)-offset if length is None else length
        assert 0 <= offset <= len(data) and 0 <= length <= len(data)-offset
        record = dict(kind=kind, path=path, sha1=sha1(data), offset=offset, length=length)
        if destination is not None:
            record["destination"] = destination
        return record

    def put(self, path, sources, witness, replace=False):
        if path not in self.target:
            return
        sources = [self.source(s) if isinstance(s,str) else s for s in sources]
        old = None if replace else self.bindings.get(path)
        record = dict(sources=list(old["sources"]) if old else [],
                      witnesses=list(old["witnesses"]) if old else [])
        for source in sources:
            if source not in record["sources"]:
                record["sources"].append(source)
        if witness not in record["witnesses"]:
            record["witnesses"].append(witness)
        record["kind"] = "derived" if record["sources"] else "authored"
        self.bindings[path] = record

    def refs(self, files, path):
        raw = files[path]
        if raw.startswith(b"<"):
            return [x.decode() for x in re.findall(rb'Path="([^"]+)"',raw)]
        if raw[4:8][::-1] == b"OMTX":
            return []
        return [self.hashnames[h] for h in dependencies(raw)]

    def walk(self, files, roots):
        done, todo = set(), list(roots)
        while todo:
            path = todo.pop()
            if path in done:
                continue
            done.add(path)
            todo.extend(self.refs(files,path))
        return done

    def limb_sources(self, stem, original, variant, ordinal):
        name = "a"+original+"Skel" if variant == "title" else "aVsOnFoot"+original+"Skel"
        raw = self.base[stem+"/"+name]
        count = struct.unpack_from("<I",raw,64)[0]
        assert ordinal < count
        limb = self.hashnames[struct.unpack_from("<Q",raw,68+ordinal*8)[0]]
        gfx = struct.unpack_from("<Q",self.base[limb],64)[0]
        return {limb} | self.walk(self.base,[self.hashnames[gfx]] if gfx else [])

    def material_source(self, stem, material):
        name = material.get("name","")
        if name.startswith("D_TITLE_"):
            return "ast_title/"+name
        if name.startswith("D_versus_"):
            return "ast_versus/"+name
        match = re.fullmatch(r"(ast_title|ast_versus)_([0-9A-F]+)_(.+)",name)
        if match:
            stem, offset = match[1], int(match[2],16)
            return next((stem+"/"+n for n,f in bw.manifest(stem)[1].items()
                         if "offset" in f and int(f["offset"],16)&0xffffff == offset),None)
        return None

    def original_vertex(self, obj, stem, pointer, count):
        path = f"{stem}/{stem}_seg{pointer>>24}_vtx_{pointer&0xffffff:X}"
        raw = self.base[path]
        assert struct.unpack_from("<I",raw,64)[0] >= count
        big = b"".join(struct.pack(">hhhHhhBBBB",*v)
                       for v in struct.iter_unpack("<hhhHhhBBBB",raw[68:68+count*16]))
        bank = obj.original_arwing if stem == "ast_arwing" else obj.segments[stem]
        offset = pointer & 0xffffff
        assert bytes(bank[offset:offset+count*16]) == big, (path,pointer,count)
        return path

    def witness(self, member, **extra):
        return dict(packSha256=self.pack_hash,packMember=member,
                    packMemberSha256=sha256(self.pack.read(member)),**extra)

    def build_characters(self, rom, base_path):
        emit, texture = Compiler.emit, Compiler.texture
        self.active, self.texture_proofs = None, {}
        def captured_emit(comp,glb,meshes,path,*args,**kwargs):
            frame = sys._getframe(1)
            ctx, caller = frame.f_locals, frame.f_code.co_name
            if caller == "rig":
                member = f"characters/{ctx['character']}/{ctx['variant']}/body.glb"
                sources = self.limb_sources(ctx["stem"],ctx["source"],ctx["variant"],ctx["ordinal"])
                origin = dict(originalRig=ctx["source"],limb=ctx["ordinal"])
            elif caller == "build_heads":
                member, name = ctx["source"], ctx["name"]
                assert name in ("wolf","krystal","kami","panther","vitzy")
                sources = self.walk(self.base,["ast_title/ast_title_seg6_gfx_20070"]) if name in ("wolf","krystal","kami") else set()
                origin = dict(head=name,source="Fox-derived" if sources else "authored head")
            elif caller == "install_cockpit":
                member, sources = "cockpits/vitzy/bill.glb", set()
                origin = dict(node="Bill_Wolfen_cockpit_module",generator="Vitzy reference head builder")
            else:
                raise ValueError(("Unknown compiler caller",caller,path))
            witness = self.witness(member,generator="tools/site_character_gfx.py:Compiler.emit",caller=caller,origin=origin)
            previous, self.active = self.active, witness
            before = set(comp.builder.resources)
            try:
                result = emit(comp,glb,meshes,path,*args,**kwargs)
            finally:
                self.active = previous
            for output in (set(comp.builder.resources)-before) | {path}:
                self.put(output,sorted(sources),dict(witness,regeneratedSha1=sha1(comp.builder.resources[output])))
            return result
        def captured_texture(comp,glb,material):
            result = texture(comp,glb,material)
            pbr = material.get("pbrMetallicRoughness",{})
            image_hash = image_name = None
            if "baseColorTexture" in pbr:
                t = glb.doc["textures"][pbr["baseColorTexture"]["index"]]
                image = glb.doc["images"][t["source"]]
                view = glb.doc["bufferViews"][image["bufferView"]]
                offset = view.get("byteOffset",0)
                image_hash = sha256(glb.binary[offset:offset+view["byteLength"]])
                image_name = image.get("name")
            source = self.material_source(comp.stem,material)
            sources = [source] if source in self.base else []
            witness = dict(self.active or {},generator="tools/site_character_gfx.py:Compiler.texture",
                           material=copy.deepcopy(material),imageSha256=image_hash,imageName=image_name)
            paths = [result[1]] + ([result[6][1]] if result[6] else [])
            for path in paths:
                self.texture_proofs[path] = sources, dict(witness,regeneratedSha1=sha1(comp.builder.resources[path]))
            return result
        Compiler.emit, Compiler.texture = captured_emit, captured_texture
        try:
            crew_portraits.PACK = self.private/"assets/crew_portraits"
            with zipfile.ZipFile(base_path) as archive:
                b = bw.Builder(rom,archive)
                b.build()
                c = SiteCharacters(b)
                c.build()
                self.generated = dict(b.resources)
                for member in self.pack.namelist():
                    if not member.endswith(".glb"):
                        continue
                    if member.startswith("characters/"):
                        _,name,variant,_ = member.split("/")
                        stem = "ast_title" if variant == "title" else "ast_versus"
                        prefix = f"characters/{name}/{variant}"
                    elif member.startswith("heads/"):
                        stem, prefix = "ast_arwing", "characters/pilots"
                    elif member.startswith("cockpits/"):
                        stem, prefix = "ast_arwing", "characters/vitzy/cockpit"
                    else:
                        continue
                    glb = GLB(self.pack.read(member))
                    fake = SimpleNamespace(base=archive,resources={},segments={stem:bytearray()})
                    comp = Compiler(fake,stem,prefix)
                    self.active = self.witness(member,historicalVariant="unmodified pack materials")
                    for material in glb.doc.get("materials",[]):
                        captured_texture(comp,glb,material)
                for stem,prefix in (("ast_title","characters/kami/title"),("ast_versus","characters/kami/on_foot"),("ast_arwing","characters/pilots")):
                    member = "characters/kami/title/body.glb"
                    glb = GLB(self.pack.read(member))
                    for material in glb.doc["materials"]:
                        if material.get("name") == "Kami_eight_view_head":
                            material.setdefault("extras",{})["runtime_texture_region"] = [0,0,.125,1]
                    focus_kami_face(glb)
                    fake = SimpleNamespace(base=archive,resources={},segments={stem:bytearray()})
                    comp = Compiler(fake,stem,prefix)
                    self.active = self.witness(member,historicalVariant="before style_face_texture")
                    for material in glb.doc["materials"]:
                        if material.get("name") in ("Kami_eight_view_head","Kami_face_detail"):
                            captured_texture(comp,glb,material)
            for path,(sources,witness) in self.texture_proofs.items():
                if path in self.target:
                    assert witness["regeneratedSha1"] == sha1(self.target[path]), path
                    self.put(path,sources,witness,replace=True)
            for comp in [c.head_compiler,c.cockpit_compiler,*c.bodies.compilers]:
                for _,wrapper in comp.precision_matrices.values():
                    for path in (wrapper,wrapper.removesuffix("_push")):
                        self.put(path,[],dict(generator="tools/site_character_gfx.py:Compiler.precision_matrix"),replace=True)
            for path,raw in self.target.items():
                if path in self.bindings or not path.startswith(("characters/panther/","characters/pilots/")):
                    continue
                if raw[4:8] == b"XETO" and struct.unpack_from("<4I",raw,64) == (2,8,8,128):
                    pixel = raw[80:82]
                    if raw[80:] == pixel*64:
                        self.put(path,[],dict(generator="site_character_panther.parts + Compiler.texture",procedural="solid RGBA16 8x8",pixelHex=pixel.hex()))
            return b,c
        finally:
            Compiler.emit, Compiler.texture = emit, texture
            self.active = None

    def bind_native(self,b,c):
        vertex_sources = set()
        for obj in (b,b.vitzy_fighter):
            for (stem,pointer,count,matrix),(_,path) in obj.vertices.items():
                source = self.original_vertex(obj,stem,pointer,count)
                if obj is b:
                    vertex_sources.add(source)
                self.put(path,[source],dict(generator="Builder.vertex + Fighter.vertex",sourcePointer=pointer,count=count,matrix=list(matrix)),replace=True)
        fighter_sources = set()
        for (stem,offset),(_,path) in b.vitzy_fighter.textures.items():
            source = stem+"/"+b.vitzy_fighter.assets[stem,offset][0]
            if (stem,offset) == ("ast_arwing",0x10448):
                source = "ast_star_wolf/"+b.assets["ast_star_wolf",0x11F00][0]
            fighter_sources.add(source)
            self.put(path,[source],dict(generator="tools/vitzy_fighter.py:Fighter.texture",stem=stem,offset=offset),replace=True)
        fighter_sources |= {s["path"] for _,path in b.vitzy_fighter.vertices.values()
                            for s in self.bindings.get(path,{}).get("sources",[]) if s["kind"] == "base"}
        for path in b.vitzy_fighter.resources:
            if path not in self.bindings:
                self.put(path,sorted(fighter_sources),dict(generator="tools/vitzy_fighter.py:Fighter.build"))
        for path in ("ships/vitzy_fighter/HeadDL","ships/vitzy_fighter/CanopyDL"):
            self.put(path,[],self.witness("heads/vitzy/head.glb",generator="SiteCharacters.build_heads"),replace=True)
        from site_character_bodies import CREW
        for character,occupied,original in CREW:
            for variant,stem in (("title","ast_title"),("on_foot","ast_versus")):
                symbol = lambda name: stem+("/a"+name+"Skel" if variant=="title" else "/aVsOnFoot"+name+"Skel")
                source_skel, target_skel = symbol(original), symbol(occupied)
                before, after = self.base[source_skel], self.all[target_skel]
                count = struct.unpack_from("<I",before,64)[0]
                assert count == struct.unpack_from("<I",after,64)[0]
                member = f"characters/{character}/{variant}/body.glb"
                glb = GLB(self.pack.read(member))
                bones = sorted((n for n in glb.doc["nodes"] if n.get("name","").startswith("limb_")),
                               key=lambda n:int(n["name"].split("_")[1]))
                assert len(bones)==count
                assert [n["name"] for n in bones]==[f"limb_{i:02d}" for i in range(count)]
                old = struct.unpack_from("<"+str(count)+"Q",before,68)
                new = struct.unpack_from("<"+str(count)+"Q",after,68)
                for ordinal,(source_hash,target_hash) in enumerate(zip(old,new)):
                    source_path, target_path = self.hashnames[source_hash], self.hashnames[target_hash]
                    if target_path not in self.target:
                        continue
                    assert target_path == f"characters/{character}/{variant}/limbs/{ordinal}"
                    assert self.generated[target_path] == self.target[target_path], target_path
                    self.put(target_path,[source_path],
                        self.witness(member,generator="tools/site_character_bodies.py:Bodies.rig",
                            sourceSkeleton=source_skel,sourceLimb=source_path,limb=ordinal,
                            packBone=bones[ordinal]["name"],
                            packBoneSha256=sha256(json.dumps(bones[ordinal],sort_keys=True,separators=(",",":")).encode()),
                            regeneratedSha1=sha1(self.generated[target_path])))
        # The reused fairing is tiled Wolfen metal, not its base-named Arwing texture.
        name = "ast_arwing/"+b.assets["ast_arwing",0x10448][0]
        source = "ast_star_wolf/"+b.assets["ast_star_wolf",0x11F00][0]
        self.put(name,[source],dict(generator="tools/build_wolfen.py:Builder.texture",operation="tile Wolfen metal"),replace=True)
        for path in self.target:
            if path.startswith("wolfen_player/detail/"):
                original = path.removeprefix("wolfen_player/detail/").removeprefix("map/")
                parent = self.bindings.get(original)
                sources = parent["sources"] if parent else [original] if original in self.base else None
                if sources is None:
                    raise ValueError(("Unbound detail parent",path,original))
                self.put(path,sources,dict(generator="tools/wolfen_lod.py:detailed_native",sourceResource=original),replace=True)
            elif re.fullmatch(r"wolfen_player/(map_)?lod_vtx_\d+",path) and path in self.generated:
                self.put(path,sorted(vertex_sources),dict(generator="tools/wolfen_lod.py:build_lod"))
        for (stem,pointer,role),(_,path,_) in b.character.materials.items():
            if role == "head_strap":
                self.put(path,[],dict(generator="wolf_head_strap.atlas_pixels",file="assets/wolfen/wolf-eyepatch-strap.png",
                         sha256=sha256((ROOT/"assets/wolfen/wolf-eyepatch-strap.png").read_bytes())),replace=True)
            else:
                source = stem+"/"+b.assets[stem,pointer][0]
                self.put(path,[source],dict(generator="wolf_character.Character.material",role=role),replace=True)
        for (stem,pointer,count,limb,material),(_,path) in b.character.vertex_paths.items():
            segment = 6 if stem == "ast_title" else 3
            source = f"{stem}/{stem}_seg{segment}_vtx_{pointer:X}"
            assert source in self.base
            self.put(path,[source],dict(generator="wolf_character.Character.vertices",sourcePointer=pointer,count=count,limb=limb),replace=True)
        for path in self.generated:
            if not path.startswith("wolf_character/") or path in self.bindings:
                continue
            stem = "ast_versus" if "ast_versus" in path else "ast_title"
            variant = "on_foot" if stem == "ast_versus" else "title"
            sources = self.limb_sources(stem,"Fox",variant,16 if variant == "on_foot" else 19)
            self.put(path,sorted(sources),dict(generator="wolf_head_strap.rebuild_textured_head + wolf_cockpit.build_cockpit_head"))
        for (pointer,count),(_,path) in b.medusa.vertices.items():
            self.put(path,[self.source("restoration-model.bin","project",pointer&0xffffff,count*16,68)],
                     dict(generator="medusa.Medusa.vertex",pointer=pointer,count=count),replace=True)
        for (pointer,count),(_,path) in b.medusa.textures.items():
            self.put(path,[self.source("restoration-model.bin","project",pointer&0xffffff,count*2,80)],
                     dict(generator="medusa.Medusa.texture",pointer=pointer,count=count),replace=True)
        great_root = "ast_great_fox/"+b.assets["ast_great_fox",0][0]
        great_sources = self.walk(self.base,[great_root])
        for path in self.generated:
            if not path.startswith("medusa/") or path in self.bindings:
                continue
            if path.startswith(("medusa/vtx_engine_","medusa/tex_engine_")):
                self.put(path,sorted(great_sources),dict(generator="medusa.Medusa.add_engines"))
            else:
                self.put(path,[self.source("restoration-model.bin","project")],
                         dict(generator="medusa.Medusa.build",proceduralAddition=True))
        self.put("crew_hud/aWolfMarkDL",["ast_common/aFalcoMarkDL"],dict(generator="crew_hud.install"))
        self.put("crew_hud/aWolfMarkTLUT",["ast_common/aFalcoMarkTLUT"],dict(generator="crew_hud.palette"))
        self.put("crew_hud/aWolfMarkTex",[],dict(generator="crew_hud.wolf_pixels",procedural="literal glyph rows"))
        for path in ("characters/CREDITS.md","characters/README_TheRegressor.txt","characters/Vitzy_README.md"):
            member = path.split("/",1)[1]
            assert self.pack.read(member) == self.target[path]
            self.put(path,[],self.witness(member,generator="SiteCharacters.build"))

    def bind_audio(self):
        exported = json.loads((self.private/"audio_data/manifest.json").read_text())
        metadata = json.loads((self.private/"audio_data/metadata.json").read_text())
        chatter = json.loads((ROOT/"assets/audio/chatter/bank.json").read_text())
        releases = []
        for report_path in (self.private/"build/dialogue-blips/starwolf64").glob("*/report.json"):
            archives = list(report_path.parent.glob("*.o2r"))
            if not archives:
                continue
            data = codec.archive_files(archives[0])
            matches = sum(self.target.get(p) == v for p,v in data.items())
            if all(self.target.get(p) == v for p,v in data.items() if p != "ast_radio/message_table"):
                releases.append((matches,str(report_path),data))
        assert releases, "No snapshot-matching voice release"
        _,report_path,_ = max(releases)
        report = json.loads(Path(report_path).read_text())
        rows = {s["resource"]:s for s in exported["samples"]}
        banks = {v["encoded_sha256"]:k for k,v in report["coverage"]["banks"].items()}
        def approved(name):
            source = chatter["sources"][name]
            roots = ([source["resource"]] if "resource" in source else [])+[s["resource"] for s in source.get("segments",[])]
            return roots,source
        def closure(roots):
            return list(dict.fromkeys(p for r in roots for p in (r,rows[r]["predictor_book"],rows[r]["loop_resource"]) if p))
        def instrument_samples(fid,slot):
            raw = self.target[f"ast_audio/ast_audio_v1_instrument_blips_{fid:02d}_{slot:03d}"]
            return {self.hashnames[h] for off in (76,88,100) if (h:=struct.unpack_from("<Q",raw,off)[0])}
        expert, narrator = instrument_samples(3,123), instrument_samples(1,0)
        for path,raw in self.target.items():
            if "_sample_blips_" not in path:
                continue
            digest = sha256(raw[87:])
            bank = banks.get(digest)
            if path in expert:
                roots,proof = approved("vitzy")
            elif path in narrator:
                roots,proof = approved("narrator")
            elif bank and bank.startswith("approved:"):
                roots,proof = approved(bank.split(":",1)[1])
            else:
                assert bank and bank.startswith("source:"),path
                proof = report["coverage"]["banks"][bank]["provenance"]
                for item in proof:
                    assert rows[item["resource"]]["sha256"] == item["source_sha256"]
                roots = list(dict.fromkeys(item["resource"] for item in proof))
            loop,book = struct.unpack_from("<QQ",raw,71)
            witness = dict(generator="voice_blips_bank + voice_blips_codec.encode + voice_blips_native",
                           encodedSha256=digest,provenance=proof,releaseReportSha256=sha256(Path(report_path).read_bytes()))
            for output in (path,self.hashnames[loop],self.hashnames[book]):
                self.put(output,closure(roots),witness,replace=True)
        for path in self.target:
            match = re.fullmatch(r"ast_audio/ast_audio_v1_instrument_blips_(\d+)_(\d+)",path)
            if match:
                fid,slot = map(int,match.groups())
                original = 5 if (fid,slot) == (3,123) else slot
                source = metadata["soundfonts"][fid]["instruments"][original]
                self.put(path,[source],dict(generator="voice_blips_native.native_resources",font=fid,slot=slot,sourceSlot=original),replace=True)
        roots = []
        for name in ("wolf","panther","narrator"):
            roots += approved(name)[0]
        self.put("audio/crew_chatter",closure(roots),dict(generator="build_crew_chatter",sources=chatter["sources"]),replace=True)
        self.put("audio/voice_blips",[],dict(generator="voice_blips_native.native_resources",procedural="BLP1 mapping marker"),replace=True)

    def finish(self, output, archive_digests):
        by_hash = {sha1(data):path for path,data in sorted(self.base.items(),reverse=True)}
        for path,data in self.target.items():
            original = by_hash.get(sha1(data))
            if original is not None:
                self.put(path,[original],dict(generator="exact resource identity",sourceSha1=sha1(data)),replace=True)
            elif path not in self.bindings and path in self.base:
                self.put(path,[path],dict(generator="frozen same-symbol resource modification",
                                         sourceSha1=sha1(self.base[path]),snapshotSha1=sha1(data)))
        unresolved = sorted(set(self.target)-self.bindings.keys())
        if unresolved:
            raise ValueError("Unbound snapshot resources: "+json.dumps(unresolved))
        payloads = {kind:{} for kind in (b"XETO",b"XTVO")}
        for path,data in self.base.items():
            kind = data[4:8]
            if kind in payloads:
                offset = 80 if kind == b"XETO" else 68
                payloads[kind].setdefault(data[offset:],path)
        unchanged = []
        for path,data in self.target.items():
            if path in self.base or sha1(data) in by_hash:
                continue
            kind = data[4:8]
            if kind in payloads:
                offset = 80 if kind == b"XETO" else 68
                original = payloads[kind].get(data[offset:])
                if original:
                    self.put(path,[self.source(original,offset=offset,length=len(data)-offset,destination=offset)],
                             dict(generator="exact payload identity",sourceResource=original),replace=True)
                    unchanged.append(path)
        for path,binding in self.bindings.items():
            binding["targetSha1"] = sha1(self.target[path])
        projects = {"restoration-model.bin":self.model}
        recipe,literals = codec.create(self.base,self.target,self.bindings,project_sources=projects)
        assert codec.apply(recipe,literals,self.base,project_sources=projects) == self.target
        from refresh_mod import source_hashes
        inputs = codec.publication_inputs(ROOT)
        recipe_bytes = (json.dumps(recipe,separators=(",",":"))+"\n").encode()
        archives_bytes = (json.dumps(archive_digests,indent=2)+"\n").encode()
        audit = dict(format="starwolf64-mod-provenance-v1",status="pass",
            assetSetSha256=codec.asset_digest(self.target),resources=len(self.target),
            recipeSha256=sha256(recipe_bytes),literalsSha256=sha256(literals),
            archivesSha256=sha256(archives_bytes),inputs=inputs,bindings=self.bindings,
            checks=dict(reconstructsSnapshot=True,unresolved=0,unchangedBasePayloadCopies=0,
                        additionalExactPayloadReferences=len(unchanged)))
        output.mkdir(parents=True,exist_ok=True)
        for name,data in (("recipe.json",recipe_bytes),("literals.dat",literals),("archives.json",archives_bytes),
                          ("provenance.json",(json.dumps(audit,indent=2)+"\n").encode())):
            (output/name).write_bytes(data)
        (output/"sources.json").write_text(json.dumps(source_hashes(ROOT),indent=2)+"\n")
        print(json.dumps(dict(resources=len(self.target),residualBytes=len(literals),
                             assetSetSha256=audit["assetSetSha256"],status="pass")))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base","rom","overlay"):
        parser.add_argument("--"+name,required=True,type=Path)
    parser.add_argument("--port",type=Path)
    parser.add_argument("--snapshot",type=Path,default=ROOT/"assets/wasm/mod")
    parser.add_argument("--output",type=Path,default=ROOT/"assets/wasm/mod")
    parser.add_argument("--private-project",type=Path,default=ROOT)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    assert sha1(rom) == bw.ROM_SHA1
    base = codec.archive_files(args.base)
    old = json.loads((args.snapshot/"recipe.json").read_text())
    projects = {"restoration-model.bin":(ROOT/"assets/medusa/battleship.f3d").read_bytes()}
    chatter = (args.snapshot/"chatter.dat").read_bytes() if old["format"] == codec.FORMAT else None
    target = codec.apply(old,(args.snapshot/"literals.dat").read_bytes(),base,chatter,project_sources=projects)
    target.update(codec.archive_files(args.overlay))
    f = Freeze(base,target,args.private_project)
    b,c = f.build_characters(rom,args.base)
    f.bind_native(b,c)
    f.bind_audio()
    port = codec.archive_files(args.port or args.base.parent/"starship.o2r")
    f.finish(args.output,{"sf64.o2r":codec.asset_digest(base),"starship.o2r":codec.asset_digest(port),"wolfen.o2r":codec.asset_digest(target)})

if __name__ == "__main__":
    main()
