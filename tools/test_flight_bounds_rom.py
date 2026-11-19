#!/usr/bin/env python3
"""Check the original-ROM flight envelope adapter with a stock-boundary fixture."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
HARNESS="#include <stdio.h>\n#include <string.h>\n#include \"flight_abi.h\"\nuint32_t gFlightState[4];\nint32_t gPlayState,gCamCount;\nstatic float seenWidth,seenHeight;\nstatic int toggleTo=-1;\nvoid FlightBounds_Reset(void);\nvoid FlightBounds_MoveRails(void*);\nvoid FlightBounds_Move360(void*);\nstatic void original(void*p,int allRange){\n seenWidth=PF(p,0x9C);seenHeight=PF(p,0xA0);\n float cx=PF(p,0xAC),cy=allRange?0:PF(p,0xB0);\n PF(p,P_POS)+=PF(p,0xC0);PF(p,P_POS+4)+=PF(p,0xC4);\n if(!allRange){\n  if(PF(p,P_POS)>cx+seenWidth)PF(p,P_POS)=cx+seenWidth;\n  if(PF(p,P_POS)<cx-seenWidth)PF(p,P_POS)=cx-seenWidth;\n }\n if(PF(p,P_POS+4)>cy+seenHeight)PF(p,P_POS+4)=cy+seenHeight;\n if(PF(p,P_POS+4)<cy+PF(p,0xA4))PF(p,P_POS+4)=cy+PF(p,0xA4);\n if(toggleTo>=0){gFlightState[1]=toggleTo;toggleTo=-1;}\n}\nvoid Original_MoveRails(void*p){original(p,0);}\nvoid Original_Move360(void*p){original(p,1);}\n#define CHECK(x) do{if(!(x)){fprintf(stderr,\"FAIL line %d: %s\\n\",__LINE__,#x);return 1;}}while(0)\nint main(void){\n union{uint64_t align;uint8_t bytes[0x600];}storage;memset(storage.bytes,0,sizeof(storage.bytes));void*p=storage.bytes;\n PI(p,P_STATE)=3;gPlayState=2;gCamCount=1;\n PF(p,0x9C)=1000;PF(p,0xA0)=500;PF(p,0xA4)=0;PF(p,0xAC)=100;PF(p,0xB0)=50;\n gFlightState[1]=1;PF(p,P_POS)=1300;PF(p,P_POS+4)=1300;\n FlightBounds_MoveRails(p);\n CHECK(seenWidth==1250&&seenHeight==1500);\n CHECK(PF(p,0x9C)==1000&&PF(p,0xA0)==500);\n CHECK(PF(p,P_POS)==1300&&PF(p,P_POS+4)==1300);\n toggleTo=0;float oldX=PF(p,P_POS),oldY=PF(p,P_POS+4);PI(p,0x228)=0;\n FlightBounds_MoveRails(p);\n CHECK(PF(p,P_POS)<oldX&&PF(p,P_POS)>1100);\n CHECK(PF(p,P_POS+4)<oldY&&PF(p,P_POS+4)>550);\n CHECK((PI(p,0x228)&9)==9);\n for(int i=0;i<100;i++)FlightBounds_MoveRails(p);\n CHECK(PF(p,P_POS)<=1100.5f&&PF(p,P_POS+4)<=550.5f);\n FlightBounds_Reset();gFlightState[1]=1;PF(p,P_POS)=-1100;PF(p,P_POS+4)=200;\n toggleTo=0;PI(p,0x228)=0;FlightBounds_MoveRails(p);\n CHECK(PF(p,P_POS)>-1100&&PF(p,P_POS)<-900&&(PI(p,0x228)&2));\n FlightBounds_Reset();gFlightState[1]=1;PF(p,0xC0)=PF(p,0xC4)=0;PF(p,P_POS)=20000;PF(p,P_POS+4)=1250;\n FlightBounds_Move360(p);\n CHECK(seenWidth==1000&&seenHeight==1500&&PF(p,P_POS)==20000&&PF(p,P_POS+4)==1250);\n toggleTo=0;PI(p,0x228)=0;FlightBounds_Move360(p);\n CHECK(PF(p,P_POS)==20000&&PF(p,P_POS+4)<1250&&PF(p,P_POS+4)>500&&(PI(p,0x228)&8));\n for(int i=0;i<100;i++)FlightBounds_Move360(p);\n CHECK(PF(p,P_POS)==20000&&PF(p,P_POS+4)<=500.5f);\n FlightBounds_Reset();gFlightState[1]=0;PF(p,P_POS)=0;PF(p,P_POS+4)=200;\n FlightBounds_MoveRails(p);CHECK(seenWidth==1000&&seenHeight==500);\n gFlightState[1]=1;gCamCount=2;FlightBounds_MoveRails(p);CHECK(seenWidth==1000&&seenHeight==500);\n gCamCount=1;PI(p,P_FORM)=1;FlightBounds_Move360(p);CHECK(seenHeight==500);\n puts(\"PASS: 3x ceiling, 1.25x rail sides, smooth return, directional cues and all-range lateral preservation\");\n return 0;\n}\n"
def main():
    build=ROOT/"build/flight-bounds-tests"
    build.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build) as name:
        root=Path(name);source=root/"harness.c";binary=root/"harness"
        source.write_text(HARNESS)
        env=dict(os.environ,TMPDIR=str(root))
        subprocess.run(["cc","-std=gnu17","-Wall","-Wextra","-Werror",
                        "-I",str(ROOT/"tools/n64"),str(source),
                        str(ROOT/"tools/n64/flight_bounds.c"),"-o",str(binary)],env=env,check=True)
        return subprocess.run([str(binary)],env=env).returncode
if __name__=="__main__":
    raise SystemExit(main())
