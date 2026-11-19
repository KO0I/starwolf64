.set noreorder
.set noat
.text
.globl Original_DrawIndicators
Original_DrawIndicators:
 addiu $sp,$sp,-120
 sw $ra,116($sp)
 j 0x8005750c
 nop
.globl Original_DrawActorOnRails
Original_DrawActorOnRails:
 addiu $sp,$sp,-64
 sw $s0,32($sp)
 j 0x8005d95c
 nop
.globl Original_DrawActorAllRange
Original_DrawActorAllRange:
 addiu $sp,$sp,-96
 sw $s0,28($sp)
 j 0x8005dbc8
 nop
