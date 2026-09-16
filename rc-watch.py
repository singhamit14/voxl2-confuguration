#!/usr/bin/env python3
"""
Watch RC_CHANNELS on the exact stream QGC consumes and report per-channel
min/max spread. Proves whether the values QGC receives actually MOVE.
"""
import socket, sys, time, collections
from pymavlink.dialects.v20 import common as mavlink2

TCP_ADDR = ("127.0.0.1", 14551)
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
V1, V2 = 0xFE, 0xFD


def split_frames(buf):
    frames, i, n = [], 0, len(buf)
    while True:
        while i < n and buf[i] not in (V1, V2):
            i += 1
        if i >= n:
            break
        if buf[i] == V1:
            if n - i < 8: break
            total = 6 + buf[i + 1] + 2
        else:
            if n - i < 12: break
            total = 10 + buf[i + 1] + 2 + (13 if buf[i + 2] & 0x01 else 0)
        if n - i < total: break
        frames.append(bytes(buf[i:i + total]))
        i += total
    return frames, buf[i:]


def main():
    tcp = socket.create_connection(TCP_ADDR, timeout=10)
    tcp.settimeout(1.0)
    mav = mavlink2.MAVLink(None); mav.robust_parsing = True
    lo = collections.defaultdict(lambda: 10**9)
    hi = collections.defaultdict(lambda: -10**9)
    n = 0
    buf = bytearray()
    t0 = last = time.time()
    print("[rcwatch] watching %.0fs - MOVE ALL STICKS AND FLIP SWITCHES NOW" % DURATION, flush=True)
    while time.time() - t0 < DURATION:
        try:
            chunk = tcp.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf.extend(chunk)
        frames, rest = split_frames(buf)
        buf = bytearray(rest)
        for f in frames:
            try:
                msgs = mav.parse_buffer(f) or []
            except Exception:
                continue
            for m in msgs:
                if m.get_type() != "RC_CHANNELS":
                    continue
                n += 1
                for c in range(1, 17):
                    v = getattr(m, "chan%d_raw" % c)
                    if v == 65535:
                        continue
                    lo[c] = min(lo[c], v); hi[c] = max(hi[c], v)
        now = time.time()
        if now - last >= 5:
            last = now
            moved = [c for c in sorted(hi) if hi[c] - lo[c] > 2]
            print("  t+%2.0fs  %4d msgs   channels that have moved: %s"
                  % (now - t0, n, moved if moved else "NONE YET"), flush=True)
    tcp.close()

    print("\n==== RESULT after %d RC_CHANNELS messages ====" % n, flush=True)
    if n == 0:
        print("  NO RC_CHANNELS RECEIVED AT ALL.")
        return 1
    moved = []
    for c in sorted(hi):
        span = hi[c] - lo[c]
        tag = "  <-- MOVED" if span > 2 else ""
        if span > 2:
            moved.append(c)
        print("  ch%-2d  min=%4d  max=%4d  span=%4d%s" % (c, lo[c], hi[c], span, tag))
    print()
    if moved:
        print("  VERDICT: %d channel(s) moved: %s" % (len(moved), moved))
        print("  The stream QGC receives DOES carry live stick motion.")
        print("  => the fault is inside QGC, not the RC link or the relay.")
    else:
        print("  VERDICT: NOT ONE CHANNEL CHANGED.")
        print("  PX4 is emitting a frozen snapshot. The RC link is NOT delivering")
        print("  live stick data, despite link_quality=100. Fault is upstream of QGC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
