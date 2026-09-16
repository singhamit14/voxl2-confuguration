# VOXL 2 — ELRS / CRSF Receiver Setup

Connecting an ExpressLRS receiver to the VOXL 2 and proving the link is real.

**Status: working.** Verified on this board **2026-09-15** — `link_quality: 100`,
16 channels, sticks reaching the flight-control layer. Every output below is the real
captured output from that session.

- **Board:** `MDK-F0006-4-V2-C11-T0-M0-X0` — VOXL 2 Flight Deck (M0054), voxl-suite 1.4.0
- **Protocol:** CRSF (ELRS native)
- **Port:** J19, RC UART = `SSC_QUP7`
- **Companion docs:** `SETUP.md` (general inspection), `build-guide.html` (the drone build),
  `AUTONOMY.md` (what comes after first flight)

---

## 1. Bind the receiver first

**Do this before touching the VOXL.** Binding is purely transmitter ↔ receiver; the flight
controller plays no part in it. Skipping this step means debugging the flight controller for a
problem that lives entirely in the radio.

- Bind the ELRS RX to your TX on the bench, powered from anything convenient.
- Confirm RX and TX firmware **major versions match**. ELRS refuses to link across a mismatch.

The RX LED reports this layer independently of everything downstream:

| LED | State |
|---|---|
| Solid | Bound and connected |
| Slow blink | Bound, no link to TX |
| Fast blink | Bind mode |

---

## 2. Wiring

1. **Power the board down completely.**
2. ELRS RX connects to **J19**. Four wires: `5V`, `GND`, and the CRSF UART pair.
3. **Cross the data pair** — RX's TX → board's RX, RX's RX → board's TX.
4. All J19 signals are **3.3V logic**.

