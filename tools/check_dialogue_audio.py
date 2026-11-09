#!/usr/bin/env python3
"""Execute the installed dialogue lookup and verify silent edited voice lines."""
import struct,sys,zipfile,hashlib
from pathlib import Path
sys.path.insert(0,"tools")
from build_wolfen import TABLE,ROM_NAME,mio0
from wolf_dialogue import RADIO_BASE,VOICE_RETURN_ROM,lookup_entries,voice_filter
rom=Path("browser/wolfen.z64").read_bytes()
base_rom=Path(ROM_NAME).read_bytes()
rows=[struct.unpack_from(">IIII",rom,TABLE+i*16) for i in range(64)]
_,start,end,compressed=next(row for row in rows if row[0]==0xDE5D50)
assert compressed==0
radio=rom[start:end]
entries=[]
for offset in range(0xCCAC,len(radio)-7,8):
    pair=struct.unpack_from(">iI",radio,offset)
    if pair[0]==-1: break
    entries.append(pair)
HALT=0xF00DF00D
def execute(message_ptr,radio_image=radio,rom_image=rom):
    def read(address,size):
        if RADIO_BASE<=address and address+size<=RADIO_BASE+len(radio_image):
            data=radio_image[address-RADIO_BASE:address-RADIO_BASE+size]
        else:
            offset=address-0x7FFFF400
            assert 0x1000<=offset and offset+size<=0xDE480,hex(address)
            data=rom_image[offset:offset+size]
        return int.from_bytes(data,"big")
    registers=[0]*32
    registers[4]=message_ptr
    registers[31]=HALT
    pc=0x800C2890
    pending=None
    for _ in range(20000):
        if pc==HALT: return registers[2]
        word=read(pc,4)
        opcode=word>>26
        rs,rt,rd=(word>>21)&31,(word>>16)&31,(word>>11)&31
        immediate=word&65535
        signed=immediate if immediate<32768 else immediate-65536
        prior=pending
        pending=None
        next_pc=pc+4
        if word==0: pass
        elif opcode==15: registers[rt]=immediate<<16
        elif opcode==9: registers[rt]=(registers[rs]+signed)&0xFFFFFFFF
        elif opcode==13: registers[rt]=registers[rs]|immediate
        elif opcode==35: registers[rt]=read((registers[rs]+signed)&0xFFFFFFFF,4)
        elif opcode==37: registers[rt]=read((registers[rs]+signed)&0xFFFFFFFF,2)
        elif opcode==0 and word&63==37: registers[rd]=registers[rs]|registers[rt]
        elif opcode==0 and word&63==8: pending=registers[rs]
        elif opcode==2: pending=((pc+4)&0xF0000000)|((word&0x3FFFFFF)<<2)
        elif opcode in (4,5,21):
            equal=registers[rs]==registers[rt]
            take=equal if opcode==4 else not equal
            if take: pending=(pc+4+signed*4)&0xFFFFFFFF
            elif opcode==21: next_pc=pc+8
        else: raise AssertionError((hex(pc),hex(word)))
        registers[0]=0
        pc=prior if prior is not None else next_pc
    raise AssertionError("MIPS lookup failed to return")
by_id=dict(entries)
for message_id in (1,2040,2050,2055,2058,23000,23032):
    result=execute(by_id[message_id])
    with zipfile.ZipFile('build-cmake/mods/wolfen.o2r') as installed, zipfile.ZipFile('sf64.o2r') as original:
        changed={int(name.rsplit('_',1)[1]) for name in installed.namelist() if name.startswith('ast_radio/gMsg_ID_') and installed.read(name)!=original.read(name)}
    expected=0 if message_id in changed else message_id
    assert result==expected,(message_id,result,expected)
assert execute(0x81234560)==0xFFFF
assert struct.unpack_from(">I",rom,VOICE_RETURN_ROM)[0]>>26==2
# The same real instruction path supports multiple muted entries.
jump=struct.unpack_from(">I",rom,VOICE_RETURN_ROM)[0]
stub_address=0x80000000|((jump&0x3FFFFFF)<<2)
stub_offset=stub_address-RADIO_BASE
for muted_ids in ((),(2050,2055)):
    multiple=bytearray(radio)
    code=voice_filter(stub_offset,muted_ids)
    multiple[stub_offset:stub_offset+len(code)]=code
    for message_id in (2040,2050,2055,2058):
        expected=0 if message_id in muted_ids else message_id
        assert execute(by_id[message_id],multiple)==expected
# This proves the check catches the former behavior.
unfiltered=bytearray(rom)
struct.pack_into(">I",unfiltered,VOICE_RETURN_ROM,0x03E00008)
assert execute(by_id[2050],rom_image=unfiltered)==2050
# All browser IDs and native numeric text lookups remain available.
old_rows=[struct.unpack_from(">IIII",base_rom,TABLE+i*16) for i in range(64)]
_,a,b,c=next(row for row in old_rows if row[0]==0xDE5D50)
old_radio=mio0(base_rom[a:b]) if c else base_rom[a:b]
expected_radio=bytearray(old_radio)
struct.pack_into(">I",expected_radio,0xCDF0,RADIO_BASE)
assert radio[0xCCAC:]==expected_radio[0xCCAC:],"Radio IDs changed"
with zipfile.ZipFile("sf64.o2r") as source,zipfile.ZipFile("build-cmake/mods/wolfen.o2r") as mod:
    old=lookup_entries(source.read("ast_radio/message_table"))
    new=lookup_entries(mod.read("ast_radio/message_table"))
    forward={i:c for i,c in new[:-1] if i<65536}
    assert forward==dict(old[:-1])
    reverse={}
    for message_id,crc in new[:-1]: reverse.setdefault(crc,message_id&65535)
    for message_id,crc in old[:-1]:
        assert reverse[crc]==(0 if message_id in changed else message_id)
    assert not any(name.startswith("ast_audio/") for name in mod.namelist())
# Existing playback dispatcher, music, and sound banks were not patched.
assert rom[0x1B8DC:0x1B900]==base_rom[0x1B8DC:0x1B900]
assert rom[0xDEA20:0x873CB0]==base_rom[0xDEA20:0x873CB0]
assert Path("mods/wolfen.o2r").read_bytes()==Path("build-cmake/mods/wolfen.o2r").read_bytes()
print("PASS: executed installed MIPS lookup/filter with delay slots; edited voice is zero, unedited voices survive, multi-line muting works, and reverting the hook restores the original voice.")
print("PASS: all native numeric text IDs preserved, voice/music banks unchanged, native mirror matches.")
print("ROM version",hashlib.sha256(rom).hexdigest()[:16])
