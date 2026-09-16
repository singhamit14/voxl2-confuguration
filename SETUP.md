# VOXL 2 — Setup & Inspection Runbook

> Looking for a specific command? **`adb-shell-commands.md`** is the full ADB/PX4 command
> reference, organised by task.

How to check what software is on the board and what hardware is actually attached to it.

Every command below was run against this board on **2026-09-15** and the outputs shown are the
real ones. Run them from the PC with the board on USB-C; anything prefixed `adb shell` runs on
the board.

- **Board:** `MDK-F0006-4-V2-C11-T0-M0-X0` — VOXL 2 Flight Deck (M0054)
- **SDK:** voxl-suite 1.4.0, system image `1.8.02-M0054-14.1a-perf`
- **Companion docs:** `build-guide.html` / `VOXL2-Drone-Build.pdf` — the drone build itself;
  `RCSETUP.md` — ELRS/CRSF receiver setup and verification;
  `AUTONOMY.md` — VIO, obstacle avoidance and offboard roadmap

---

## 1. Confirm the board is connected

```bash
adb devices -l
```

```
List of devices attached
ae30bd3c   device usb:2-1.3.1 product:qrb5165-qti-distro-ubuntu-fullstack-perf transport_id:1
```

`device` is what you want. Other states and what they mean:

| Shown | Meaning | Fix |
|---|---|---|
| `device` | Connected and authorised | — |
| `unauthorized` | Board hasn't accepted this PC's key | Re-plug; check the board is fully booted |
| `offline` | Enumerated but not responding | `adb kill-server && adb devices` |
| *(empty list)* | Not enumerating | Try another USB-C cable — charge-only cables are the usual culprit |

Open a shell with `adb shell`, or run one-off commands as `adb shell '<cmd>'`.

---

## 2. Check versions

### The one command that summarises everything

```bash
adb shell voxl-version
```

```
system-image: 1.8.02-M0054-14.1a-perf
kernel:       #1 SMP PREEMPT Mon Nov 11 22:08:01 UTC 2024 4.19.125
hw platform:  M0054
mach.var:     1.0.0
voxl-suite:   1.4.0
Repo:  http://voxl-packages.modalai.com/ ./dists/qrb5165/sdk-1.4/binary-arm64/
```

Read it as four separate things, because they version independently:

| Line | What it is |
|---|---|
| `system-image` | The OS layer — kernel, rootfs, and firmware for the DSPs. Only changes when you flash |
| `kernel` | Linux version inside that image |
| `hw platform` | The board model. `M0054` = VOXL 2 |
| `voxl-suite` | The ModalAI software stack on top — the part `apt` manages |

`voxl-version` also prints the full installed package list after those lines. It is long; page it
or grep for what you care about.

> **A warning you can ignore here:** `voxl-version` prints *"repo file has changed since last
> update"*. It means the apt source was edited after the last `apt update`. Harmless on a board
> with no network route.

### Individual package versions

```bash
adb shell 'dpkg -l voxl-px4 voxl-esc voxl-camera-server voxl-vision-hub 2>/dev/null | tail -5'
```

```
ii  voxl-px4            1.14.0-2.0.85   PX4 flight controller
ii  voxl-esc            1.4.8           Tools for ModalAI's VOXL ESC
ii  voxl-camera-server  2.0.8           Camera server
```

Useful when a doc says "requires voxl-esc ≥ x" and you need to know where you stand.

### Board identity / SKU

```bash
adb shell voxl-inspect-sku
```

```
family code:   MDK-F0006 (voxl2-flight-deck)
compute board: 4 (voxl2)
hw version:    2
cam config:    11
MDK-F0006-4-V2-C11-T0-M0-X0
```

`cam config: 11` is the field that tells the camera server which sensors to expect — it is why
six cameras come up without you configuring anything.

---

## 3. What is connected

There are four independent places to look, because the board has four different subsystems that
each track their own hardware.

### 3a. Services — what software is meant to be running

```bash
adb shell voxl-inspect-services
```

```
 Service Name             |  Enabled  |   Running   |  CPU Usage
-------------------------------------------------------------------
 voxl-camera-server       |  Enabled  |   Running   |     1.8%
 voxl-cpu-monitor         |  Enabled  |   Running   |     0.2%
 voxl-imu-server          |  Enabled  |   Running   |     2.3%
 voxl-mavcam-manager      |  Enabled  |   Running   |     0.0%
 voxl-mavlink-server      |  Enabled  |   Running   |     1.5%
 voxl-portal              |  Enabled  |   Running   |     0.0%
 voxl-px4                 |  Enabled  |   Running   |    15.4%
 voxl-qvio-server         |  Enabled  |   Running   |     0.9%
 (… disabled services omitted)
```

