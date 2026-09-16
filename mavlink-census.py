#!/usr/bin/env python3
"""
Diagnostic stand-in for qgc-bridge.py (run INSTEAD of it, never alongside): same TCP->UDP path, plus a
CRC-validated census of everything crossing it.

Answers three questions the old logging could not:
  1. Are the frames we hand QGC actually well-formed? (bad_data count)
  2. What (sysid, compid) do they carry?  QGC silently drops mismatches.
  3. Does QGC talk back, and with what?
"""
import socket, sys, threading, time, collections
from pymavlink.dialects.v20 import common as mavlink2

TCP_ADDR = ("127.0.0.1", 14551)
QGC_ADDR = ("127.0.0.1", 14550)
V1, V2 = 0xFE, 0xFD


def split_frames(buf):
    frames, i, n = [], 0, len(buf)
    while True:
        while i < n and buf[i] not in (V1, V2):
            i += 1
        if i >= n:
            break
        if buf[i] == V1:
            if n - i < 8:
                break
            total = 6 + buf[i + 1] + 2
        else:
            if n - i < 12:
                break
            total = 10 + buf[i + 1] + 2 + (13 if buf[i + 2] & 0x01 else 0)
        if n - i < total:
            break
        frames.append(bytes(buf[i:i + total]))
        i += total
    return frames, buf[i:]


down = collections.Counter()   # (sysid, compid, msgtype) -> count
up = collections.Counter()
bad = {"down": 0, "up": 0}
rc_last = {}
bytes_ = {"down": 0, "up": 0}
qgc_seen = [False]

dmav = mavlink2.MAVLink(None); dmav.robust_parsing = True
umav = mavlink2.MAVLink(None); umav.robust_parsing = True


def tally(mav, frame, counter, key):
    try:
        msgs = mav.parse_buffer(frame) or []
    except Exception:
        bad[key] += 1
        return
    for m in msgs:
        t = m.get_type()
        if t == "BAD_DATA":
            bad[key] += 1
            continue
        counter[(m.get_srcSystem(), m.get_srcComponent(), t)] += 1
        if t == "RC_CHANNELS":
            rc_last.update(dict(
                sysid=m.get_srcSystem(), compid=m.get_srcComponent(),
                chancount=m.chancount, rssi=m.rssi,
                ch=[getattr(m, "chan%d_raw" % i) for i in range(1, 9)]))


def main():
    try:
        tcp = socket.create_connection(TCP_ADDR, timeout=10)
    except OSError as e:
        print("[census] cannot reach board relay %s:%s - %s" % (*TCP_ADDR, e))
        return 1
    tcp.settimeout(1.0)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(1.0)
    print("[census] relay connected; feeding QGC on UDP %s:%s" % QGC_ADDR, flush=True)

    stop = threading.Event()

    def udp_to_tcp():
        while not stop.is_set():
            try:
                data, _ = udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not qgc_seen[0]:
                qgc_seen[0] = True
                print("[census] *** QGC is talking back ***", flush=True)
            tally(umav, data, up, "up")
            bytes_["up"] += len(data)
            try:
                tcp.sendall(data)
            except OSError:
                break
        stop.set()

    threading.Thread(target=udp_to_tcp, daemon=True).start()

    buf = bytearray()
    t0 = last = time.time()
    try:
        while not stop.is_set():
            try:
                chunk = tcp.recv(4096)
            except socket.timeout:
                chunk = b""
            if chunk == b"" and not stop.is_set():
                try:
                    tcp.getpeername()
                except OSError:
                    break
            if chunk:
                buf.extend(chunk)
                frames, rest = split_frames(buf)
                buf = bytearray(rest)
                for f in frames:
                    udp.sendto(f, QGC_ADDR)
                    bytes_["down"] += len(f)
                    tally(dmav, f, down, "down")
            now = time.time()
            if now - last >= 5:
                el = now - t0
                last = now
                print("\n=== t+%.0fs  down %dB  up %dB  bad(down)=%d bad(up)=%d  QGC_talking=%s"
                      % (el, bytes_["down"], bytes_["up"], bad["down"], bad["up"], qgc_seen[0]), flush=True)
                print("  -- vehicle -> QGC (sys,comp,msg  count  Hz) --", flush=True)
                for (s, c, t), n in down.most_common(14):
                    print("     %d/%-3d %-26s %6d  %5.1f Hz" % (s, c, t, n, n / el), flush=True)
                if up:
                    print("  -- QGC -> vehicle --", flush=True)
                    for (s, c, t), n in up.most_common(10):
                        print("     %d/%-3d %-26s %6d" % (s, c, t, n), flush=True)
                if rc_last:
                    print("  -- RC_CHANNELS: sys=%d comp=%d chancount=%d rssi=%d ch1-8=%s"
                          % (rc_last["sysid"], rc_last["compid"], rc_last["chancount"],
                             rc_last["rssi"], rc_last["ch"]), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set(); tcp.close(); udp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
