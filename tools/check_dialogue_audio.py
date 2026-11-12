#!/usr/bin/env python3
"""Execute the installed dialogue lookup and verify silent edited voice lines."""
import struct,sys,zipfile,hashlib
from pathlib import Path
sys.path.insert(0,"tools")
from build_wolfen import TABLE,ROM_NAME,mio0
from wolf_dialogue import RADIO_BASE,VOICE_RETURN_ROM,lookup_entries,voice_filter,crew_voice_filter,RADIO_SPEAKER_ADDRESS,CREW_SPEAKERS
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rom',type=Path,default=Path('browser/wolfen.z64'))
parser.add_argument('--native',type=Path,default=Path('build-cmake/mods/wolfen.o2r'))
args=parser.parse_args()
rom=args.rom.read_bytes()
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
# US 1.1 Radio_Draw checks NEXT through index 60 even beyond END. Code
# stored after a short message must not introduce a spurious page transition.
original_rows=[struct.unpack_from(">IIII",base_rom,TABLE+i*16) for i in range(64)]
_,old_start,old_end,old_compressed=next(row for row in original_rows if row[0]==0xDE5D50)
original_radio=mio0(base_rom[old_start:old_end]) if old_compressed else base_rom[old_start:old_end]
original_messages={}
for offset in range(0xCCAC,len(original_radio)-7,8):
    message_id,pointer=struct.unpack_from(">iI",original_radio,offset)
    if message_id==-1: break
    original_messages[message_id]=pointer
gate_address=0x80000000|((struct.unpack_from(">I",rom,VOICE_RETURN_ROM)[0]&0x3FFFFFF)<<2)
gate_end=gate_address+len(crew_voice_filter(RADIO_BASE))
for message_id,pointer in entries:
    offset=pointer-RADIO_BASE
    old_offset=original_messages[message_id]-RADIO_BASE
    codes=struct.unpack_from(">61H",radio,offset)
    old_codes=struct.unpack_from(">61H",original_radio,old_offset)
    if 0 not in codes: continue
    terminator=codes.index(0)
    for index in range(terminator+1,61):
        if not gate_address<=pointer+index*2<gate_end: continue
        assert codes[index]!=15 or old_codes[index]==15, (
            "Injected MSGCHAR_NXT after message terminator",message_id,index)

HALT=0xF00DF00D
def execute(message_ptr,radio_image=radio,rom_image=rom,speaker=90):
    def read(address,size):
        if address == RADIO_SPEAKER_ADDRESS and size == 4:
            return struct.unpack(">I",struct.pack(">f",speaker))[0]
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
        elif opcode==36: registers[rt]=read((registers[rs]+signed)&0xFFFFFFFF,1)
        elif opcode==37: registers[rt]=read((registers[rs]+signed)&0xFFFFFFFF,2)
        elif opcode==0 and word&63==0: registers[rd]=(registers[rt]<<((word>>6)&31))&0xFFFFFFFF
        elif opcode==0 and word&63==33: registers[rd]=(registers[rs]+registers[rt])&0xFFFFFFFF
        elif opcode==0 and word&63==35: registers[rd]=(registers[rs]-registers[rt])&0xFFFFFFFF
        elif opcode==0 and word&63==43: registers[rd]=int(registers[rs]<registers[rt])
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
with zipfile.ZipFile(args.native) as installed, zipfile.ZipFile('sf64.o2r') as original:
    changed={int(name.rsplit('_',1)[1]) for name in installed.namelist() if name.startswith('ast_radio/gMsg_ID_') and installed.read(name)!=original.read(name)}
for message_id, pointer in entries:
    result=execute(pointer)
    expected=0 if message_id in changed else message_id
    assert result==expected,(message_id,result,expected)
assert execute(0x81234560)==0xFFFF
# Run the installed crew gate through the real lookup path for every declared speaker.
import re,subprocess,tempfile
header=Path("include/sf64mesg.h").read_text()
speakers=[int(value) for value in re.findall(r'RCID_\w+\s*=\s*(\d+)',header)]
for speaker in speakers:
    for message_id in (2040,2050,2055,2058):
        expected=0 if speaker in CREW_SPEAKERS or message_id in changed else message_id
        assert execute(by_id[message_id],speaker=speaker)==expected,(speaker,message_id)
    assert execute(0x81234560,speaker=speaker)==0xFFFF

