OUTPUT_ARCH(mips)
ENTRY(Flight_Entry)
SECTIONS {
  . = 0x80137E90;
  .flight_state : { KEEP(*(.flight_state)) }
  .text : { *(.text.entry) *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) *(.sdata*) }
  .bss : { *(.bss*) *(.sbss*) *(COMMON) }
  Flight_End = .;
  ASSERT(Flight_End <= 0x80138E90, "6DOF module exceeds retired bootstrap stack")
  /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.pdr) *(.eh_frame*) *(.gnu.attributes) }
}
sinf = 0x80023090;
cosf = 0x80023250;
Math_Atan2F = 0x80005100;
Math_SmoothStepToF = 0x8009BC2C;
Math_SmoothStepToAngle = 0x8009BD38;
Audio_GetCurrentVoice = 0x8001AE78;
Audio_PlaySfx = 0x80019218;
Matrix_RotateX = 0x80005D44;
Matrix_RotateY = 0x80005E90;
Matrix_RotateZ = 0x80005FE0;
Matrix_MultVec3fNoTranslate = 0x80006A20;
gCalcMatrix = 0x8013BBC8;
gInputPress = 0x8017797C;
gPlayState = 0x80177854;
gLevelMode = 0x80177880;
gRadioState = 0x8017829C;
gCallTimer = 0x80161690;

gMasterDisp = 0x80137E64;
gPlayer = 0x80178280;
gHudAlpha = 0x80161708;
gCamCount = 0x801778A8;
