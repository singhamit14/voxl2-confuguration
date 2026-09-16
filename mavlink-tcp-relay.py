#!/usr/bin/env python3
"""
MAVLink TCP <-> UDP relay for VOXL 2, for use over `adb forward`.

VOXL 2 cannot serve QGroundControl over USB-C. This bridges the gap for BENCH USE:

    QGC (PC, TCP) --adb forward--> board TCP :14650 --UDP--> voxl-mavlink-server :14550

voxl-mavlink-server already listens on UDP 14550 for a GCS to initiate contact, so
no config change or service restart is needed. The relay registers itself by sending
one HEARTBEAT, after which the server streams telemetry back.

TCP is a byte stream and UDP is datagrams, so TCP->UDP splits the stream on MAVLink
frame boundaries and sends one datagram per frame. UDP->TCP just concatenates.

BENCH ONLY. Not a flight configuration - do not rely on a USB cable in the air.
"""

import socket
import struct
import sys
import threading

TCP_PORT = 14650                      # relay listens here; adb forwards the PC to it
# The relay stands in for voxl-mavlink-server on the GCS path and speaks to PX4's
# apps-side bridge directly. voxl-mavlink-server MUST be stopped, because it owns
# the receive port. Taking 14550 instead is not possible: the server binds
# 0.0.0.0:14550 and transmits to <gcs_ip>:14550, so no second socket can own it.
RELAY_ADDR = ("127.0.0.1", 14559)     # gcs_port_from_autopilot - PX4 sends telemetry here
MAVLINK_UDP = ("127.0.0.1", 14558)    # gcs_port_to_autopilot   - PX4 listens for commands here

V1_MAGIC = 0xFE
V2_MAGIC = 0xFD


def crc16_mcrf4xx(data, crc=0xFFFF):
    """MAVLink checksum (CRC-16/MCRF4XX)."""
    for b in data:
        tmp = b ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def build_heartbeat(seq=0, sysid=255, compid=190):
    """A GCS HEARTBEAT (msgid 0, CRC_EXTRA 50) so the server learns our address."""
    payload = struct.pack("<IBBBBB",
                          0,    # custom_mode
                          6,    # type = MAV_TYPE_GCS
                          8,    # autopilot = MAV_AUTOPILOT_INVALID
                          0,    # base_mode
                          4,    # system_status = MAV_STATE_ACTIVE
                          3)    # mavlink_version
    header = struct.pack("<BBBBBBB", len(payload), 0, 0, seq, sysid, compid, 0)
    header += b"\x00\x00"                      # msgid is 3 bytes, id 0
    frame = header + payload
    crc = crc16_mcrf4xx(frame)
    crc = crc16_mcrf4xx(bytes([50]), crc)      # CRC_EXTRA for HEARTBEAT
    return bytes([V2_MAGIC]) + frame + struct.pack("<H", crc)


def split_frames(buf):
    """Pull complete MAVLink frames out of a byte stream. Returns (frames, remainder)."""
    frames = []
    i = 0
    n = len(buf)
    while True:
        while i < n and buf[i] not in (V1_MAGIC, V2_MAGIC):
            i += 1                              # resync on garbage
        if i >= n:
            break
        if buf[i] == V1_MAGIC:
            if n - i < 8:
                break
            total = 6 + buf[i + 1] + 2
        else:
            if n - i < 12:
                break
            signed = buf[i + 2] & 0x01          # incompat_flags bit 0 = signature present
            total = 10 + buf[i + 1] + 2 + (13 if signed else 0)
        if n - i < total:
            break                               # frame not fully arrived yet
        frames.append(bytes(buf[i:i + total]))
        i += total
    return frames, buf[i:]


def log_rc_channels(frame, state):
    """Decode RC_CHANNELS (msgid 65) so we can see exactly what QGC is being sent."""
    if len(frame) < 12 or frame[0] != V2_MAGIC:
        return
    if int.from_bytes(frame[7:10], "little") != 65:
        return
    payload = frame[10:10 + frame[1]]
    if len(payload) < 42:
        return
    chans = struct.unpack("<18H", payload[4:40])
    chancount, rssi = payload[40], payload[41]
    state["n"] += 1
    if state["n"] % 20 == 1:                     # ~every 3 s at 7 Hz
        print("[rc] #{} chancount={} rssi={} ch1-6={}".format(
            state["n"], chancount, rssi, list(chans[:6])), flush=True)


def handle_client(conn, addr, udp):
    """Pump one client. `udp` is owned by main() and outlives every client."""
    print("[relay] QGC connected from {}".format(addr), flush=True)

    # Re-register with voxl-mavlink-server so it (re)learns our address and
    # resumes streaming to this port.
    udp.sendto(build_heartbeat(), MAVLINK_UDP)

    stop = threading.Event()
    stats = {"to_qgc": 0, "to_px4": 0}
    rc_state = {"n": 0}

    def udp_to_tcp():
        while not stop.is_set():
            try:
                data, _ = udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                for fr, _ in [(data, None)]:
                    log_rc_channels(fr, rc_state)
                conn.sendall(data)
                stats["to_qgc"] += len(data)
            except OSError:
                break
        stop.set()

    t = threading.Thread(target=udp_to_tcp, daemon=True)
    t.start()

    buf = bytearray()
    try:
        while not stop.is_set():
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            frames, rest = split_frames(buf)
            buf = bytearray(rest)
            for f in frames:
                udp.sendto(f, MAVLINK_UDP)     # one datagram per MAVLink frame
                stats["to_px4"] += len(f)
    except OSError:
        pass
    finally:
        stop.set()
        conn.close()
        print("[relay] QGC disconnected ({} B to GCS, {} B to PX4)".format(
            stats["to_qgc"], stats["to_px4"]), flush=True)


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(1)
    print("[relay] TCP {} <-> UDP {}:{} (as GCS {}:{})".format(
        TCP_PORT, MAVLINK_UDP[0], MAVLINK_UDP[1],
        RELAY_ADDR[0], RELAY_ADDR[1]), flush=True)
    print("[relay] on the PC:  adb forward tcp:14551 tcp:{}".format(TCP_PORT), flush=True)

    # One UDP socket for the life of the relay. Binding it per client raced:
    # the incoming client bound RELAY_ADDR while the outgoing one still held it
    # and, with SO_REUSEADDR, the kernel kept delivering PX4's telemetry to the
    # socket that was about to close.
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind(RELAY_ADDR)
    udp.settimeout(1.0)

    current = {"conn": None}
    try:
        while True:
            conn, addr = srv.accept()
            # Only one client at a time: the shared UDP socket delivers each
            # datagram to exactly one reader, so a second concurrent client
            # would go deaf. Drop the older connection instead.
            old = current["conn"]
            if old is not None:
                print("[relay] dropping previous client for {}".format(addr), flush=True)
                try:
                    old.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    old.close()
                except OSError:
                    pass
            current["conn"] = conn
            threading.Thread(target=handle_client, args=(conn, addr, udp),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\n[relay] stopping", flush=True)
    finally:
        srv.close()
        udp.close()


if __name__ == "__main__":
    sys.exit(main())
