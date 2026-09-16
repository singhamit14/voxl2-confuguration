# VOXL 2 — ADB Shell Command Reference

Every command here was **run on this board** and its output checked: M0054, system-image `1.8.02-M0054-14.1a-perf`,
voxl-suite `1.4.0`, PX4 1.14.0, serial `ae30bd3c`.

Commands run **on the PC** unless a row says otherwise. `adb shell '<cmd>'` runs `<cmd>` on the
board and returns; plain `adb shell` drops you into an interactive shell on the board.

> **Quote your commands.** `adb shell 'px4-param show "RC_MAP_*"'` — without the inner quotes your
> PC's shell expands the `*` against the PC's filesystem, not the board's.

---

## 0. The one thing that will waste your time

PX4 tools emit **ANSI colour escapes** that wreck `grep` and `awk`. Strip them:

```bash
adb shell 'px4-param show BAT1_CAPACITY' | sed 's/\x1b\[[0-9;]*m//g'
```

Keep that `sed` in your muscle memory — every `px4-param` and `px4-listener` pipeline needs it.

---

## 1. Connection and files

| Command | Use |
|---|---|
| `adb devices` | Is the board attached? Must print a serial followed by `device`. |
| `adb shell` | Interactive shell on the board. `exit` to leave. |
| `adb shell '<cmd>'` | Run one command and return. |
| `adb push <local> <remote>` | Copy PC → board, e.g. `adb push x.py /data/x.py`. |
| `adb pull <remote> <local>` | Copy board → PC. Used to back up `/data/modalai`. |
| `adb forward tcp:14551 tcp:14650` | Tunnel a **TCP** port PC → board. The only way to reach a board socket over USB. |
| `adb forward --list` | Show active forwards. |
| `adb forward --remove-all` | Clear them. **Forwards do not survive a replug or reboot.** |
| `adb reboot` | Reboot the board. Also restores stock service configuration. |

`/data` and `/etc` persist across reboots; host-side forwards do not.

---

## 2. Identity and versions

| Command | Use |
|---|---|
| `adb shell 'voxl-version'` | System image, kernel, hw platform, voxl-suite version, package repo. Start here. |
| `adb shell 'voxl-platform'` | Just the board model — prints `M0054`. |
| `adb shell 'cat /data/modalai/sku.txt'` | Factory SKU of this exact unit. |
| `adb shell 'voxl-inspect-sku'` | SKU as the software understands it. |
| `adb shell 'px4-ver all'` | PX4 firmware version. |
| `adb shell 'dpkg -l \| grep voxl'` | Every installed voxl package and version. |
| `adb shell 'uptime'` | Confirm whether the board was just power-cycled. |

---

## 3. Services

`voxl-*` features are systemd services. **Check state before concluding anything is broken.**

| Command | Use |
|---|---|
| `adb shell 'voxl-inspect-services'` | The dashboard: every service, Enabled/Disabled, Running/Not Running, CPU. |
| `adb shell 'systemctl is-active <svc>'` | Running right now? |
| `adb shell 'systemctl is-enabled <svc>'` | Starts at boot? |
| `adb shell 'systemctl start <svc>'` | Start now. |
| `adb shell 'systemctl stop <svc>'` | Stop now. |
| `adb shell 'systemctl restart <svc>'` | Bounce it. |
| `adb shell 'journalctl -u <svc> -n 40 --no-pager'` | Last 40 log lines — the first thing to read when a service won't start. |
| `adb shell 'journalctl -k -n 100'` | Kernel log, e.g. for USB/Wi-Fi dongle detection. |

**Read `voxl-inspect-services` like this:** anything **Enabled + Not Running** is a service that
was supposed to come up and did not — *except* `voxl-mavlink-server` while the bench MAVLink relay
is running, where it is expected (see §8).

Services that matter here: `voxl-px4`, `voxl-imu-server`, `voxl-camera-server`, `voxl-vision-hub`,
`voxl-qvio-server`, `voxl-mavlink-server`.

---

## 4. PX4 parameters

This is where nearly all configuration lives.