> ⚠️ **J19 carries two UARTs.** The RC UART is `SSC_QUP7`; the GNSS UART is `SSC_QUP6`
> (and mag I2C shares the connector too). Landing on the GPS pins gives you a board that looks
> perfectly healthy with no RC at all. Check the pinout against the
> [connector datasheet](https://docs.modalai.com/voxl2-connectors/) for your board revision.

**Crossing the pair wrong is the most common ELRS bring-up failure**, and it presents exactly
like a dead receiver — no error, just silence.

---

## 3. Configuration

No change needed. `/etc/modalai/voxl-px4.conf` ships with:

```bash
RC=CRSF_RAW
```

Check it with:

```bash
adb shell 'grep "^RC=" /etc/modalai/voxl-px4.conf'
```

What that setting does, from `/usr/bin/voxl-px4-start`:

```bash
elif [ "$RC" == "CRSF_RAW" ]; then
    /bin/echo "Starting CRSF RC driver"
    qshell crsf_rc start -d 7
```

`-d 7` is `SSC_QUP7` — the RC UART on J19. The driver runs on the SLPI DSP, not Linux, which is
why there is no `/dev/ttyHS*` device to inspect for RC.

| RC= value | Use for |
|---|---|
| `CRSF_RAW` | **ELRS and Crossfire** — PX4 parses CRSF directly |
| `CRSF_MAV` | Receivers that output MAVLink rather than raw CRSF |
| `M0065_SBUS` | S.Bus via the VOXL 2 IO expander |
| `SPEKTRUM` | Spektrum satellite receivers |
| `EXTERNAL` | RC forwarded over MAVLink from a GCS |
| `FAKE_RC_INPUT` | Bench testing with no radio at all |

---

## 4. Verifying the link

Work down in order. Each step isolates one layer — stop at the first failure.

### 4a. Board and flight stack are up

```bash
adb devices -l
adb shell systemctl is-active voxl-px4
```

`voxl-px4` must report `active`. If not:
`adb shell 'systemctl enable voxl-px4 && systemctl restart voxl-px4'`

### 4b. The primary check

```bash
adb shell 'px4-listener input_rc'
```

Known-good output from this board:

```
 input_rc
    timestamp: 337916899 (0.003558 seconds ago)
    timestamp_last_signal: 337916889
    rssi: -1
    rssi_dbm: -14.00000
    rc_lost_frame_count: 0
    rc_total_frame_count: 0
    values: [1500, 1500, 1001, 1500, 1011, 1011, 1011, 1011, 1011, 1018, 1503, 1503, 1000, 1000, 2000, 2000, 0, 0]
    channel_count: 16
    rc_failsafe: False
    rc_lost: False
    input_source: 14
    link_quality: 100
```

**Read the right fields.** The topic itself publishes whether or not a receiver exists — it was
already publishing on this board before any receiver was owned. These four prove a live link:

| Field | Good | Meaning |
|---|---|---|
| `timestamp_last_signal` | **non-zero** | The single most important field. `0` = nothing ever received |
| `link_quality` | `100` | CRSF link quality percentage |
| `channel_count` | `16` | Receiver negotiated its channels |
| `values[]` | real numbers ~1000–2000 | Actual stick positions in µs |

Supporting fields: `rc_failsafe: False`, `rc_lost: False`, `rc_lost_frame_count` staying low.

> **Two fields that look broken but are not, on CRSF:**
>
> - **`rssi: -1`** — legacy field, unused by the CRSF driver. Signal strength lives in
>   **`rssi_dbm`** (`-14` here) and **`link_quality`** (`100`).
> - **`rc_total_frame_count: 0`** — the `crsf_rc` driver never populates this counter. It stays
>   at `0` on a perfectly healthy link. Do not use it as a liveness check.

### 4c. Sticks move the values

```bash
adb shell 'px4-listener input_rc | grep values'   # move a stick, run again, compare
```

### 4d. End-to-end — data reached the flight controller

This is the check that proves more than the driver is happy: it confirms RC made it all the way
to the control layer.

```bash
adb shell 'px4-listener manual_control_setpoint'
```

```
 manual_control_setpoint
    timestamp: 357568035 (0.043434 seconds ago)
    roll: 0.00000
    pitch: 0.00000
    yaw: 0.00000
    throttle: -0.99796
```

A recent `timestamp` and a `throttle` that tracks your stick means the chain is complete.
`-0.998` is throttle at minimum — the correct and safe resting value.

### 4e. Channel mapping

```bash
adb shell 'px4-listener rc_channels'
```

```
    channels: [0.00000, 0.00000, -0.99796, 0.00000, -1.00000, ...]
    function: [2, 0, 1, 3, -1, -1, ...]
    channel_count: 16
    signal_lost: False
```

`channels[]` is normalised −1…1, easier to read than raw µs. `function[]` maps roles onto
channels, so it is the quickest way to spot a reversed or misordered stick.

> `rc_channels.rssi` reads `255` and its `timestamp` can look stale — like `input_rc.rssi`,
> neither is meaningful here. Trust `input_rc` and `manual_control_setpoint`.

### 4f. Quick repeat check

```bash
/home/amit/voxl/voxl-audit.sh
```

The RC line reports `RC signal present` or `no RC signal (driver up, nothing bound)`.

---

## 5. Troubleshooting

| Symptom | Cause |
|---|---|
| `input_rc` → `never published` | Driver never started. Check `RC=CRSF_RAW`, restart `voxl-px4` |
| `timestamp_last_signal: 0` | Nothing arriving: **TX/RX not crossed**, wrong J19 pins, RX unpowered, or RX not bound to the TX |
| `link_quality` low / `rc_lost_frame_count` climbing | Marginal link — wiring quality, antenna placement, or TX power |
| `rc_failsafe: True` | Receiver is in failsafe — TX off or out of range |
| Values arrive, wrong channels | Channel mapping. Fix in the transmitter, verify via `function[]` in `rc_channels` |
| `rssi: -1` or `rc_total_frame_count: 0` | **Not a fault.** See §4b — normal for CRSF |

---

## 6. Connecting QGroundControl

**This is the blocking step, and it needs hardware this board does not yet have.**

### VOXL 2 has no onboard Wi-Fi

Confirmed on this board and in ModalAI's docs: **M0054 has no Wi-Fi radio.** Wi-Fi comes from a
**USB dongle**, which is why the board ships with Realtek dongle drivers installed:

```bash
adb shell 'dpkg -l | grep -E "rtl88|voxl2-wlan"'
```

```
rtl8188eus   rtl8812au   rtl8812au-vtx   rtl8821cu   voxl2-wlan
```

Those are drivers waiting for hardware. With no dongle attached there is no radio, so:

```bash
adb shell 'ip -4 addr show wlan0'     # Device "wlan0" does not exist.
adb shell 'systemctl start voxl-softap'   # fails - no interface to bind
```

`voxl-wifi` will happily walk you through SoftAP setup and write a valid `hostapd` config with an
SSID. **It does not check that a radio exists.** The config is written for an interface that can
never appear. Running it costs nothing but achieves nothing.

> **Do not read the boot log as evidence of Wi-Fi hardware.** `cnss_wlan_region` and
> `pil_wlan_fw_region` appear in `dmesg` at boot, but these are generic SoC device-tree
> reservations present whether or not a radio is fitted. There is no Wi-Fi driver module and no
> Wi-Fi firmware anywhere on the filesystem — `find / -name "*wlan*.ko"` returns nothing.

### QGC cannot connect over USB-C

Per ModalAI's [connectivity docs](https://docs.modalai.com/voxl-px4-connectivity/), the USB-C
port does not carry a QGC connection. It is ADB only.

### What you need

VOXL 2 has **no USB-A port**, so a dongle needs an expansion board as well. Two wires to the same
place:

| Route | Parts |
|---|---|
| **Wi-Fi** | USB expansion (**M0151**, **M0141**, or **M0090**) + a Realtek dongle — Alfa AWUS036EACS, Alfa AWUS036ACS, or TP-Link TL-WN725N |
| **Ethernet** | **M0062** (Ethernet Expansion + USB Hub), or an expansion board plus any USB-to-Ethernet adapter |

### Check a dongle before you buy it

The board carries **out-of-tree** Realtek drivers only. These bundle their own 802.11 stack,
which is why they work on an image with no `mac80211`:

```bash
adb shell 'for p in rtl8188eus rtl8812au rtl8821cu; do dpkg -L $p 2>/dev/null | grep "\.ko$"; done'
```

```
/lib/modules/4.19.125/kernel/drivers/net/wireless/8188eu.ko    <- RTL8188EUS
/lib/modules/4.19.125/kernel/drivers/net/wireless/88XXau.ko    <- RTL8812AU
/lib/modules/4.19.125/kernel/drivers/net/wireless/8821cu.ko    <- RTL8811CU / RTL8821CU
```

**Only those three chipsets work.** Anything needing an in-tree driver fails, because
`mac80211` is not built on this image — `find / -name "mac80211*"` returns source headers only.

To identify a dongle you already own, plug it into a **Linux PC** and read the chipset the
kernel binds:

```bash
lsusb | grep -i realtek
journalctl -k -n 100 | grep -iE "rtl|8188|8812|8821"
```

> **Worked example — a dongle that does *not* work.** An `0bda:018a` adapter reports
> `rtl8192cu: Chip version 0x10` on a PC. RTL8192CU is an in-tree `rtlwifi` part, so on the VOXL
> it fails three ways at once: no `rtl8192cu.ko`, no `mac80211.ko`, and no
> `rtl8192cufw_TMSC.bin` firmware. Being Realtek is not sufficient — the chipset must be one of
> the three above.

**Recommended:** TP-Link TL-WN725N (RTL8188EUS) — cheapest, on ModalAI's tested list, low power
draw.

Once a dongle is attached, the documented flow works as written:

```bash
adb shell voxl-wifi        # choose station or softap
adb reboot && adb wait-for-device
adb shell voxl-my-ip
```

In **station** mode, set `primary_static_gcs_ip` in `/etc/modalai/voxl-mavlink-server.conf` to
your PC's LAN address and `systemctl restart voxl-mavlink-server`. In **softap** mode the board
serves `192.168.8.10` first, which already matches the shipped default — no config change.

Verify from the board that a GCS actually attached:

```bash
adb shell voxl-inspect-gcs-ip      # reads "none" until QGC connects
```

> **This is not a detour for the build.** A flying drone needs a wireless GCS link regardless —
> you cannot fly on a USB cable. The expansion board and dongle are build parts, not a
> workaround for calibration.

### Interim option, unsupported

Python 3.6 is on the board, so a small TCP↔UDP relay plus `adb forward tcp:14550` lets QGC
attach over a **TCP** link through the USB cable. Useful for bench calibration before the
expansion hardware arrives. It is outside ModalAI's supported configuration and is bench-only.

---

## 6b. Bench option: QGC over the USB cable (TCP relay)

Working and tested on this board. **Bench only** — you cannot fly on a USB cable, so this is a
stopgap until the Wi-Fi dongle and expansion board arrive.

### How it works

```
QGC (PC, TCP 14550) --adb forward--> board TCP 14650 --UDP--> PX4 14558
                                     board UDP 14559 <--UDP-- PX4
```

`voxl-mavlink-server` normally occupies the GCS path. It **cannot** be shared: it binds
`0.0.0.0:14550` and transmits to `<gcs_ip>:14550`, so no second socket can own that port — even
on a separate loopback alias, which fails with `EADDRINUSE`. The relay therefore *replaces* it,
speaking directly to PX4's apps-side bridge on 14558/14559.

The systemd unit declares `Conflicts=voxl-mavlink-server.service` and stops it automatically.
**The two never run together.**

### Files

| Path | Purpose |
|---|---|
| `/data/mavlink-tcp-relay.py` | The relay (local copy: `mavlink-tcp-relay.py`) |
| `/etc/systemd/system/mavlink-tcp-relay.service` | Unit file |
| `qgc-bridge.py` | PC-side bridge so QGC auto-connects (no comm link needed) |

### Use it — one command

`voxl-qgc.sh` wraps the whole sequence and adds the checks that caught us out: it installs the
relay and unit if the board is missing them, verifies the service actually came up, clears stale
forwards, and **refuses to start a second bridge**.

```bash
./voxl-qgc.sh up        # then open QGroundControl; Ctrl-C stops the bridge
./voxl-qgc.sh status    # relay / forwards / bridge count
./voxl-qgc.sh down      # revert to stock
```

`status` is the first thing to run when something looks wrong — `bridges running` must never
exceed 1.

### Use it — the same thing by hand

QGroundControl auto-connects to MAVLink arriving on UDP 14550. `qgc-bridge.py` on the PC feeds
it there, so you never touch the Comm Links dialog:

```bash
adb shell 'systemctl start mavlink-tcp-relay'   # board side (stops voxl-mavlink-server)
adb forward tcp:14551 tcp:14650                 # PC -> board
./qgc-bridge.py                                 # leave running in its own terminal
```

Then just open QGroundControl. It connects on its own.

The bridge prints throughput every 5 seconds, and says `QGC is talking back - connected` once
QGC replies — useful for telling "no data" apart from "data flowing, QGC not listening".

### Use it — manual TCP link

If you prefer configuring the link explicitly, skip `qgc-bridge.py` and forward to 14550 instead:

```bash
adb shell 'systemctl start mavlink-tcp-relay'
adb forward tcp:14550 tcp:14650
```

In QGC: **Application Settings → Comm Links → Add**.

> **The host and port fields are not shown until you choose a Type.** The dialog opens with only
> **Name** and **Type**. Pick **TCP** from the Type dropdown and *then* **Server Address** and
> **Port** appear beneath it. Enter `127.0.0.1` and `14550`, click OK, select the link, Connect.

### Switch back for flight

```bash
adb shell 'systemctl stop mavlink-tcp-relay && systemctl start voxl-mavlink-server'
adb forward --remove-all
```

### Verified

A 6-second capture through the relay decoded real telemetry — note `RC_CHANNELS`, which is what
the Radio calibration page reads:

```
  30  ATTITUDE               x89
  65  RC_CHANNELS            x30
  74  VFR_HUD                x23
   0  HEARTBEAT               x6
  32  LOCAL_POSITION_NED      x6
   1  SYS_STATUS              x6
```

Uplink confirmed separately: `12027 B to GCS, 105 B to PX4`.

> **Why TCP and not UDP:** `adb forward` only carries TCP. The relay splits the TCP byte stream on
> MAVLink frame boundaries so each frame goes out as exactly one UDP datagram — a naive byte-for-byte
> copy would corrupt framing.

> **Not supported by ModalAI.** Their documented position is that QGC cannot connect over USB-C.
> This works, but you own it. Revert to `voxl-mavlink-server` before flying.

---

## 7. RC calibration in QGroundControl

> ⚠️ **Props off. Vehicle disarmed.** Calibration sweeps stick ranges, and a mis-set throttle
> channel on an armed vehicle spins motors.

**Before starting:** transmitter on, receiver bound (§4 shows `link_quality: 100`), board
powered, QGC connected per §6.

1. **Vehicle Setup → Radio** (the gear icon in QGC's toolbar).

2. **Sanity-check first.** Move the sticks and watch the channel bars move. If they do not move,
   **do not assume it is the RC link** — on this bench it never was. Prove where the break is
   with `rc-watch.py` before changing anything (§7.1).

### 7.1 If the channel bars do not move

Measured on this board, 16 Sep 2026 — the bars not moving was **a second bridge process**,
nothing to do with RC.

**Prove the chain end to end first.** `rc-watch.py` taps the exact byte stream QGC consumes,
CRC-validates it, and reports per-channel min/max, so it separates "the data never moves" from
"QGC is not drawing it":

```bash
./rc-watch.py 40          # then sweep all four sticks and flip the switches
```

A healthy result — this is what this board actually produces:

```
ch1   min=1001  max=2000  span= 999  <-- MOVED
ch2   min=1001  max=2000  span= 999  <-- MOVED
ch3   min=1001  max=2000  span= 999  <-- MOVED
ch4   min=1001  max=2000  span= 999  <-- MOVED
VERDICT: the stream QGC receives DOES carry live stick motion.
```

If the spans are non-zero, the RC link, PX4 and the relay are all fine and the fault is on the
PC side. **The cause here was two bridges running at once.** The relay hands each PX4 datagram
to exactly one reader, so a second client leaves one of them deaf and QGC gets a partial stream
— telemetry and parameters still work, which is why it reads as "connected but Radio frozen":

```bash
pgrep -af 'qgc-bridge|mavlink-census'    # must list exactly ONE
```

> While the relay is running, `voxl-inspect-services` will always list
> **`voxl-mavlink-server` as Enabled + Not Running**. That is the relay's `Conflicts=` directive
> doing its job, not a stuck service — expect it, and ignore it until you revert.

`mavlink-census.py` is the diagnostic stand-in for `qgc-bridge.py` (run one *or* the other). It
prints a per-(sysid, compid, message) rate table plus CRC error counts in both directions:

```bash
./mavlink-census.py
```

On a healthy link: `RC_CHANNELS` at ~5 Hz from **sys=1 comp=1** (same ID as `HEARTBEAT`, so QGC
cannot be dropping it on a sysid mismatch), `bad(down)=0`, and `QGC_talking=True` with QGC
heartbeating back as `255/190`.

**Two hypotheses this ruled out — do not spend time on either again:**

- *"Parameters have not finished downloading."* They finish in **13 s**. Launch QGC with
  `QT_LOGGING_RULES="VehicleLog.debug=true"` and it prints `_parametersReady true`. PX4 reports
  `820/2162 parameters used`, so the ~821 params QGC pulls **is** the complete set.
- *"`COM_RC_IN_MODE=3` disables the sticks."* On PX4 1.14 value 3 is *"RC and Joystick, keep
  first"*; **4** is the one that disables stick input. 3 is ModalAI's shipped default and is
  correct — `manual_control_setpoint` shows `valid: True, data_source: 1` (RC) with it set.

> `rc_channels` and `manual_control_input` read **empty** via `px4-listener` on this board. That
> is the muorb DSP bridge not forwarding those topics, not a fault. Trust `input_rc` and
> `manual_control_setpoint`, which are both populated.

3. **Set the transmitter mode** (top-right of the Radio page): Mode 1 / 2 / 3 / 4. **Mode 2**
   (throttle on the left stick) is the most common. Getting this wrong makes the whole
   calibration wrong.

4. **Click `Calibrate`.**

5. QGC asks you to **lower the throttle fully and centre all other sticks**, then click Next.

6. **Follow the on-screen diagram.** QGC shows one stick position at a time — move to it and
   click Next. The sequence walks throttle, yaw, roll and pitch through both extremes.

7. When prompted, **move every switch and dial through its full range** so QGC can see them.

8. **Click Next to finish.** QGC writes the `RC_MAP_*` mappings and the per-channel
   `RC<n>_MIN` / `MAX` / `TRIM` parameters to the flight controller.

9. **Verify** back on the Radio page: sticks centred should read ~1500, and the endpoints should
   reach their min and max cleanly.

### Confirm from the board

```bash
adb shell 'px4-listener rc_channels'
adb shell 'px4-listener manual_control_setpoint'
```

In `rc_channels`, `function[]` shows the role assigned to each channel. In
`manual_control_setpoint`, `roll` / `pitch` / `yaw` / `throttle` should track the right sticks —
throttle at minimum reads `-1.0`.

> **If roll and pitch come out swapped:** ELRS/CRSF normally uses **AETR** channel order. Fix the
> order in the transmitter, then re-run the calibration — do not try to patch it with
> `RC_MAP_*` by hand.

---

## 8. After calibration

1. **Flight Modes tab** — assign the flight-mode switch. Put **Stabilized** on a position you can
   reach by feel; it is your recovery mode.
2. **Assign an arming switch**, then confirm arm and disarm behave. Props still off.
3. **Safety tab** — configure and then *test* the RC-loss and battery failsafes on the bench.
   Switch the transmitter off and confirm the vehicle reacts as configured.

> ⚠️ Props stay off for all of §7 and §8.
