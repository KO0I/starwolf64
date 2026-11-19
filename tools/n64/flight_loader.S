.set noreorder
.set noat
.text
.globl Flight_Loader
Flight_Loader:
    lui $t0,0x8013
    ori $t0,$t0,0x7e90
    lw $t1,0($t0)
    lui $t2,0x3644
    ori $t2,$t2,0x4f46
    beq $t1,$t2,loaded
    nop
    lui $t1,(FLIGHT_ROM_ADDRESS >> 16)
    ori $t1,$t1,(FLIGHT_ROM_ADDRESS & 0xffff)
    addiu $t2,$t0,FLIGHT_MODULE_BYTES
copy:
    lw $t3,0($t1)
    sw $t3,0($t0)
    cache 0x19,0($t0)
    cache 0x10,0($t0)
    addiu $t0,$t0,4
    bne $t0,$t2,copy
    addiu $t1,$t1,4
    sync
loaded:
    j FLIGHT_ENTRY
    nop

.globl Flight_AeroLoader
Flight_AeroLoader:
    addiu $sp,$sp,-24
    sw $t0,0($sp)
    sw $t1,4($sp)
    sw $t2,8($sp)
    sw $t3,12($sp)
    sw $t9,16($sp)
    sw $ra,20($sp)
    lui $t0,0x800b
    ori $t0,$t0,0x26a4
    xor $t9,$ra,$t0
    sltu $t9,$zero,$t9
    j Flight_Loader
    addiu $t9,$t9,4
