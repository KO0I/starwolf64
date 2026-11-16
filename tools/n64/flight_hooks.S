.set noreorder
.set noat
.section .text.entry,"ax",@progbits
.globl Flight_Entry
Flight_Entry:
    sltiu $at,$t9,4
    bnez $at,normalHook
    nop
    addiu $at,$t9,-4
    lw $t0,0($sp)
    lw $t1,4($sp)
    lw $t2,8($sp)
    lw $t3,12($sp)
    lw $t9,16($sp)
    lw $ra,20($sp)
    beqz $at,Flight_BoostGate
    addiu $sp,$sp,24
    j Flight_BrakeGate
    nop
normalHook:
    move $a0,$s0
    move $a1,$t9
    lw $a2,0x84($sp)
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    sw $t9,24($sp)
    jal Flight_Hook
    nop
    lw $t9,24($sp)
    lw $ra,28($sp)
    beq $t9,$zero,move360
    addiu $sp,$sp,32
    addiu $at,$zero,1
    beq $t9,$at,moveRails
    nop
    addiu $at,$zero,2
    beq $t9,$at,camRails
    nop
cam360:
    bnez $v0,cam360done
    lui $at,0x800e
    jr $ra
    lwc1 $f6,-0x7574($at)
cam360done:
    j 0x800b6834
    nop
camRails:
    bnez $v0,camRailsdone
    lui $v0,0x8017
    jr $ra
    lbu $v0,0x7c98($v0)
camRailsdone:
    j 0x800b5d1c
    nop
move360:
    bnez $v0,move360done
    lui $at,0x800e
    jr $ra
    lwc1 $f4,-0x7958($at)
move360done:
    mtc1 $zero,$f20
    j 0x800ae9e8
    nop
moveRails:
    bnez $v0,moveRailsdone
    lui $at,0x800e
    jr $ra
    lwc1 $f4,-0x78f0($at)
moveRailsdone:
    mtc1 $zero,$f20
    j 0x800af55c
    nop

.globl Flight_BoostGate
Flight_BoostGate:
    lw $at,0x1cc($s0)
    bnez $at,boostOriginal
    nop
    lui $at,%hi(gFlightState+4)
    lw $at,%lo(gFlightState+4)($at)
    bnez $at,boostSkip
    nop
boostOriginal:
    lw $t9,0x4dc($s0)
    bnezl $t9,boostBranch
    lw $v0,0x27c($s0)
    j 0x800b26a8
    nop
boostBranch:
    j 0x800b2740
    nop
boostSkip:
    j 0x800b273c
    nop

.globl Flight_BrakeGate
Flight_BrakeGate:
    lw $at,0x1cc($s0)
    bnez $at,brakeOriginal
    nop
    lui $at,%hi(gFlightState+4)
    lw $at,%lo(gFlightState+4)($at)
    bnez $at,brakeSkip
    nop
brakeOriginal:
    lw $v0,0($a1)
    j 0x800b2cc0
    addiu $a3,$zero,5
brakeSkip:
    j 0x800b2d48
    addiu $a3,$zero,5