# Compile the actual native lookup and gate with only resource-boundary stubs.
source=Path("src/engine/fox_message.c").read_text()
native=source[source.index("static u16 Message_VoiceId"):source.index("s32 Message_GetWidth")]
enum=header[header.index("typedef enum RadioCharacterId"):header.index("} RadioCharacterId;")+len("} RadioCharacterId;")]
harness=r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
typedef int32_t s32;
typedef uint16_t u16;
typedef struct {s32 msgId;u16* msgPtr;const char* path;} MsgLookup;
float gRadioMsgRadioId;
static u16 original_text[16]={1}, changed_text[16]={2}, unknown_text[16]={3};
static MsgLookup lookup[]={{2040,original_text,"ast_radio/gMsg_ID_2040"},{65536,changed_text,"ast_radio/gMsg_ID_2050"},{-1,0,0}};
static void* gMsgLookup=lookup;
#define LOAD_ASSET(x) (x)
static int GameEngine_OTRSigCheck(u16* msg){return memcmp(msg,"__OTR__",7)==0;}
static int VoiceBlips_IsActive(void){return 0;}
''' + enum + native + r'''
int main(void){
    const int speakers[]={SPEAKERS};
    for(unsigned i=0;i<sizeof(speakers)/sizeof(speakers[0]);i++){
        int speaker=speakers[i];
        int crew=speaker==0||speaker==5||speaker==10||speaker==15||speaker==20||speaker==25||speaker==30||speaker==35||speaker==400;
        gRadioMsgRadioId=(float)speaker;
        assert(Message_IdFromPtr(original_text)==(crew?0:2040));
        assert(Message_IdFromPtr((u16*)"__OTR__ast_radio/gMsg_ID_2040")==(crew?0:2040));
        assert(Message_IdFromPtr(changed_text)==0);
        assert(Message_IdFromPtr(unknown_text)==65535);
    }
    return 0;
}
'''
harness=harness.replace("SPEAKERS",",".join(map(str,speakers)))
with tempfile.TemporaryDirectory(prefix="starship-crew-voice-") as temporary:
    test=Path(temporary)/"lookup.c"
    binary=Path(temporary)/"lookup"
    test.write_text(harness)
    subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",str(test),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print("PASS: native and installed MIPS gates mute every crew variant, preserve other speakers, and keep text lookups available.")

assert struct.unpack_from(">I",rom,VOICE_RETURN_ROM)[0]>>26==2
# The same real instruction path supports multiple muted entries.
jump=struct.unpack_from(">I",rom,VOICE_RETURN_ROM)[0]
stub_address=0x80000000|((jump&0x3FFFFFF)<<2)
stub_offset=stub_address-RADIO_BASE
filter_size=len(voice_filter(0,())[0])
for muted_ids in ((),(2050,2055),(1,254,255,256,2050,2055,21050),
                  tuple(range(2049,2057)),tuple(range(1795,2051)),tuple(range(1,257))):
    multiple=bytearray(radio)
    instructions,table=voice_filter(stub_offset+filter_size,muted_ids)
    code=instructions+table
    multiple[stub_offset:stub_offset+len(code)]=code
    for message_id in (2040,2050,2055,2058):
        expected=0 if message_id in muted_ids else message_id
        assert execute(by_id[message_id],multiple)==expected
# Exercise both sides of each delta encoding boundary through the real lookup.
entry_offset=0xCCAC+8*next(i for i,(message_id,_) in enumerate(entries) if message_id==2050)
for delta in (239,240,255,256,3583,3584,3839,3840,65533):
    target=delta+1
    for muted_ids in ((1,target),(1,target-1)):
        multiple=bytearray(radio)
        instructions,table=voice_filter(stub_offset+filter_size,muted_ids)
        code=instructions+table
        multiple[stub_offset:stub_offset+len(code)]=code
        struct.pack_into(">i",multiple,entry_offset,target)
        expected=0 if target in muted_ids else target
        assert execute(by_id[2050],multiple)==expected,(delta,muted_ids)
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
with zipfile.ZipFile("sf64.o2r") as source,zipfile.ZipFile(args.native) as mod:
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
if args.native.resolve()==Path("build-cmake/mods/wolfen.o2r").resolve():
    assert Path("mods/wolfen.o2r").read_bytes()==args.native.read_bytes()
print("PASS: installed MIPS filters preserve non-crew unedited voices, support multi-line muting, and reverting the hook restores original voice IDs.")
print("PASS: all native numeric text IDs preserved, voice/music banks unchanged, native mirror matches.")
print("ROM version",hashlib.sha256(rom).hexdigest()[:16])
