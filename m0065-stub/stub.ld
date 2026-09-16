/* The stub must fit entirely below the application at 0x08001C00. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 7K    /* 0x08000000-0x08001BFF */
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 20K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
    .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
    .text       : { *(.text*) }            > FLASH

    /DISCARD/   : { *(.ARM.exidx*) *(.comment) }
}

ASSERT(. <= 0x08001C00, "stub overruns the application load address")
