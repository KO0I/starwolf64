#!/usr/bin/env python3
"""Check the actual installed native and browser extended portrait textures."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_wolfen import TABLE, manifest as bank_manifest, mio0
from crew_portraits import encode_rgba16, decode_rgba16

def segments(rom):
    rows=[struct.unpack_from(">IIII",rom,TABLE+i*16) for i in range(64)]
    def read(stem):
        virtual,_=bank_manifest(stem)
        _,start,end,compressed=next(row for row in rows if row[0]==virtual)
        return bytes(mio0(rom[start:end]) if compressed else rom[start:end])
    return read

def main():
    pack=ROOT/"assets/extended_portraits"
    spec=json.loads((pack/"manifest.json").read_text())
    scenes=json.loads((pack/"scenes.json").read_text())
    assert spec["version"]==1 and "actual" in spec["technique"]
    rom=(ROOT/"browser/wolfen.z64").read_bytes()
    read=segments(rom)
    originals=segments((ROOT/"Star Fox 64 (U) (V1.1) [!].z64").read_bytes())
    decoded={}
    with zipfile.ZipFile(ROOT/"build-cmake/mods/wolfen.o2r") as archive:
        for entry in spec["assets"]:
            image=Image.open(pack/entry["source"]).convert("RGBA")
            raw=encode_rgba16(image)
            assert hashlib.sha256(raw).hexdigest()==entry["sha256_rgba16"],entry["id"]
            assert decode_rgba16(raw,*image.size).tobytes()==image.tobytes(),entry["id"]
            decoded[entry["id"]]=image
            for target in entry["targets"]:
                stem,offset=target["segment"],target["offset"]
                _,definitions=bank_manifest(stem)
                name,fields=next((name,fields) for name,fields in definitions.items()
                                 if "offset" in fields and int(fields["offset"],16)&0xffffff==offset)
                resource=archive.read(stem+"/"+name)
                assert struct.unpack_from("<4I",resource,64)==(2,target["width"],target["height"],len(raw)),name
                assert resource[80:]==raw,("native",name)
                assert read(stem)[offset:offset+len(raw)]==raw,("browser",name)
                assert originals(stem)[offset:offset+len(raw)]!=raw,("unchanged replacement",name)
    historical_offset=0x33080
    historical_size=96*52*2
    assert read("ast_map")[historical_offset:historical_offset+historical_size]==originals("ast_map")[historical_offset:historical_offset+historical_size],"Historical flashback changed"
    normal_offset=0x25080
    normal_size=316*240*2
    assert read("ast_ending_expert")[normal_offset:normal_offset+normal_size]==originals("ast_ending_expert")[normal_offset:normal_offset+normal_size],"Complete THANK YOU image changed"
    assert "ending_normal_team" not in decoded
    before=np.array(Image.open(ROOT/"assets/portraits/png/ending_expert_reward.png").convert("RGBA"))
    assert np.array_equal(before[:80],np.array(decoded["ending_expert_team"])[:80]),"Original GREAT! caption changed"
    original_card=np.array(Image.open(ROOT/"assets/portraits/png/D_OPT_800E170.png").convert("RGBA"))
    assert np.array_equal(original_card[:,163:],np.array(decoded["invoice_team"])[:,163:]),"Original invoice stamp changed"
    closed=decoded["wolf_briefing_closed"].copy()
    talking=closed.copy()
    talking.paste(decoded["wolf_briefing_mouth"],(47,0))
    delta=np.any(np.array(closed)!=np.array(talking),axis=2)
    assert delta.any(),"Wolf has no talking-frame change"
    mask=np.zeros((51,92),dtype=bool);mask[:34,47:79]=True
    assert not np.any(delta&~mask),"Wolf talking frame changes outside the overlay"
    assert (ROOT/"mods/wolfen.o2r").read_bytes()==(ROOT/"build-cmake/mods/wolfen.o2r").read_bytes(),"Native mirror is stale"
    print(f"PASS: {len(spec['assets'])} extended textures match native/browser builds; source hashes and RGBA16 checked.")
    print("PASS: historical flashback, complete THANK YOU! image, GREAT! caption, invoice stamp, and mouth-overlay allocation preserved.")

if __name__=="__main__":
    main()