**Enabled but Not Running is the state to watch for.** It means the service is supposed to be up
and isn't — usually because a diagnostic tool took its hardware and didn't give it back (see
§5). Fix with `adb shell systemctl restart <service>`.

### 3b. Pipes — what data is actually flowing

Services publish to named MPA pipes. A pipe existing is proof that something real is producing
data, which makes this the fastest "is it working" check on the board.

```bash
adb shell voxl-list-pipes
```

```
cpu_monitor          imu_apps              qvio                  stereo_front
gcs_ip_list          imu_apps_fft          qvio_extended         stereo_rear
hires_large_color    mavlink_attitude      qvio_overlay          tracking
hires_small_color    mavlink_gps_raw_int   voa_pc_out            vvhub_aligned_vio
hires_snapshot       mavlink_onboard       modal_io_bridge       vvhub_body_wrt_local
```

Reading this board: `stereo_front`, `stereo_rear`, `tracking` and the `hires_*` family confirm
all four camera groups are streaming. `qvio*` confirms visual odometry is running on them.
`imu_apps` confirms the IMU. `mavlink_*` confirms the PX4 bridge is up.

### 3c. Cameras

The camera **config** says what the board expects:

```bash
adb shell 'grep -E "\"name\"|\"type\"|\"enabled\"" /etc/modalai/voxl-camera-server.conf | paste - - -'
```

```
"type": "ov7251"   "name": "stereo_front"   "enabled": true
"type": "ov7251"   "name": "tracking"       "enabled": true
"type": "imx214"   "name": "hires"          "enabled": true
"type": "ov7251"   "name": "stereo_rear"    "enabled": true
```

That is six physical sensors: a front stereo pair, a rear stereo pair, one tracking camera, and
one high-res colour camera.

To probe the **hardware** directly, past the config:

```bash
adb shell 'voxl-camera-server -l 2>&1 | grep -E "Cam idx|Number of cameras"'
```

```
Cam idx: 0, Cam slot: 0, Slave Address: 0x00E2, Sensor Id: 0x7750
Cam idx: 1, Cam slot: 1, Slave Address: 0x00E4, Sensor Id: 0x7750
Cam idx: 2, Cam slot: 2, Slave Address: 0x00E2, Sensor Id: 0x7750
Cam idx: 3, Cam slot: 3, Slave Address: 0x0020, Sensor Id: 0x0214
Cam idx: 4, Cam slot: 4, Slave Address: 0x00E2, Sensor Id: 0x7750
Cam idx: 5, Cam slot: 5, Slave Address: 0x00E4, Sensor Id: 0x7750
Number of cameras detected: 6
```

| Sensor Id | Part | Role on this board |
|---|---|---|
| `0x7750` | OV7251 — mono global shutter | Stereo pairs + tracking (5 of them) |
| `0x0214` | IMX214 — colour rolling shutter | `hires` (1) |

> ⚠️ **This command stops the running camera service.** It takes the camera HAL for itself.
> Always follow it with:
> ```bash
> adb shell systemctl restart voxl-camera-server
> ```

For a live view of one camera instead: `adb shell voxl-inspect-cam -c tracking`.

### 3d. IMU

```bash
adb shell 'timeout 5 voxl-inspect-imu'
```

```
latency|gravity| accl_x accl_y accl_z| gyro_x  gyro_y  gyro_z |  Temp |
 2.1ms |  9.60 | -0.37  -0.01   9.59 |  0.011   0.002  -0.002 | 32.07 |
```

