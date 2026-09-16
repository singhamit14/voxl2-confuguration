#!/bin/bash
# Probe and flash a DIY M0065 (STM32F103C8T6 + ST-Link V2).
#
#   ./m0065-flash.sh probe    identify the MCU, check it is a genuine ST part
#   ./m0065-flash.sh flash    write boot stub @0x08000000 + M0065 app @0x08005000
#   ./m0065-flash.sh verify   read back and compare both regions
#
# PROPS OFF. Nothing but the ST-Link should be connected for the first flash.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/m0065.bin"
STUB="$DIR/stub.bin"
APP_ADDR=0x08001C00
STUB_ADDR=0x08000000

die() { echo "ERROR: $*" >&2; exit 1; }

# Many "STM32F103C8T6" Blue Pills are CKS32/GD32-class clones whose SWD DAP
# reports 0x2BA01477 instead of ST's 0x1BA01477, which makes target/stm32f1x.cfg
# refuse to attach. CPUTAPID overrides that check. Override with TAPID=... if a
# board reports something else again.
TAPID="${TAPID:-0x2ba01477}"

ocd() {
    local iface
    for iface in interface/stlink.cfg interface/stlink-v2.cfg; do
        if openocd -f "$iface" \
                   -c "transport select hla_swd" \
                   -c "set CPUTAPID $TAPID" \
                   -f target/stm32f1x.cfg -c "$1" 2>&1; then return 0; fi
    done
    return 1
}

need_tools() {
    command -v openocd >/dev/null || die "openocd not installed: sudo apt install -y openocd stlink-tools"
}

get_app() {
    [ -f "$APP" ] && return 0
    echo "-- fetching the stock M0065 image from the board"
    adb devices | grep -qw device || die "no ADB device and no $APP; plug in VOXL 2 or copy the .bin here"
    adb pull /usr/share/modalai/voxl2-io-tools/firmware/modalai_m0065_firmware_v0_2_RC1_f94baad1.bin "$APP" \
        >/dev/null || die "could not pull the firmware"
}

case "${1:-}" in
probe)
    need_tools
    lsusb | grep -q '0483:3748\|0483:374b' || echo "WARNING: no ST-Link seen on USB"
    echo "=== ST-Link / target ==="
    command -v st-info >/dev/null && st-info --probe
    echo
    echo "=== identity registers ==="
    # openocd 0.11 has no read_memory and mdw prints nothing through -c, so
    # mem2array is the portable way to get these values back out.
    ocd "init; reset halt; \
         mem2array a 32 0xE0042000 1; echo \"DBGMCU_IDCODE = [format 0x%08x \$a(0)]\"; \
         mem2array b 16 0x1FFFF7E0 1; echo \"FLASH_SIZE_KB = \$b(0)\"; \
         mem2array c 32 0x1FFFF7E8 3; echo \"UNIQUE_ID     = [format %08x \$c(0)]-[format %08x \$c(1)]-[format %08x \$c(2)]\"; \
         shutdown" | grep -E "DBGMCU_IDCODE|FLASH_SIZE_KB|UNIQUE_ID|Error"
    cat <<'NOTE'

How to read that:
  DBGMCU_IDCODE  low 12 bits = DEV_ID, high 16 = REV_ID.
                 Genuine STM32F103C8 is DEV_ID 0x410 (medium density).
                 REV_ID 0x0000/0x2000/0x2001/0x2003 are real ST silicon.
                 GD32/CKS32/CH32 clones also claim 0x410 but carry odd REV_IDs
                 (0x1303 is a common GD32 tell).
  flash size     genuine C8 reports 64. A part reporting 64 but happily
                 programming past 0x08010000 is a relabelled 128 KB clone.
  unique ID      all-zero or repeating across boards means a clone.

A clone is not automatically fatal here -- the firmware only uses TIM2/3/4,
GPIOA/GPIOB and a USART -- but if anything misbehaves, suspect it first.
NOTE
    ;;

flash)
    need_tools
    [ -f "$STUB" ] || die "stub.bin missing -- run 'make' first"
    get_app
    echo "-- stub $(stat -c%s "$STUB") bytes -> $STUB_ADDR"
    echo "-- app  $(stat -c%s "$APP")  bytes -> $APP_ADDR"
    # No mass_erase: it times out on CKS32/GD32 clones, and `program` erases the
    # sectors it writes anyway.
    ocd "init; reset halt; \
         program $STUB $STUB_ADDR verify; \
         program $APP $APP_ADDR verify; \
         reset run; shutdown" || die "flash failed"
    echo
    echo "Flashed. The board should now print 'ModalAi M0065 Board Starting..' on its"
    echo "debug UART. PWM pins: PA0 PA1 PB8 PB9 PA6 PA7 PB0 PB1 -- SCOPE THEM before"
    echo "connecting any ESC."
    ;;

verify)
    need_tools
    get_app
    ocd "init; reset halt; \
         verify_image $STUB $STUB_ADDR bin; \
         verify_image $APP $APP_ADDR bin; shutdown"
    ;;

*)
    awk 'NR>1 && /^#/ { sub(/^# ?/,""); print; next } NR>1 { exit }' "$0"
    exit 1
    ;;
esac