| Command | Use |
|---|---|
| `adb shell 'px4-param show <NAME>'` | One parameter. |
| `adb shell 'px4-param show "BAT1_*"'` | Wildcard — trailing `*` only. |
| `adb shell 'px4-param show'` | All **used** parameters. |
| `adb shell 'px4-param show -a'` | All parameters, including ones nothing reads. |
| `adb shell 'px4-param show -c'` | **Only changed** params — the fastest way to see how this board differs from stock. |
| `adb shell 'px4-param show -q <NAME>'` | Value only, no decoration. Good for scripts. |
| `adb shell 'px4-param set <NAME> <VALUE>'` | Change a value. |
| `adb shell 'px4-param save'` | **Persist to storage. Do this after every `set`.** |
| `adb shell 'px4-param reset <NAME>'` | Back to firmware default. |
| `adb shell 'px4-param reset_all'` | Everything to default. Wipes your calibration — see §10. |
| `adb shell 'px4-param compare <NAME> <VAL>'` | Exit status 0 if equal. For scripts. |
| `adb shell 'px4-param find <NAME>'` | Parameter index. |
| `adb shell 'px4-param status'` | Parameter subsystem status. |

### Reading the output

```
Symbols: x = used, + = saved, * = unsaved
x + BAT1_CAPACITY [1,42] : 9000.0000
 820/2162 parameters used.
```

| Symbol | Meaning |
|---|---|
| `x` | Some running module actually reads this parameter |
| `+` | Saved to storage — survives reboot |
| `*` | Changed but **not yet saved** — run `px4-param save` |
| *(no `x`)* | **Nothing reads it.** Setting it does nothing |
| `[1,42]` | `[used_index, param_index]`; a **used_index of `-1` means unused** |

That last row is the trap. `BAT1_V_DIV [-1,51]` is present, settable, shown by QGC — and read by
nothing on this board. Always check for `-1` before trusting a parameter.

### Set and verify in one go

```bash
adb shell 'px4-param set BAT1_CAPACITY 9000; px4-param save; px4-param show BAT1_CAPACITY' \
  | sed 's/\x1b\[[0-9;]*m//g'
```

---

## 5. Live data — uORB topics

| Command | Use |
|---|---|
| `adb shell 'px4-listener <topic>'` | Print one sample of a topic. |
| `adb shell 'px4-listener <topic> 5'` | Print 5 consecutive samples. |
| `adb shell 'px4-uorb status'` | All topics, subscriber counts and sizes. |
| `adb shell 'px4-listener vehicle_status'` | Arming state, nav state, failsafe. `arming_state: 1` = disarmed/standby, `2` = armed. |

> **`px4-commander status` and `px4-top` print nothing useful here.** Commander and the work queues
> run on the SLPI DSP, so the apps-side shell stubs report `not running` or stay silent. Read
> `vehicle_status` via `px4-listener` instead, and use `voxl-cpu-monitor` / `voxl-inspect-cpu` for
> load. Same reason `voxl-inspect-state` is silent — its state-estimator service is disabled.


Useful topics: `input_rc`, `manual_control_setpoint`, `battery_status`, `sensor_accel`,
`sensor_gyro`, `sensor_mag`, `sensor_gps`, `vehicle_attitude`, `vehicle_local_position`,
`actuator_outputs`, `esc_status`.

> **PX4 runs split across the apps processor and the SLPI DSP**, and the muorb bridge does not
> forward every topic. `rc_channels` and `manual_control_input` read **empty** here — that is the
> bridge, not a fault. Use `input_rc` and `manual_control_setpoint` instead.

A topic can publish even with no hardware attached. The field that tells the truth is
`timestamp_last_signal`, not the mere existence of the topic.

Sample a topic repeatedly (~40 Hz on this board):

```bash
adb shell 'for i in $(seq 200); do px4-listener input_rc 1 | sed -n "s/^ *values: //p"; done'
```

---

## 6. RC / radio

