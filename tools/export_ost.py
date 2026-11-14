#!/usr/bin/env python3
"""Render Starship's music through its native engine and package a playable OST."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import wave
import zipfile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Album order, sequence id, descriptive title. Shared sequences appear once.
TRACKS = [
 (35, 'Opening'), (34, 'Title'), (36, 'Main Menu and Ranking'), (60, 'World Map'),
 (37, 'Mission Intro - Corneria'), (2, 'Corneria'), (18, 'Boss Battle - Corneria'),
 (38, 'Mission Clear'), (50, 'Mission Intro - Meteo'), (3, 'Meteo'), (19, 'Boss Battle - Meteo'),
 (65, 'Real Boss'), (51, 'Mission Intro - All-Range'), (10, 'Fortuna and Sector Z'),
 (43, 'Star Wolf'), (49, 'Mission Failure'), (44, 'Mission Intro - Short'), (5, 'Sector X'),
 (45, 'Mission Intro - Medium'), (4, 'Titania and Macbeth'), (12, 'Bolse'), (28, 'Boss Battle - Bolse'),
 (9, 'Sector Y and Solar'), (25, 'Boss Battle - Sector Y'), (13, 'Katina'), (55, 'Bill'),
 (14, 'Aquas'), (6, 'Zoness'), (54, 'Katt'), (7, 'Area 6'), (58, 'Warp Zone'),
 (8, 'Venom'), (62, 'Dash into the Base'), (17, 'Andross Approach'), (33, 'Andross'),
 (61, 'Andross Brain'), (64, 'All Clear'), (42, 'Staff Roll'), (39, 'Player Down'),
 (40, 'Game Over'), (63, 'Training'), (56, 'Versus Menu and Results'), (46, 'Versus Battle'),
 (47, 'Versus Hurry Up'),
]
# Audio heap and reverb presets from sSoundTestTracks and the mission callers.
BONUS_TRACKS = [(19, 'Boss Battle - Meteo - Alternate', 0), (33, 'Andross - Alternate', 0)]
SPECS = {35:22,34:23,36:23,60:280,37:0,44:1,45:1,50:1,51:8,
 2:0,3:1,4:2,5:3,6:4,7:5,8:6,9:7,10:8,12:10,13:11,14:12,58:1,
 54:13,55:11,18:0,19:1,25:7,28:10,43:6,38:0,49:0,39:0,40:25,
 63:28,46:784,47:785,56:23,62:6,17:23,33:6,61:6,64:6,42:27,65:7}

def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, **kwargs)

def build(output, build_dir):
    commands = subprocess.check_output(['ninja','-C',str(build_dir),'-t','commands','Starship'],text=True).splitlines()
    original = 'CMakeFiles/Starship.dir/src/port/Game.cpp.o'
    compile_command = shlex.split(next(c for c in commands if ' -c '+str(ROOT/'src/port/Game.cpp') in c))
    args = []; skip = False
    for part in compile_command:
        if skip: skip = False; continue
        if part in ('-o','-MF','-MT'): skip = True; continue
        if part in ('-MD','-c',str(ROOT/'src/port/Game.cpp')): continue
        args.append(part)
    obj = output/'render_ost.o'
    run(args+['-c',ROOT/'tools/render_ost.cpp','-o',obj],cwd=build_dir)
    renamed = output/'game_without_main.o'
    run(['objcopy','--redefine-sym','main=ost_original_main',build_dir/original,renamed])
    link = shlex.split(commands[-1].split('&&')[1].strip())
    link = [str(renamed) if a==original else a for a in link if not a.startswith('-Wl,--dependency-file=')]
    executable = output/'Starship-ost'
    link[link.index('-o')+1] = str(executable)
    link.append(str(obj))
    run(link,cwd=build_dir)
    return executable

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'exports/starship-ost')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'build-cmake')
    parser.add_argument('--only',type=int,nargs='*',help='Sequence ids for a trial render; no album archive')
    parser.add_argument('--seconds',type=int,default=180,help='Duration limit for looping cues, including a six-second fade')
    args=parser.parse_args()
    if args.seconds < 1 or args.seconds > 3600: parser.error('--seconds must be between 1 and 3600')
    if args.only and not set(args.only).issubset({sid for sid,_ in TRACKS}): parser.error('--only contains an unknown music sequence')
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    work=output/'work'; work.mkdir(exist_ok=True)
    executable=build(work,args.build_dir.resolve())
    session=work/'session'; session.mkdir(exist_ok=True)
    (session/'mods').mkdir(exist_ok=True)
    for name in ('sf64.o2r','starship.o2r','gamecontrollerdb.txt'):
        source=ROOT/name if name=='sf64.o2r' else args.build_dir.resolve()/name
        dest=session/name
        if source.exists() and not dest.exists(): dest.symlink_to(source)
    (session/'starship.cfg.json').write_text(json.dumps({'Window':{'Width':320,'Height':240},'Audio':{'Channels':2}}))
    manifest=json.loads((ROOT/'audio_data/manifest.json').read_text())
    music=[s for s in manifest['sequences'] if s['id']>1]
    assert {s['file'] for s in music}=={next(s['file'] for s in music if s['id']==sid) for sid,_ in TRACKS}
    assert len(TRACKS)==len({s['file'] for s in music})==44
    env=dict(os.environ,SHIP_HOME=str(session),SDL_AUDIODRIVER='dummy',LIBGL_ALWAYS_SOFTWARE='1')
    signature=hashlib.sha256((ROOT/'tools/render_ost.cpp').read_bytes()+(ROOT/'sf64.o2r').read_bytes()).hexdigest()
    records=[]
    album=[(sid,title,0 if sid==62 else 255) for sid,title in TRACKS]+BONUS_TRACKS
    total=len(album)
    for number,(sid,title,parameter) in enumerate(album,1):
        if args.only and sid not in args.only: continue
        base=f'{number:02d} - {title}'
        key=f'{sid:02d}' if parameter==255 else f'{sid:02d}-p{parameter}'
        raw=work/(key+'.wav'); log=work/(key+'.log')
        limit=600 if sid==42 else args.seconds
        capture=work/(key+'-capture.json')
        config=dict(sequence=sid,spec=SPECS[sid],parameter=parameter,seconds=limit,renderer=signature)
        if not raw.exists() or not capture.exists() or json.loads(capture.read_text())!=config:
            print(f'Rendering {number:02d}/{total} {title}',flush=True)
            with log.open('w') as stream:
                run(['xvfb-run','-a',executable,sid,SPECS[sid],parameter,limit,raw],cwd=session,env=env,stdout=stream,stderr=subprocess.STDOUT)
            capture.write_text(json.dumps(config,indent=2)+'\n')
        text=log.read_text()
        if 'OST_CAPTURE' not in text: raise RuntimeError('Incomplete capture: '+str(log))
        ended='ended=1' in text
        with wave.open(str(raw)) as stream:
            assert stream.getframerate()==32000 and stream.getnchannels()==2
            pcm=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').reshape(-1,2).copy()
        active=np.flatnonzero(np.max(np.abs(pcm.astype(np.int32)),axis=1)>16)
        if len(active)<3200: raise RuntimeError('Silent capture: '+title)
        pcm=pcm[max(0,int(active[0])-3200):min(len(pcm),int(active[-1])+16000)]
        if not ended:
            fade=min(len(pcm),6*32000)
            pcm[-fade:]=(pcm[-fade:].astype(float)*np.linspace(1,0,fade)[:,None]).astype('<i2')
        prepared=work/(key+'-prepared.wav')
        with wave.open(str(prepared),'wb') as stream:
            stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(32000);stream.writeframes(pcm.tobytes())
        record=dict(track=number,title=title,sequence_id=sid,audio_spec=SPECS[sid],bgm_parameter=parameter,natural_end=ended,
          seconds=round(len(pcm)/32000,3),peak=int(np.max(np.abs(pcm.astype(np.int32)))),
          clipped_samples=int(np.count_nonzero((pcm==32767)|(pcm==-32768))))
        if record['clipped_samples']: raise RuntimeError('Capture clips: '+title)
        record['files']={}
        for fmt,codec in [('flac',['-c:a','flac','-compression_level','8']),('mp3',['-c:a','libmp3lame','-b:a','320k'])]:
            folder=output/fmt.upper();folder.mkdir(exist_ok=True)
            dest=folder/(base+'.'+fmt)
            run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',prepared,*codec,
              '-metadata','album=Starship OST','-metadata','title='+title,'-metadata',f'track={number}/{total}',
              '-metadata','genre=Game Soundtrack','-metadata','comment=Rendered from local Starship game assets',dest])
            record['files'][fmt]=dict(path=str(dest.relative_to(output)),sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
        records.append(record)
        print(f'Exported {base}: {record["seconds"]}s; natural_end={ended}; peak={record["peak"]}',flush=True)
    if args.only: return
    assert len(records)==total
    for fmt in ('flac','mp3'):
        folder=output/fmt.upper()
        playlist='#EXTM3U\n'+''.join(f'#EXTINF:{r["seconds"]},{r["title"]}\n{Path(r["files"][fmt]["path"]).name}\n' for r in records)
        (folder/'Starship OST.m3u8').write_text(playlist)
    (output/'tracklist.txt').write_text('Starship OST\n\n'+''.join(f'{r["track"]:02d}. {r["title"]} [{int(r["seconds"])//60}:{int(r["seconds"])%60:02d}]\n' for r in records))
    report=dict(album='Starship OST',tracks=records,sample_rate=32000,channels=2,
      capture_music_volume=85,source_archive_sha256=hashlib.sha256((ROOT/'sf64.o2r').read_bytes()).hexdigest(),
      method='Native Starship sequence interpreter, synthesizer, soundfonts and audio-spec reverb presets; no gameplay, dialogue or sound effects.',
      loop_policy=f'Looping cues rendered for up to {args.seconds} seconds with a six-second fade. Natural endings retain up to two seconds of release. Staff roll allowed up to ten minutes.',
      shared_sequences='44 distinct music sequences plus two alternate boss arrangements from the sound-test settings; aliased stage and boss ids are not duplicated.')
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'README.txt').write_text('Starship OST\n\n46 tracks rendered from the local game assets using the native audio engine.\nIncludes all 44 distinct music sequences and two alternate boss arrangements.\nMusic captured at 85/99 volume for headroom, without normalization.\nFLAC: lossless stereo, 16-bit, 32 kHz. MP3: stereo, 320 kbps, 32 kHz.\n'+report['loop_policy']+'\nDescriptive track titles follow the source code. Shared sequences appear once.\nOriginal music remains credited to its respective rights holders.\n')
    for fmt in ('FLAC','MP3'):
        bundle=output.parent/f'Starship-OST-{fmt}.zip'
        with zipfile.ZipFile(bundle,'w',zipfile.ZIP_STORED) as archive:
            for path in sorted((output/fmt).iterdir()):archive.write(path,fmt+'/'+path.name)
            for name in ('README.txt','tracklist.txt','manifest.json'):archive.write(output/name,name)
        print('Archive: '+str(bundle),flush=True)

if __name__=='__main__':main()
