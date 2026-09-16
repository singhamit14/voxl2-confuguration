# Boot stub for a DIY M0065 (STM32F103C8T6)
CROSS   ?= arm-none-eabi-
CC       = $(CROSS)gcc
OBJCOPY  = $(CROSS)objcopy
SIZE     = $(CROSS)size

CFLAGS   = -mcpu=cortex-m3 -mthumb -nostdlib -nostartfiles -Os -Wall

all: stub.bin

stub.elf: stub.s stub.ld
	$(CC) $(CFLAGS) -T stub.ld -o $@ stub.s
	$(SIZE) $@

stub.bin: stub.elf
	$(OBJCOPY) -O binary $< $@
	@echo "stub.bin: $$(stat -c%s $@) bytes  (must be < 7168)"

disasm: stub.elf
	$(CROSS)objdump -d $<

clean:
	rm -f stub.elf stub.bin

.PHONY: all clean disasm
