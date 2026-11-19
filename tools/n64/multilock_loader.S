.set noreorder
.set noat
.text
.globl ML_Loader
ML_Loader:
    lui $t0,(ML_MODULE_RAM >> 16)
    ori $t0,$t0,(ML_MODULE_RAM & 0xffff)
    lw $t1,0($t0)
    lui $t2,0x4d4c
    ori $t2,$t2,0x4f43
    beq $t1,$t2,loaded
    nop
    lui $t1,(ML_ROM_ADDRESS >> 16)
    ori $t1,$t1,(ML_ROM_ADDRESS & 0xffff)
    addiu $t2,$t0,ML_MODULE_BYTES
copy:
    lw $t3,0($t1)
    sw $t3,0($t0)
    addiu $t0,$t0,4
    bne $t0,$t2,copy
    addiu $t1,$t1,4
    lui $t0,(ML_MODULE_RAM >> 16)
    ori $t0,$t0,(ML_MODULE_RAM & 0xffff)
writeback:
    cache 0x15,0($t0)
    addiu $t0,$t0,16
    bne $t0,$t2,writeback
    nop
    sync
    lui $t0,(ML_MODULE_RAM >> 16)
    ori $t0,$t0,(ML_MODULE_RAM & 0xffff)
invalidate:
    cache 0x10,0($t0)
    addiu $t0,$t0,32
    bne $t0,$t2,invalidate
    nop
    sync
loaded:
    j ML_DISPATCH
    nop
