OUTPUT_ARCH(mips)
ENTRY(Multi_Installed)
SECTIONS {
  . = 0x8027D000;
  .multilock_state : { KEEP(*(.multilock_state)) }
  .text : { *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) *(.sdata*) }
  .bss : { *(.bss*) *(.sbss*) *(COMMON) }
  Multi_End = .;
  ASSERT(Multi_End <= 0x80281000, "Multi-shot payload overlaps fixed graphics buffers")
  /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.pdr) *(.eh_frame*) *(.gnu.attributes) }
}
INCLUDE tools/n64/multilock_symbols.ld
INCLUDE tools/n64/multilock_gfx.ld