| Command | Use |
|---|---|
| `adb shell 'px4-listener input_rc'` | Raw channel values, `link_quality`, `channel_count`. The ground truth for the RC link. |
| `adb shell 'px4-listener manual_control_setpoint'` | Post-mapping axes. At rest: roll/pitch/yaw ≈ 0, throttle ≈ −1. |
| `adb shell 'px4-param show "RC_MAP_*"'` | Which channel drives which function. |
| `adb shell 'px4-param show "RC1_*"'` | Endpoints for channel 1 (`_MIN` `_MAX` `_TRIM` `_REV` `_DZ`). |
| `adb shell 'voxl-elrs'` | ELRS receiver utility. |
| `adb shell 'voxl-bind-elrs'` | Put an ELRS receiver into bind mode. |

**This board's verified mapping (AETR):** ch1 roll, ch2 pitch, ch3 throttle, ch4 yaw.
Switches: ARM=5, FLTMODE=6, RETURN=7, KILL=8.

```bash
adb shell 'px4-param set RC_MAP_ROLL 1; px4-param set RC_MAP_PITCH 2; \
           px4-param set RC_MAP_YAW 4; px4-param set RC_MAP_THROTTLE 3; px4-param save'
```

> **Verify the map after every QGC radio calibration.** On this CRSF link the wizard has mapped
> roll and pitch onto *switch* channels. Check `RC_MAP_*` and confirm
> `manual_control_setpoint` reads 0/0/0 at rest. `./rc-axes.py` and `./rc-order.py` automate this.

Normal for CRSF, not faults: `rssi: -1` or `rssi=255`, and `rc_total_frame_count: 0`.

---

## 7. Battery and power

| Command | Use |
|---|---|
| `adb shell 'px4-listener battery_status'` | Voltage, current, cell count, remaining. |
| `adb shell 'px4-param show "BAT1_*"'` | Battery 1 configuration. |
| `adb shell 'voxl-inspect-battery'` | Live monitor — **runs until Ctrl-C**. |

This board's correct values:

```bash
adb shell 'px4-param set BAT1_N_CELLS 6; px4-param set BAT_N_CELLS 6; \
           px4-param set BAT1_CAPACITY 9000; px4-param save'
```

| Parameter | Value | Note |
|---|---|---|
| `BAT1_N_CELLS` | 6 | **Shipped as 3** on a 6S pack |
| `BAT_N_CELLS` | 6 | Deprecated twin, still reports as *used* — keep it in agreement |
| `BAT1_CAPACITY` | 9000 | mAh. Shipped as 4700 |
| `BAT1_V_CHARGED` | 4.15 | Per cell |
| `BAT1_V_EMPTY` | 3.50 | Per cell |
| `VOXLPM_SHUNT_BAT` | 0.0006 | Ω — **this** scales current |
| `BAT1_V_DIV`, `BAT1_A_PER_V` | −1 | **Unused. Setting them does nothing.** |

Power is read over **I2C from ModalAI's INA231 monitor**, not an analog ADC, so there is no
voltage divider to calibrate and QGC's `Calculate` buttons are inert. Voltage needs no calibration
(24.27 V measured vs 24.43 V on a multimeter). To trim current, scale the shunt under real load:

```
new_shunt = VOXLPM_SHUNT_BAT × (reported_current / true_current)
```

PX4 reports the **minimum** of the voltage-based and coulomb-counted estimates, so an undersized
`BAT1_CAPACITY` makes the gauge pessimistic — failsafes fire early and you lose endurance.
Oversizing is the dangerous direction.

---

## 8. QGroundControl over the USB cable

VOXL 2 has no onboard Wi-Fi and USB-C carries ADB only, so QGC needs a relay. `./voxl-qgc.sh up`
does all of this; the manual equivalent:

```bash
adb shell 'systemctl start mavlink-tcp-relay'    # deliberately stops voxl-mavlink-server
adb forward tcp:14551 tcp:14650
./qgc-bridge.py                                  # EXACTLY ONE bridge
```

Revert:

```bash
adb shell 'systemctl stop mavlink-tcp-relay && systemctl start voxl-mavlink-server'
adb forward --remove-all
```

