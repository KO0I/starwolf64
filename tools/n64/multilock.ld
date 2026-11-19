OUTPUT_ARCH(mips)
ENTRY(ML_Dispatch)
SECTIONS {
  . = 0x8015B320;
  .ml_state : { KEEP(*(.data.ML_State)) }
  . = ALIGN(16);
  .text : { *(.text.entry) *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) *(.sdata*) }
  . = ALIGN(16);
  .bss (NOLOAD) : {
    ML_BssStart = .;
    *(.bss*) *(.sbss*) *(COMMON)
    ML_BssEnd = .;
  }
  . = ALIGN(32);
  ML_End = .;
  ASSERT(ML_State == 0x8015B320, "Multilock state must start the loaded image")
  ASSERT(ML_End <= 0x8015F310, "Multilock exceeds the unused RMON stack")
  /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.pdr) *(.eh_frame*) *(.gnu.attributes) *(.mdebug*) }
}
/* US 1.1 symbol maps from commit 9df4bbab, checked against the retail ROM. */
Audio_InitBombSfx = 0x8001CB80;
Audio_KillSfxBySource = 0x8001A500;
Audio_PlayBombFlightSfx = 0x8001CCDC;
Audio_PlaySfx = 0x80019218;
Graphics_SetScaleMtx = 0x8005980C;
Math_Atan2F = 0x80005100;
Math_SmoothStepToAngle = 0x8009BD38;
Math_SmoothStepToF = 0x8009BC2C;
Matrix_MultVec3f = 0x80006970;
Matrix_MultVec3fNoTranslate = 0x80006A20;
Matrix_Pop = 0x80005740;
Matrix_Push = 0x80005708;
Matrix_RotateX = 0x80005D44;
Matrix_RotateY = 0x80005E90;
Matrix_RotateZ = 0x80005FE0;
Matrix_Scale = 0x80005C34;
Matrix_SetGfxMtx = 0x80006EB8;
Matrix_Translate = 0x80005B00;
Object_Kill = 0x80060FBC;
Object_PlayerSfx = 0x80060F30;
Object_SetInfo = 0x800612B8;
Player_SetupArwingShot = 0x800AC290;
Player_SetupTankShot = 0x800AC650;
PlayerShot_CollisionCheck = 0x80038140;
RCP_SetupDL = 0x800B8DD0;
Rand_ZeroOne = 0x80004EB0;
memcpy = 0x80023FC0;
sinf = 0x80023090;
cosf = 0x80023250;
gActors = 0x80163FE0;
gBombCount = 0x80177DA0;
gCalcMatrix = 0x8013BBC8;
gCamCount = 0x801778A8;
gChargeTimers = 0x801779C8;
gClearPlayerInfo = 0x80177824;
gControllerRumbleTimers = 0x80177BD0;
gCurrentLevel = 0x80178234;
gDefaultMod = 0x800C5D34;
gDefaultReverb = 0x800C5D3C;
gDefaultSfxSource = 0x800C5D28;
gGfxMatrix = 0x8013B3C0;
gGroundHeight = 0x80177940;
gInputHold = 0x80177974;
gInputPress = 0x8017797C;
gItems = 0x801737E0;
gLaserStrength = 0x80161AA8;
gLevelMode = 0x80177880;
gLight3B = 0x80178368;
gLight3Brightness = 0x8017836C;
gLight3G = 0x80178364;
gLight3R = 0x80178360;
gLight3x = 0x80178370;
gLight3y = 0x80178374;
gLight3z = 0x80178378;
gLockOnTargetViewPos = 0x80161578;
gMasterDisp = 0x80137E64;
gObjectInfo = 0x800CC124;
gPathProgress = 0x80177D20;
gPlayer = 0x80178280;
gPlayerShots = 0x80174050;
gVersusMode = 0x801778E8;
D_enmy_800CFDF4 = 0x800CFDF4;

gReflectY = 0x80161410;
