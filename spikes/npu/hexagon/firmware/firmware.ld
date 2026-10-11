/* The program memory of the Hexagon candidate: 1 MiB at 0x4000_0000 on the
 * core's bus (spikes/npu/hexagon/integration/hexagon_npu.h), code first and
 * the stack at the top. */
ENTRY(_start)

MEMORY
{
    program (rwx) : ORIGIN = 0x40000000, LENGTH = 1M
}

SECTIONS
{
    .text : { *(.text .text.*) } > program
    .rodata : { *(.rodata .rodata.*) } > program
    .data : { *(.data .data.*) } > program
    .bss : { *(.bss .bss.*) } > program
    _stack_top = ORIGIN(program) + LENGTH(program) - 16;
}
