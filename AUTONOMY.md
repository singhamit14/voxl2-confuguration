# VOXL 2 — Autonomy Roadmap

From a hovering drone to a GPS-denied, obstacle-aware, self-flying one.

Everything below was read off this board on **2026-09-15**. Package versions, config values and
parameter readings are the real ones.

- **Board:** `MDK-F0006-4-V2-C11-T0-M0-X0` — VOXL 2 Flight Deck (M0054), voxl-suite 1.4.0
- **Flight stack:** PX4 1.14.0 on the SLPI DSP
- **Cameras:** stereo front pair, stereo rear pair, tracking, hires — all streaming
- **Companion docs:** `SETUP.md`, `RCSETUP.md`, `build-guide.html`

---

## The stack is already installed and running

This is the part that surprises people. You do not build an autonomy stack on VOXL 2 — you
configure the one that ships with it. All of this is on your board right now:

| Package | Version | Role |
|---|---|---|
| `voxl-vision-hub` | 1.8.17 | The orchestrator — VIO to PX4, obstacle avoidance, offboard modes |
| `voxl-qvio-server` | 1.1.1 | Qualcomm visual-inertial odometry |
| `voxl-open-vins` | 0.4.14 | Alternative open-source VIO |
| `qrb5165-dfs-server` | 0.2.0 | Depth From Stereo |
| `voxl-tflite-server` | 0.3.7 | On-device neural networks |
| `voxl-tag-detector` | 0.0.4 | AprilTag detection |
| `voxl-flow-server` | 0.3.6 | Optical flow |

And the two settings that matter are **already enabled** in
`/etc/modalai/voxl-vision-hub.conf`:

```json
"en_vio": true,     "vio_pipe": "qvio",
"en_voa": true,     "voa_pie_slices": 36,  "voa_pie_max_dist_m": 20,
```

Neural-net models are already on disk in `/usr/bin/dnn/`:

```
fastdepth_float16_quant.tflite                  monocular depth
edgetpu_deeplab_321_os32_float16_quant.tflite   semantic segmentation
lite-model_efficientnet_lite4_uint8_2.tflite    classification
lite-model_movenet_singlepose_lightning...      human pose
coco_labels.txt  cityscapes_labels.txt  imagenet_labels.txt
```

**The missing piece for autonomy is not software. It is that the drone cannot fly yet.**

---

## Phase 0 — The foundation: mechanical quality

> **Read this before Phase 1, not after Phase 2 fails.**

GPS forgives a sloppy airframe. **VIO does not.** Propeller imbalance blurs camera frames and
injects noise into the IMU, and VIO degrades or drops out entirely. The large majority of "VIO
doesn't work" problems on this platform are mechanical, not software.

Before trusting any vision-based mode:

```bash
adb shell 'voxl-inspect-vibration'
```

- Balance every propeller. Replace any that is chipped — do not fly it.
- Soft-mount the flight deck if your frame allows it.
- Keep camera lenses clean and firmly seated; a camera that shifts invalidates the extrinsics.
- Re-check after any crash, however minor.

**VIO also needs something to look at.** Visual texture and light are requirements, not
preferences. A blank white wall, a dark room, or a featureless floor will degrade VIO. That is
inherent to the method, not a fault to debug.

---

## Phase 1 — Make it hover

Conventional multirotor work, nothing VOXL-specific. See `build-guide.html` stages 2–6.

1. ESC (**M0134-6**), motors, props, frame, GPS/mag — order per the build guide
2. Airframe selection and ESC calibration (`voxl-esc calibrate`)
3. Sensor and RC calibration in QGC (`RCSETUP.md`)
4. First hover in **Stabilized**, props checked, outdoors, low
5. PID tuning until it holds attitude cleanly

**Gate:** do not move to Phase 2 until the drone hovers stably in Stabilized and
`voxl-inspect-vibration` is clean. Every later phase inherits this airframe's quality.

---

## Phase 2 — GPS-denied position hold (VIO)

The board's signature capability: holding position indoors with no GPS at all.

The data path is already live — `voxl-qvio-server` publishes to the `qvio` pipe, and
`voxl-vision-hub` forwards it to PX4 as a vision position estimate. What is *not* yet done is
telling PX4's estimator to fuse it.

### Check VIO quality first

```bash
adb shell 'voxl-inspect-qvio'
```

Look for a healthy state and a low feature-count warning rate. Move the board by hand and confirm
the pose tracks. VIO that is unreliable on the bench will not improve in the air.

### Configure the estimator

Current state on this board — vision fusion is **off**, GPS fusion is on:

```
EKF2_EV_CTRL    : 0      (vision fusion disabled)
EKF2_AID_MASK   : 0      (legacy, superseded by EV_CTRL in PX4 1.14)
EKF2_HGT_REF    : 0      (height reference = barometer)
EKF2_GPS_CTRL   : 7      (GPS fusion enabled)
```

**Use ModalAI's helper rather than setting these by hand** — it applies a validated set for this
platform:

```bash
adb shell 'voxl-configure-px4-params'
```

What the key parameters mean, so you can verify the result:

| Parameter | Controls |
|---|---|
| `EKF2_EV_CTRL` | Bitmask: which vision data to fuse — horizontal position, vertical position, velocity, yaw |
| `EKF2_HGT_REF` | Primary height source — set to vision for indoor flight |
| `EKF2_GPS_CTRL` | GPS fusion. Disable for pure indoor VIO so a poor fix cannot fight the estimator |
| `EKF2_EV_DELAY` | Vision measurement latency. Wrong values cause slow position oscillation |

