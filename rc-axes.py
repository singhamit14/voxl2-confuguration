#!/usr/bin/env python3
"""
Verify which raw RC channel actually drives each PX4 axis.

Samples input_rc and manual_control_setpoint together, then correlates every
channel against every axis. Needs no timed stick sequence - just move all four
sticks around while it runs. Catches AETR/TAER swaps and reversed channels.

    ./rc-axes.py [samples]
"""
import re
import subprocess
import sys

SAMPLES = int(sys.argv[1]) if len(sys.argv) > 1 else 260
AXES = ("roll", "pitch", "yaw", "throttle")
# What RC_MAP_* says should drive each axis; filled in from the board.
MAPPARAM = {"roll": "RC_MAP_ROLL", "pitch": "RC_MAP_PITCH",
            "yaw": "RC_MAP_YAW", "throttle": "RC_MAP_THROTTLE"}


def sh(cmd):
    return subprocess.run(["adb", "shell", cmd], capture_output=True,
                          text=True, timeout=600).stdout


def declared_map():
    out = sh("; ".join("px4-param show %s" % p for p in MAPPARAM.values()))
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    got = {}
    for ax, p in MAPPARAM.items():
        m = re.search(re.escape(p) + r"\s*\[[^\]]*\]\s*:\s*(\d+)", out)
        got[ax] = int(m.group(1)) if m else None
    return got


def capture(n):
    loop = (
        'for i in $(seq %d); do '
        'echo S; '
        'px4-listener input_rc 1 2>/dev/null | sed -n "s/^ *values: //p"; '
        'px4-listener manual_control_setpoint 1 2>/dev/null | '
        'sed -n "s/^ *\\(roll\\|pitch\\|yaw\\|throttle\\): /\\1=/p"; '
        'done' % n)
    return sh(loop)


def parse(raw):
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    rows = []
    cur = {}
    for line in raw.splitlines():
        line = line.strip()
        if line == "S":
            if "ch" in cur and len(cur) >= 2:
                rows.append(cur)
            cur = {}
        elif line.startswith("["):
            try:
                cur["ch"] = [int(x) for x in line.strip("[]").split(",")]
            except ValueError:
                pass
        elif "=" in line:
            k, v = line.split("=", 1)
            if k in AXES:
                try:
                    cur[k] = float(v)
                except ValueError:
                    pass
    if "ch" in cur and len(cur) >= 2:
        rows.append(cur)
    return rows


def pearson(xs, ys):
    n = len(xs)
    if n < 8:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 1e-9 or syy <= 1e-9:
        return 0.0
    return sxy / (sxx * syy) ** 0.5


def main():
    print("[rc-axes] reading RC_MAP_* ...", flush=True)
    dmap = declared_map()
    print("[rc-axes] declared: " + ", ".join(
        "%s=ch%s" % (a, dmap[a]) for a in AXES), flush=True)
    print("[rc-axes] sampling %d points - MOVE ALL FOUR STICKS through full "
          "range now" % SAMPLES, flush=True)
    rows = parse(capture(SAMPLES))
    print("[rc-axes] got %d usable samples\n" % len(rows), flush=True)
    if len(rows) < 20:
        print("  too few samples to correlate")
        return 1

    nch = min(len(r["ch"]) for r in rows)
    ok = True
    for ax in AXES:
        data = [(r["ch"], r[ax]) for r in rows if ax in r]
        if len(data) < 20:
            print("  %-8s no data" % ax)
            ok = False
            continue
        ys = [d[1] for d in data]
        scores = []
        for c in range(nch):
            xs = [d[0][c] for d in data]
            scores.append((abs(pearson(xs, ys)), pearson(xs, ys), c + 1))
        scores.sort(reverse=True)
        strength, signed, ch = scores[0]
        runner = scores[1] if len(scores) > 1 else (0, 0, 0)
        want = dmap.get(ax)
        sign = "normal" if signed > 0 else "REVERSED"
        # pitch is inverted by PX4 convention: stick forward = nose down
        if ax == "pitch":
            sign += " (PX4 inverts pitch; negative here is expected)"
        flag = ""
        if want is not None and ch != want:
            flag = "   <-- MISMATCH, RC_MAP says ch%d" % want
            ok = False
        elif strength < 0.9:
            flag = "   <-- WEAK correlation, moved enough?"
            ok = False
        print("  %-8s driven by ch%-2d  r=%+.3f  (%s)%s"
              % (ax, ch, signed, sign, flag))
        if runner[0] > 0.6:
            print("           note: ch%d also correlates (|r|=%.2f)"
                  % (runner[2], runner[0]))
    print()
    if ok:
        print("  VERDICT: all four axes track their mapped channels. No AETR/TAER swap.")
    else:
        print("  VERDICT: see flags above - fix channel ORDER in the transmitter,")
        print("           not with RC_MAP_* by hand, then re-calibrate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
