#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='Exercise the actual native engine and capture its PCM with GDB.')
parser.add_argument('--game-set', choices=['starfox64', 'starwolf64'], required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--starwolf-mod', type=Path, default=ROOT / 'build/dialogue-blips/inputs/starwolf64.o2r')
parser.add_argument('--engine-assets', type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
run = Path(tempfile.mkdtemp(prefix='session-', dir=output))
(output / 'proof.json').unlink(missing_ok=True)
(run / 'mods').mkdir(exist_ok=True)
controller_db = args.engine_assets.resolve().parent / 'gamecontrollerdb.txt'
if controller_db.exists() and not (run / 'gamecontrollerdb.txt').exists():
    (run / 'gamecontrollerdb.txt').symlink_to(controller_db)
release_root = ROOT / 'build/dialogue-blips' / args.game_set
release = release_root / json.loads((release_root / 'latest.json').read_text())['directory']
archive = next(release.glob('*voice-blips-*.o2r'))
for source, target in [(ROOT / 'sf64.o2r', run / 'sf64.o2r'), (args.engine_assets, run / 'starship.o2r'),
                       (archive, run / 'mods' / archive.name)]:
    if not target.exists():
        target.symlink_to(source.resolve())
if args.game_set == 'starwolf64':
    if not args.starwolf_mod.is_file():
        parser.error('The Starwolf probe requires --starwolf-mod')
    (run / 'mods/wolfen.o2r').symlink_to(args.starwolf_mod.resolve())
expected = 24040 if args.game_set == 'starwolf64' else 2050
script = '''set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
python
import gdb, wave, struct, json
frame=0
channels=0
pcm={key:bytearray() for key in ('normal','expert','silent')}
states={key:[] for key in pcm}
delivered={key:bytearray() for key in pcm}
message_pointer=0
lookup_id=0
route={}
pause_active=False
narration_started=False
narration_cleared=False
pending_narration_cleared=False
narration_interruption_preserved=False
def value(expression):
    return int(gdb.parse_and_eval(expression))
def invoke(expression):
    gdb.parse_and_eval(expression)
def phase():
    return 'normal' if 130<=frame<290 else 'expert' if 330<=frame<490 else 'silent' if 530<=frame<690 else None
class Frame(gdb.Breakpoint):
    def stop(self):
        global frame
        frame+=1
        return True

def frame_action():
    global pause_active,narration_started,narration_cleared,pending_narration_cleared,narration_interruption_preserved,message_pointer,lookup_id
    if frame==1 or frame%100==0: print('Native frame',frame,flush=True)
    gdb.execute('set {int}&sTitleMsgFrameCount = 0',to_string=True)
    if frame==100:
        print('Checking native marker',flush=True)
        assert value('(int)VoiceBlips_IsActive()')==1
        print('Marker loaded',flush=True)
        message_pointer=value('(unsigned long)ResourceGetDataByName(\"ast_radio/gMsg_ID_2050\")')
        lookup_id=value('(int)Message_IdFromPtr((void*)'+str(message_pointer)+')')
        assert lookup_id==2050,lookup_id
        invoke('(void)Audio_SetVolume(0,0)')
        invoke('(void)Audio_SetVolume(2,0)')
        invoke('(void)Audio_SetVolume(1,99)')
    if frame in (130,330,530):
        key='normal' if frame==130 else 'expert' if frame==330 else 'silent'
        gdb.execute('set {unsigned char}&gExpertMode = '+str(int(frame!=130)),to_string=True)
        if frame==530: invoke('(void)Audio_SetVolume(1,0)')
        invoke('(void)Audio_PlayVoice(2050)')
        route[key]=[value('*(unsigned int*)&sCurrentVoiceId'),value('*(unsigned int*)&sNextVoiceId')]
    if frame==380: invoke('(void)Audio_PlayPauseSfx(1)')
    if frame==385: pause_active=value('(int)Audio_GetCurrentVoice()')==2050
    if frame==390: invoke('(void)Audio_PlayPauseSfx(0)')
    if frame==700:
        invoke('(int)CrewChatter_Observe(1000,(void*)1,0,0,(float)1.0)')
        narration_started=value('*(unsigned int*)&sCurrentVoiceId')==1000
    if frame==705:
        narration_cleared=value('*(unsigned int*)&sCurrentVoiceId')==0 and value('*(unsigned int*)&sNextVoiceId')==1
    if frame==706:
        invoke('(int)CrewChatter_Observe(1000,(void*)2,0,0,(float)1.0)')
        invoke('(void)VoiceBlips_ClearNarration()')
        pending_narration_cleared=value('*(unsigned int*)&sCurrentVoiceId')==0 and value('*(unsigned int*)&sNextVoiceId')==1
    if frame==708:
        invoke('(int)CrewChatter_Observe(1000,(void*)3,0,0,(float)1.0)')
        invoke('(void)Audio_PlayVoice(2050)')
    if frame==712:
        narration_interruption_preserved=value('*(unsigned int*)&sCurrentVoiceId')==2050
    key=phase()
    if key and frame%5==0:
        states[key].append(value('(int)Audio_GetCurrentVoice()'))
        if key!='silent':
            speaker=400 if key=='expert' else 0
            assert value('(int)CrewChatter_Observe('+str(speaker)+',(void*)'+str(message_pointer)+','+str(frame)+',24,(float)1.0)')==0
class Mix(gdb.Breakpoint):
    def stop(self):
        global channels
        key=phase()
        if key:
            pointer,frames,count=[value(x) for x in ('$rdi','$rsi','$rdx')]
            assert count in (1,2) and 0<frames<20000
            assert channels in (0,count)
            channels=count
            pcm[key].extend(bytes(gdb.selected_inferior().read_memory(pointer,frames*count*2)))
        return False
class Delivered(gdb.Breakpoint):
    def stop(self):
        key=phase()
        if key:
            pointer,size=[value(x) for x in ('$rdi','$rsi')]
            assert 0<size<100000
            delivered[key].extend(bytes(gdb.selected_inferior().read_memory(pointer,size)))
        return False
OUTPUT=OUTPUT_VALUE
Frame('CrewChatter_Commit',internal=True)
Mix('CrewChatter_Mix',internal=True)
Delivered('AudioPlayerPlayFrame',internal=True)
gdb.execute('run',to_string=True)
gdb.execute('set scheduler-locking off')
while frame<720:
    frame_action()
    gdb.execute('continue',to_string=True)
for key,data in pcm.items():
    with wave.open(OUTPUT+'/'+key+'.wav','wb') as stream:
        stream.setnchannels(channels);stream.setsampwidth(2);stream.setframerate(32000);stream.writeframes(data)
summary={'routes':route,'channels':channels,'states':states,'pause_retains_voice':pause_active,'narration_started':narration_started,'narration_cleared':narration_cleared,'pending_narration_cleared':pending_narration_cleared,'narration_interruption_preserved':narration_interruption_preserved,'lookup_2050':lookup_id,'legacy_mixer_unchanged':all(pcm[key]==delivered[key] for key in pcm)}
open(OUTPUT+'/engine.json','w').write(json.dumps(summary,indent=2)+'\\n')
print('VOICE_PROBE '+json.dumps(summary))
end
quit 0
'''.replace('OUTPUT_VALUE', repr(str(output)))
command = output / 'probe.gdb'
command.write_text(script)
environment = dict(os.environ, SHIP_HOME=str(run), SDL_AUDIODRIVER='dummy', LIBGL_ALWAYS_SOFTWARE='1')
with (output / 'engine.log').open('w') as log:
    process = subprocess.Popen(['xvfb-run', '-a', 'gdb', '-q', '-batch', '-x', str(command), str(ROOT / 'build-native/Starship')],
        cwd=run, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGINT)
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
log = (output / 'engine.log').read_text()
if code or 'VOICE_PROBE ' not in log:
    raise SystemExit('Native engine probe failed. See ' + str(output / 'engine.log') + '\n' + log[-3500:])
report = json.loads((output / 'engine.json').read_text())
report['audio'] = {}
for name in ('normal', 'expert', 'silent'):
    with wave.open(str(output / (name + '.wav'))) as stream:
        rate, channels = stream.getframerate(), stream.getnchannels()
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(float)
    late = pcm[rate * channels:rate * channels * 2]
    rms = float(np.sqrt(np.mean(late * late)))
    report['audio'][name] = dict(late_rms=rms, frames=len(pcm) // channels)
    assert report['routes'][name] == [2050, 2050 if name == 'normal' else expected], report['routes']
    assert 2050 in report['states'][name] and report['states'][name][-1] == 0, report['states'][name]
    assert (rms < 8 and rms < report['audio']['normal']['late_rms'] / 100 if name == 'silent' else rms > 100), report['audio']
assert report['pause_retains_voice'] and report['narration_started'] and report['narration_cleared'] and report['pending_narration_cleared'] and report['narration_interruption_preserved'] and report['legacy_mixer_unchanged'] and report['lookup_2050']==2050, report
(output / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS native engine', args.game_set, report['audio'])