Read any of them back with:

```bash
adb shell 'px4-param show EKF2_EV_CTRL'
```

### Verify in the air

1. Hover in **Stabilized** first and confirm VIO stays locked while flying
2. Switch to **Position** mode at low altitude with plenty of clear space
3. Release the sticks — it should hold position without drift
4. Land and pull the log; check the EKF2 innovations before flying longer

> **Have a way out.** Keep Stabilized on a switch you can reach without looking. If VIO drops in
> Position mode the vehicle can lurch — switching to Stabilized hands control straight back to you.

---

## Phase 3 — Obstacle avoidance (VOA)

Already enabled (`en_voa: true`). Depth data is fused into a 36-slice horizontal "pie" of
obstacle distances and sent to PX4's collision-prevention logic.

Five inputs are configured. On **this** board, two produce data:

| Input pipe | Frame | Status here |
|---|---|---|
| `stereo_front_pc` | `stereo_front_l` | ✅ front stereo pair fitted |
| `stereo_rear_pc` | `stereo_rear_l` | ✅ rear stereo pair fitted |
| `dfs_point_cloud` | `stereo_l` | Depth-From-Stereo server output |
| `tof` | `tof` | ❌ no ToF sensor fitted |
| `rangefinders` | `body` | ❌ no rangefinder fitted |

Shared settings: `max_depth: 8 m`, `min_depth: 0.3 m`, `cell_size: 0.08 m`, FOV 68° × 56°.

Front **and** rear coverage is a real advantage — most builds only see forwards.

```bash
adb shell 'voxl-inspect-points'      # watch the point cloud
adb shell 'voxl-list-pipes | grep -E "voa|pc"'
```

PX4 side: collision prevention activates when `CP_DIST` is set above zero. Start conservative,
test at walking pace toward a large soft obstacle, and increase confidence gradually.

Relevant `voxl-vision-hub.conf` values:

```json
"robot_radius": 0.3,  "collision_sampling_dt": 0.1,  "max_lookahead_distance": 1,
```

Set `robot_radius` to your actual airframe radius including props, not the default.

---

## Phase 4 — Offboard control

Flying paths from code rather than sticks.

### Let onboard software talk to the flight controller

Currently disabled:

```json
"en_localhost_mavlink_udp": false,
```

Set it `true` and restart `voxl-vision-hub`. That exposes MAVLink on localhost so **MAVSDK**,
**MAVROS** or your own code running on the board can command the vehicle.

### Built-in offboard modes

`voxl-vision-hub` ships several, selected by `offboard_mode`:

| Mode | Behaviour |
|---|---|
| `off` | Send no offboard commands |
| `figure_eight` | Fly a figure-8 — **the default, and the right first test** |
| `wps` | Follow waypoints in the local coordinate frame |
| `backtrack` | Replay the last N seconds of position in reverse — a link-loss recovery behaviour |
| `trajectory` | Follow polynomial trajectories received by pipe (in development) |
| `follow_tag` | Follow an AprilTag. ModalAI marks this **R&D only, not recommended** |

`backtrack` is worth knowing about: it watches for RC link loss and commands PX4 into offboard to
retrace its path until the link returns. Configured by `backtrack_seconds: 60`,
`backtrack_rc_chan: 8`, `backtrack_rc_thresh: 1500`.

**Prove the loop with `figure_eight` in a large open space before writing your own code.** It
exercises the whole offboard path with something you can predict.

### Your own code

- **MAVSDK** (Python or C++) on the board, against localhost MAVLink — simplest route
- **ROS 2** in Docker — the `docker-autorun` service already exists on the board
- **Direct MPA pipes** — read `qvio`, `stereo_front`, `voa_pc_out` etc. natively, lowest latency

---

## Phase 5 — Perception

### Neural networks

```bash
adb shell 'voxl-configure-tflite'
adb shell 'voxl-inspect-detections'
```

Models are already on disk (see above). Object detection opens up follow-me behaviour, target
avoidance, and inspection tasks. `fastdepth` gives monocular depth where stereo cannot see.

### AprilTags

```bash
adb shell 'voxl-inspect-tags'
```

Two uses worth the effort:

1. **Precision landing** — tag on the landing pad
2. **Fixed-frame relocalisation** — VIO drifts over time; a detected tag of known position
   corrects absolute position. Enable with `en_tag_fixed_frame: true`. With
   `en_transform_mavlink_pos_setpoints_from_fixed_frame: true`, offboard setpoints from
   MAVSDK/MAVROS can then be given in that fixed frame instead of wherever VIO happened to
   initialise. See ModalAI's
   [AprilTag relocalization guide](https://docs.modalai.com/voxl-vision-px4-apriltag-relocalization/).

---

## Gotchas

**VIO drifts; it does not know where it is.** Position is relative to wherever VIO initialised.
Over a long flight it accumulates error. AprilTag relocalisation or GPS fusion is the correction.

**`en_reset_vio_if_initialized_inverted: true`** — VIO resets if the drone starts upside-down.
Power up level.

**`vio_warmup_s: 3`** — give VIO three seconds before expecting valid pose. Do not arm instantly
after boot.

**Test each phase in isolation.** Do not enable VIO, VOA and offboard in the same flight for the
first time. When something misbehaves you will not know which one caused it.

**Every phase inherits the airframe.** Vibration, loose cameras and unbalanced props will surface
as apparently unrelated software faults in Phases 2–5. When something breaks, check the mechanics
before the config.
