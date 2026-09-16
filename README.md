# VOXL 2 Configuration

Bench notes, runbooks and tooling for building an autonomy drone around a **ModalAI VOXL 2 Flight
Deck** (`MDK-F0006-4-V2-C11-T0-M0-X0`, M0054).

Everything here was **measured on a real board**, not copied from datasheets. Where the official
docs are silent or wrong, these notes record what the hardware actually did.

- System image `1.8.02-M0054-14.1a-perf` · kernel 4.19.125 · voxl-suite `1.4.0` · PX4 **1.14.0**

---

## Status

**Working and verified**

- PX4 1.14.0 on the SLPI DSP
- ICM-42688 IMU, calibrated
- Six cameras — 5× OV7251 + 1× IMX214
- 6S power rail, ~24.3 V, via the I2C power monitor
- ELRS/CRSF receiver on J19, `link_quality: 100`
- QGroundControl over the USB-C cable through a TCP relay
- RC channel map verified end to end (AETR: ch1 roll, ch2 pitch, ch3 throttle, ch4 yaw)
- Battery configured: 6S, 9000 mAh
- **DIY PWM ESC adapter** — a generic Blue Pill running ModalAI's M0065 firmware, detected by PX4 and
  driving 4 verified PWM outputs, instead of waiting 30-40 days for the real M0065
- Autonomy stack installed and configured — `voxl-vision-hub` with VIO and obstacle avoidance
  enabled, QVIO, OpenVINS, DFS, TFLite

**Not yet present** — ESC, props, GPS/magnetometer, Wi-Fi hardware. Frame and motors are in hand.

The software is ready; the airframe is the critical path.

---

## Quick start

Connect QGroundControl over the USB-C cable — one command:

```bash
./voxl-qgc.sh up          # relay + port forward + bridge + launches QGC
./voxl-qgc.sh status      # relay / forwards / bridge count
./voxl-qgc.sh down        # revert to stock configuration
```

Read-only board audit:

```bash
./voxl-audit.sh
```

---

## Files

| File | Contents |
|---|---|
| [`adb-shell-commands.md`](adb-shell-commands.md) | **Full ADB/PX4 command reference**, organised by task |
| [`m0065-diy.md`](m0065-diy.md) | Building a PWM ESC adapter from a Blue Pill: pinout reverse-engineered from ModalAI's firmware, the 16 MHz crystal fix, PX4 setup |
| `m0065-stub/` | Boot stub + flashing tooling for that adapter |
| [`SETUP.md`](SETUP.md) | Version checks, what hardware is attached, §3h battery/power |
| [`RCSETUP.md`](RCSETUP.md) | ELRS/CRSF setup, QGC connection (§6b), RC calibration (§7) |
| [`AUTONOMY.md`](AUTONOMY.md) | Roadmap: hover → VIO → obstacle avoidance → offboard → perception |
| [`build-guide.html`](build-guide.html) / `VOXL2-Drone-Build.pdf` | Staged hardware build plan |
| `voxl-qgc.sh` | `up`/`down`/`status` for the bench QGC link |
| `voxl-audit.sh` | Read-only one-shot board audit |
| `mavlink-tcp-relay.py` + `.service` | Board-side MAVLink TCP↔UDP relay (deploys to `/data/`) |
| `qgc-bridge.py` | PC-side bridge so QGC auto-connects with no comm-link setup |
| `mavlink-census.py` | Diagnostic bridge: per-(sysid, compid, message) rates + CRC error counts |
| `rc-watch.py` | Proves stick motion on the exact byte stream QGC consumes |
| `rc-axes.py` | Correlates raw channels against PX4 axes — catches a mis-mapped calibration |
| `rc-order.py` | One-stick-at-a-time channel identification, independent of `RC_MAP_*` |
| `backup/` | This unit's factory calibration and PX4 parameters |

---

## Findings worth knowing

Things that cost real debugging time.

### `px4-param` output has a symbol that matters

```
x + BAT1_CAPACITY [1,42] : 9000.0000
```

`x` = a running module reads it · `+` = saved to storage · `*` = changed but **not saved** ·
**a `-1` first index means nothing reads it.** That last case is a trap: `BAT1_V_DIV` exists, is
settable, and is displayed by QGC — while being read by nothing on this board.

### QGC's battery voltage-divider calibration does nothing here

Power is read over **I2C from an INA231 monitor**, not an analog ADC. `BAT1_V_DIV` and
`BAT1_A_PER_V` are unused; current is scaled by `VOXLPM_SHUNT_BAT`. Voltage needs no calibration —
it read 24.27 V against 24.43 V on a multimeter.

The board shipped with `BAT1_N_CELLS = 3` on a 6S pack. Fix that first; every percentage and
failsafe threshold derives from it.

### Verify the RC map after any QGC radio calibration

On this CRSF link the calibration wizard mapped roll and pitch onto *switch* channels, leaving
roll pinned at −0.978 and pitch at 0. `rc-axes.py` catches it; `rc-order.py` establishes ground
truth independently of `RC_MAP_*`.

### Run exactly one MAVLink bridge

The relay hands each PX4 datagram to a single reader, so a second bridge leaves one deaf and QGC
receives a partial stream. Telemetry and parameter download still work, which makes it look like a
vehicle fault rather than plumbing. `./voxl-qgc.sh status` must never report more than one bridge.

### Some topics and commands are silent by design

PX4 is split across the apps processor and the SLPI DSP, and the muorb bridge does not forward
everything. `rc_channels` and `manual_control_input` read **empty** — use `input_rc` and
`manual_control_setpoint`. `px4-commander status` and `px4-top` print nothing useful; read
`px4-listener vehicle_status` instead.

### Normal for CRSF, not faults

`rssi: -1` / `rssi=255`, and `rc_total_frame_count: 0`.

### Commands that leave the board broken

`voxl-esc detect` stops **and disables** `voxl-px4`. `voxl-camera-server -l` stops the camera
service. After any debugging, run `voxl-inspect-services` and look for **Enabled + Not Running**.

### The M0065 PWM adapter expects a 16 MHz crystal

A Blue Pill has 8 MHz. ModalAI's firmware sets `PLLXTPRE` (HSE/2) x9 expecting 16 MHz -> 72 MHz, so
on 8 MHz it runs at **36 MHz — everything half speed**: the host UART lands at 461538 instead of
921600 and PWM at 200 Hz instead of 400 Hz. The only symptom is an endless
`Board version info response timeout`. One byte fixes it (`m0065-diy.md` §9), or fit a 16 MHz part.

Its firmware is also **not standalone**: it links at `0x08001C00` and expects ModalAI's
(undistributed) bootloader below. A 44-byte stub at `0x08000000` that sets `VTOR` and jumps is
enough — the bootloader is only needed for UART firmware updates, and SWD replaces that.

### VOXL 2 has no onboard Wi-Fi and no USB-A port

Wi-Fi needs a USB expansion board plus a dongle with an **out-of-tree Realtek driver** —
only `rtl8188eus`, `rtl8812au` and `rtl8821cu` chipsets have drivers on this image. An RTL8192CU
dongle will not work: it needs in-tree `rtlwifi` + `mac80211`, neither of which is built here.

---

## Safety

These are bench notes for a vehicle that cannot yet fly. Props stay off for everything here.
The USB-C MAVLink relay is a **bench convenience** — it is not a flight configuration.

Nothing the relay changes persists: it is never enabled, and `voxl-mavlink-server` stays enabled,
so a power cycle restores stock configuration by itself.
