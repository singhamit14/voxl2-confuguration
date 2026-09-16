#!/usr/bin/env python3
"""
PC-side half of the VOXL 2 QGC bridge.

Removes the need to configure a TCP comm link by hand. QGroundControl auto-connects
to any MAVLink arriving on UDP 14550, so this feeds it there:

    board relay --adb forward--> PC TCP 14551 --[this]--> UDP 14550 (QGC auto-connects)

Run the board side first:
    adb shell 'systemctl start mavlink-tcp-relay'
    adb forward tcp:14551 tcp:14650
    ./qgc-bridge.py

Then just open QGroundControl. No comm link setup needed.

RUN EXACTLY ONE BRIDGE. The board relay hands each PX4 datagram to a single
reader, so two bridges connected at once leave one of them deaf and QGC sees a
partial stream - which looks exactly like "telemetry works but the Radio page
is frozen". Check with:  pgrep -af 'qgc-bridge|mavlink-census'

BENCH ONLY - revert to voxl-mavlink-server before flying.
"""

import socket
import sys
import threading
import time

TCP_ADDR = ("127.0.0.1", 14551)    # adb-forwarded port to the board relay
QGC_ADDR = ("127.0.0.1", 14550)    # QGC's default auto-connect UDP listener

V1_MAGIC = 0xFE
V2_MAGIC = 0xFD


def split_frames(buf):
    """Pull complete MAVLink frames from a byte stream. Returns (frames, remainder)."""
    frames = []
    i, n = 0, len(buf)
    while True:
        while i < n and buf[i] not in (V1_MAGIC, V2_MAGIC):
            i += 1
        if i >= n:
            break
        if buf[i] == V1_MAGIC:
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


def main():
    try:
        tcp = socket.create_connection(TCP_ADDR, timeout=10)
    except OSError as e:
        print("[bridge] cannot reach the board relay on {}:{} - {}".format(
            TCP_ADDR[0], TCP_ADDR[1], e))
        print("[bridge] check:  adb forward tcp:14551 tcp:14650")
        print("[bridge]         adb shell 'systemctl is-active mavlink-tcp-relay'")
        return 1
    tcp.settimeout(1.0)
    print("[bridge] connected to board relay at {}:{}".format(*TCP_ADDR))

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(1.0)
    print("[bridge] feeding QGC on UDP {}:{} - just open QGroundControl".format(*QGC_ADDR))

    stop = threading.Event()
    stats = {"down": 0, "up": 0}
    qgc_seen = [False]

    def udp_to_tcp():
        """QGC -> board."""
        while not stop.is_set():
            try:
                data, _ = udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not qgc_seen[0]:
                qgc_seen[0] = True
                print("[bridge] QGC is talking back - connected")
            try:
                tcp.sendall(data)
                stats["up"] += len(data)
            except OSError:
                break
        stop.set()

    threading.Thread(target=udp_to_tcp, daemon=True).start()

    buf = bytearray()
    last = time.time()
    try:
        while not stop.is_set():
            try:
                chunk = tcp.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                print("[bridge] board closed the connection")
                break
            buf.extend(chunk)
            frames, rest = split_frames(buf)
            buf = bytearray(rest)
            for f in frames:
                udp.sendto(f, QGC_ADDR)      # one datagram per frame
                stats["down"] += len(f)
            if time.time() - last >= 5:
                last = time.time()
                print("[bridge] {} B to QGC, {} B to vehicle{}".format(
                    stats["down"], stats["up"],
                    "" if qgc_seen[0] else "   (QGC not connected yet)"))
    except KeyboardInterrupt:
        print("\n[bridge] stopping")
    finally:
        stop.set()
        tcp.close()
        udp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