**What good looks like:** `gravity` sits at ~9.81 with the board still (9.60 here because the
board isn't perfectly level — the vector magnitude is what matters, and it is stable). Gyro
values near zero when stationary. Temp reasonable. Drifting or wildly-off gravity means the
calibration in `/data/modalai/voxl-imu-server.cal` is bad or missing.

### 3e. Flight-side peripherals, via PX4

PX4 runs on the SLPI DSP and owns the ESC, GPS, RC and power sensing. Ask it directly — each
topic is a separate piece of hardware:

```bash
for t in sensor_accel sensor_gyro sensor_mag sensor_gps input_rc battery_status actuator_outputs; do
  echo "--- $t ---"
  adb shell "timeout 5 px4-listener $t 2>&1 | head -6"
done
```

Three distinct outcomes, and the difference matters:

| Output | Meaning |
|---|---|
| Fields with a recent `timestamp` | Hardware present and publishing |
| `never published` | Driver never started — hardware absent or not configured |
| Topic header, then nothing | Topic exists but no data is arriving — check wiring |

> **Caveat for `input_rc` on CRSF:** `rssi: -1` and `rc_total_frame_count: 0` are *normal* on a
> healthy ELRS link — the `crsf_rc` driver populates neither. Judge the link by
> `timestamp_last_signal`, `link_quality` and `rssi_dbm`. Details in `RCSETUP.md`.

Current state of this board:

| Topic | Result | Reading |
|---|---|---|
| `sensor_accel` | ✅ publishing | `device_id: 2490378 (SPI:1)` — the onboard IMU |
| `sensor_mag` | ❌ `never published` | No magnetometer — arrives with the GPS unit |
| `sensor_gps` | ❌ `never published` | No GPS attached |
| `battery_status` | ✅ publishing | `voltage_v: 24.43`, `current_a: 0.09` — power module live on a 6S rail (see §3h: cell count shipped wrong) |
| `input_rc` | ✅ linked *(as of 15 Sep)* | ELRS receiver bound: `timestamp_last_signal` non-zero, `link_quality: 100`, 16 channels. See `RCSETUP.md`. Before the receiver was fitted this read `timestamp_last_signal: 0` — that field is the real test, not whether the topic exists |

### 3f. ESC

```bash
adb shell 'voxl-esc detect'
```

```
[ERROR] No ESCs detected
```

> ⚠️ **This command stops PX4 *and disables its systemd service*** to claim the UART. It does
> not put it back. Always follow with:
> ```bash
> adb shell 'systemctl enable voxl-px4 && systemctl restart voxl-px4'
> ```

To check an ESC is supported before buying one, list the params shipped with your SDK:

```bash
adb shell 'ls /usr/share/modalai/voxl-esc-params/boards/'
```

```
esc_params_generic_m0049.xml   esc_params_generic_m0129.xml   esc_params_generic_m0134.xml
esc_params_generic_m0117.xml   esc_params_generic_m0134_6.xml
```

### 3g. Calibration on disk

```bash
adb shell 'ls -la /data/modalai/'
```

```
opencv_stereo_front_extrinsics.yml    opencv_stereo_rear_extrinsics.yml
opencv_stereo_front_intrinsics.yml    opencv_stereo_rear_intrinsics.yml
opencv_tracking_intrinsics.yml        voxl-imu-server.cal
sku.txt                               ov/
```

These are **per-unit factory calibration** — measured against this board's physical cameras and
IMU. They cannot be regenerated without calibration targets and a rig. Back them up before any
flash:

```bash
adb pull /data/modalai /home/amit/voxl/backup/modalai
adb pull /data/px4     /home/amit/voxl/backup/px4
```

---

## 3h. Battery / power sensing

Measured 16 Sep 2026. **The board shipped with `BAT1_N_CELLS = 3` on a 6S pack** — the single
most important thing to fix, because every percentage, failsafe threshold and time-remaining
estimate is derived from it.

```bash
adb shell 'px4-param set BAT1_N_CELLS 6; px4-param set BAT_N_CELLS 6; px4-param save'
```

`BAT_N_CELLS` is the deprecated twin but still reports as *used* on this build, so set both and
keep them in agreement.

### QGC's voltage-divider calibration does nothing on this board

QGC's **Vehicle Setup → Power** page shows *Voltage divider* and *Amps per volt* with `Calculate`
buttons. Both are **inert here** — they exist in the parameter table, so QGC displays them, but
no running module reads them:

```
BAT1_A_PER_V [-1,41] : -1.0000     <- leading -1 = used by nothing
BAT1_V_DIV   [-1,51] : -1.0000
VOXLPM_SHUNT_BAT [788,2093] : 0.0006   <- this is what actually scales current
```

Power is read over I2C by ModalAI's INA231-based monitor, not an analog ADC, so there is no
divider to calibrate. Voltage comes straight from the chip's bus-voltage register and needs no
calibration: it read **24.31 V** against **24.43 V** on a multimeter, a 0.5 % error.

**To trim current** (only meaningful under a real load — idle draw is ~0.2 A and proves nothing),
scale the shunt rather than touching `A_PER_V`:

```
new_shunt = VOXLPM_SHUNT_BAT x (reported_current / true_current)
```

### What is worth setting in QGC

| Field on the Power page | Parameter | Note |
|---|---|---|
| Number of cells | `BAT1_N_CELLS` | **6** for this pack |
| Full voltage per cell | `BAT1_V_CHARGED` | 4.15 shipped; 4.2 if you charge to full |
| Empty voltage per cell | `BAT1_V_EMPTY` | 3.50 |
| Battery capacity | `BAT1_CAPACITY` | **9000 mAh** — the actual pack. Shipped as 4700, a placeholder |
| *Voltage divider / Amps per volt* | — | **skip, inert** |

`BAT_AVRG_CURRENT` (15 A default) only feeds the time-remaining estimate; set it to the airframe's
real average draw once it flies. `remaining` is dominated by coulomb counting once `BAT1_CAPACITY`
is set, so a wrong capacity skews the percentage more than the voltage curve does — at the
shipped 4700 on a 9000 mAh pack, percentage drained near twice as fast as reality and the low /
critical failsafes would have fired at roughly half the true discharge:

```bash
adb shell 'px4-param set BAT1_CAPACITY 9000; px4-param save'
```

---

## 4. One-shot audit

Everything above in a single pass. Read-only — it starts nothing and stops nothing, so it is
safe to run any time.

```bash
cat > /home/amit/voxl/voxl-audit.sh <<'EOF'
#!/bin/bash
# Read-only VOXL 2 audit. Safe to run any time.
echo "=============== VERSIONS ==============="
adb shell 'voxl-version 2>&1 | head -12'
echo "=============== IDENTITY ==============="
adb shell 'voxl-inspect-sku 2>&1 | head -6'
echo "=============== SERVICES ==============="
adb shell 'voxl-inspect-services 2>&1 | grep -E "Service|Enabled.*Running|Enabled.*Not Running"'
echo "=============== PIPES =================="
adb shell 'voxl-list-pipes 2>&1 | tr "\n" " "'; echo
echo "=============== CAMERAS (config) ======="
adb shell 'grep -E "\"name\"|\"type\"" /etc/modalai/voxl-camera-server.conf | paste - -'
echo "=============== PX4 TOPICS ============="
for t in sensor_accel sensor_gyro sensor_mag sensor_gps battery_status actuator_outputs; do
  printf "%-18s " "$t"
  adb shell "timeout 4 px4-listener $t 2>&1 | grep -qi 'never published' && echo 'NEVER PUBLISHED' || echo 'publishing'"
done
# input_rc publishes whether or not a receiver is attached -- the field that
# tells the truth is timestamp_last_signal, so check that rather than the topic.
printf "%-18s " "input_rc"
adb shell "timeout 4 px4-listener input_rc 2>&1 | awk '/timestamp_last_signal/{print \$2}'" \
  | tr -d '\r' | awk '{ if ($1=="" ) print "NEVER PUBLISHED";
                         else if ($1==0) print "no RC signal (driver up, nothing bound)";
                         else print "RC signal present" }' 
echo "=============== CALIBRATION ============"
adb shell 'ls /data/modalai/*.yml /data/modalai/*.cal 2>/dev/null'
EOF
chmod +x /home/amit/voxl/voxl-audit.sh
```

Run it with `/home/amit/voxl/voxl-audit.sh`.

---

## 5. Gotchas

Things that will confuse you if you don't know them in advance.

**Two diagnostic tools leave the board in a worse state than they found it.** Both claim hardware
from a running service and neither restores it:

| Tool | What it breaks | Repair |
|---|---|---|
| `voxl-esc detect` / `calibrate` | Stops **and disables** `voxl-px4` | `systemctl enable voxl-px4 && systemctl restart voxl-px4` |
| `voxl-camera-server -l` | Stops `voxl-camera-server` | `systemctl restart voxl-camera-server` |

After any debugging session, run `voxl-inspect-services` and look for **Enabled + Not Running**.

**`input_rc` existing does not mean RC works.** The driver publishes the topic whether or not a
receiver is attached. The field that tells the truth is `timestamp_last_signal` — `0` means
nothing has ever been received.

**The board has no network route.** `ping` from the board fails with `unknown host`, so `apt`
will not work on-device. There are 72 offline `.deb` packages in
`/data/voxl-suite-offline-packages` for installs, and everything else comes over ADB from the PC.

**PX4 is not a normal Linux process.** It runs on the SLPI DSP. `px4-listener` and `qshell` talk
to it across that boundary, so a couple of seconds of latency on first call is normal, and
`WARNING: Received N bytes of data from SLPI while SLPI uart not in use` during ESC work is
noise, not an error.

**System image and voxl-suite are different things.** Upgrading the SDK does not necessarily
change the system image and vice versa. When a doc gives a version requirement, check which of
the two it means.
