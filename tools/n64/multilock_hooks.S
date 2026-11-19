.set noreorder
.set noat
.text
.align 2
.macro ORIGINAL name, first, second, resume
.globl \name
.type \name,@function
\name:
    .word \first
    .word \second
    j \resume
    nop
.size \name,.-\name
.endm
ORIGINAL Original_ActorInitialize,0x00801025,0x00001825,0x800613CC
ORIGINAL Original_ItemInitialize,0x00801025,0x2404006C,0x8006144C
ORIGINAL Original_ShotInitialize,0x00801025,0x24040070,0x80035E50
ORIGINAL Original_FindLockTarget,0x27BDFFD8,0xAFB1001C,0x8003BB54
ORIGINAL Original_CanLockOn,0x3C038016,0x24633FE0,0x800AD120
ORIGINAL Original_UpdateLockOn,0x27BDFFC0,0xAFB00020,0x800AD1FC
ORIGINAL Original_DrawItem,0x27BDFFE8,0xAFBF0014,0x8005CB4C
ORIGINAL Original_ClearObjects,0x27BDFFE0,0xAFBF001C,0x800A6150
ORIGINAL Original_PlayerDown,0x27BDFFE0,0xAFB00018,0x800B41F4

.globl Multi_HomingGate
Multi_HomingGate:
    move $a0,$s0
    jal Multi_SelectShotTarget
    nop
    bltz $v0,Multi_HomingStock
    nop
    move $a3,$v0
    lui $a1,0x800d
    addiu $a1,$a1,-25564
    j 0x8003d230
    nop
Multi_HomingStock:
    move $a3,$zero
    move $a0,$zero
    lui $v0,0x8016
    lui $a1,0x800d
    mtc1 $zero,$f16
    j 0x8003d0fc
    nop

.globl Multi_ImpactGate
Multi_ImpactGate:
    addiu $sp,$sp,-32
    sw $a0,16($sp)
    sw $a1,20($sp)
    sw $a2,24($sp)
    sw $ra,28($sp)
    jal Multi_IsOwnedShot
    nop
    lw $a0,16($sp)
    lw $a1,20($sp)
    lw $a2,24($sp)
    lw $ra,28($sp)
    addiu $sp,$sp,32
    lui $at,0x40f0
    mtc1 $at,$f10
    beqz $v0,Multi_ImpactStock
    nop
    swc1 $f10,0x44($a0)
    j 0x8003641c
    nop
Multi_ImpactStock:
    j 0x800363d0
    nop

.globl Multi_ChargeGate
Multi_ChargeGate:
    move $a0,$zero
    jal Multi_Enabled
    nop
    bnez $v0,Multi_ChargeContinue
    nop
    lui $at,0x8017
    sw $zero,0x79c8($at)
Multi_ChargeContinue:
    j 0x80069bec
    nop

.globl Multi_CollectBombGate
Multi_CollectBombGate:
    move $a0,$s0
    jal Multi_CollectBomb
    nop
    lui $a3,0x8018
    addiu $a3,$a3,-32128
    lw $t6,0($a3)
    j 0x80067c9c
    nop

ORIGINAL Original_MoveRails,0x27BDFF60,0xAFB00028,0x800AF084
ORIGINAL Original_Move360,0x27BDFF80,0xF7B40020,0x800AE4AC
