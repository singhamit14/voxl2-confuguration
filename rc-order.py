#!/usr/bin/env python3
"""
Establish the raw-channel <-> physical-stick mapping without trusting RC_MAP_*.

The operator moves one stick at a time in a stated order; this records raw
input_rc and reports which channel was active during each burst, ordered in
time. That is ground truth, independent of whatever RC_MAP_* currently says.
"""
import re
import subprocess
import sys

N = int(sys.argv[1]) if len(sys.argv) > 1 else 700
ORDER = ["roll (right stick L-R)", "pitch (right stick U-D)",
         "throttle (left stick U-D)", "yaw (left stick L-R)"]

loop = ('for i in $(seq %d); do px4-listener input_rc 1 2>/dev/null | '
        'sed -n "s/^ *values: //p"; done' % N)
raw = subprocess.run(["adb", "shell", loop], capture_output=True,
                     text=True, timeout=900).stdout
raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)

rows = []
for line in raw.splitlines():
    line = line.strip()
    if line.startswith("["):
        try:
            rows.append([int(x) for x in line.strip("[]").split(",")])
        except ValueError:
            pass
print("[rc-order] %d samples" % len(rows))
if len(rows) < 40:
    sys.exit("too few samples")

nch = min(len(r) for r in rows)
med = []
for c in range(nch):
    col = sorted(r[c] for r in rows)
    med.append(col[len(col) // 2])

active = {}
for c in range(nch):
    idx = [i for i, r in enumerate(rows) if abs(r[c] - med[c]) > 60]
    if len(idx) < 8:
        continue
    span = max(r[c] for r in rows) - min(r[c] for r in rows)
    if span < 200:
        continue
    active[c + 1] = (sum(idx) / len(idx), len(idx), span,
                     min(r[c] for r in rows), max(r[c] for r in rows))

if not active:
    sys.exit("no channel moved - was the transmitter on?")

print("\n  channel   burst centre   samples   span   min   max")
for ch, (ctr, n, span, lo, hi) in sorted(active.items(), key=lambda kv: kv[1][0]):
    print("    ch%-2d       %6.0f       %5d   %4d  %4d  %4d"
          % (ch, ctr, n, span, lo, hi))

seq = [ch for ch, _ in sorted(active.items(), key=lambda kv: kv[1][0])]
print("\n  Channels in the order they were moved: %s" % seq)
print("\n  => inferred physical mapping")
for name, ch in zip(ORDER, seq):
    print("       %-28s = ch%d" % (name, ch))
if len(seq) != 4:
    print("\n  WARNING: expected exactly 4 moving channels, saw %d." % len(seq))
    print("  Re-run and move only one stick at a time, pausing between.")
else:
    print("\n  Suggested params:")
    for p, ch in zip(["RC_MAP_ROLL", "RC_MAP_PITCH", "RC_MAP_THROTTLE",
                      "RC_MAP_YAW"], seq):
        print("       %-16s %d" % (p, ch))