| Command | Use |
|---|---|
| `adb shell 'voxl-inspect-mavlink'` | Watch MAVLink traffic on the board. |
| `adb shell 'voxl-inspect-gcs-ip'` | Which GCS address the board is talking to. |
| `adb shell 'voxl-my-ip'` | Board's own addresses. |

**`voxl-mavlink-server` showing Enabled + Not Running while the relay runs is correct** — the
relay unit declares `Conflicts=`. Neither change persists across a reboot, so a power cycle
restores stock configuration by itself.

---

## 9. Sensors, cameras, pipes

| Command | Use |
|---|---|
| `adb shell 'voxl-inspect-imu'` | Live IMU. |
| `adb shell 'voxl-inspect-vibration'` | Vibration levels — check before tuning. |
| `adb shell 'voxl-inspect-cam -a'` | Which cameras are publishing. |
| `adb shell 'voxl-list-pipes'` | Every MPA pipe on the board. |
| `adb shell 'voxl-inspect-services'` | Confirm the camera/IMU servers are up. |
| `adb shell 'voxl-inspect-qvio'` | VIO state. |
| `adb shell 'voxl-inspect-gps'` | GPS. |
| `adb shell 'voxl-inspect-pose'` | Fused pose. |
| `adb shell 'voxl-inspect-cpu'` | CPU load and temperature. |
| `adb shell 'voxl-check-calibration'` | Validate on-disk camera calibration. |
| `adb shell 'voxl-calibrate-imu'` | IMU calibration routine. |

Most `voxl-inspect-*` tools are **live monitors** — they run until Ctrl-C. Wrap them in `timeout`
when scripting: `timeout 5 adb shell 'voxl-inspect-imu'`.

---

## 10. Protect the factory calibration

`/data/modalai` holds per-unit calibration that **cannot be regenerated without a calibration
rig** — stereo front/rear intrinsics and extrinsics, tracking intrinsics, `voxl-imu-server.cal`.

```bash
adb pull /data/modalai ./backup/modalai
adb pull /data/px4 ./backup/px4
```

Back this up before flashing anything, and do not `px4-param reset_all` casually.

---

## 11. Commands that leave the board broken

| Command | What it does |
|---|---|
| `voxl-esc detect` | Stops **and disables** `voxl-px4`. Re-enable with `systemctl enable --now voxl-px4`. |
| `voxl-camera-server -l` | Stops the camera service. Restart with `systemctl restart voxl-camera-server`. |
| `px4-param reset_all` | Wipes calibration and configuration. |
| `voxl-wifi` | Happily writes a valid SoftAP config for a radio that does not exist. Costs nothing, achieves nothing. |

**After any debugging session, run `voxl-inspect-services` and look for Enabled + Not Running.**

---

## 12. Copy-paste recipes

Full health check:

```bash
adb shell 'voxl-version; echo; voxl-inspect-services' | sed 's/\x1b\[[0-9;]*m//g'
```

Everything this board has changed from stock PX4 defaults:

```bash
adb shell 'px4-param show -c' | sed 's/\x1b\[[0-9;]*m//g'
```

Is the RC link alive and are the axes sane?

```bash
adb shell 'px4-listener input_rc; px4-listener manual_control_setpoint' \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'values|link_quality|roll|pitch|yaw|throttle|valid'
```

Battery at a glance:

```bash
adb shell 'px4-listener battery_status 1' | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E 'voltage_v:|current_a:|remaining:|cell_count|capacity:'
```

---

## See also

| File | Contents |
|---|---|
| `SETUP.md` | Version checks, what hardware is attached, §3h battery/power |
| `RCSETUP.md` | ELRS/CRSF, QGC connection (§6b), RC calibration (§7) |
| `AUTONOMY.md` | Roadmap: hover → VIO → avoidance → offboard → perception |
| `voxl-qgc.sh` | `up`/`down`/`status` for the bench QGC link |
| `voxl-audit.sh` | Read-only one-shot audit |
| `rc-axes.py`, `rc-order.py`, `rc-watch.py` | RC verification tools |
