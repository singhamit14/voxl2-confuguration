#!/bin/bash
# Bring the bench QGC link up or down over the USB cable.
#
#   ./voxl-qgc.sh up       relay + forward + bridge + launch QGC. Stays in the
#                          foreground; Ctrl-C stops the bridge. The only command
#                          you need - but the argument 'up' is required.
#   ./voxl-qgc.sh up --no-qgc   same, but do not launch QGroundControl
#   ./voxl-qgc.sh down     revert to the stock configuration
#   ./voxl-qgc.sh status   show where things stand
#
# Path:  QGC (UDP 14550) <- qgc-bridge.py <- PC TCP 14551 --adb--> board 14650 --UDP--> PX4
#
# BENCH ONLY. Do not rely on a USB cable in the air.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
SVC=mavlink-tcp-relay

die() { echo "ERROR: $*" >&2; exit 1; }

# `pgrep -f qgc-bridge.py` also matches any shell whose command line merely
# mentions the name - including the one running this script. Require a python
# interpreter and drop our own PID and parent.
find_bridges() {
    pgrep -af 'python.*(qgc-bridge|mavlink-census)\.py' 2>/dev/null \
        | awk -v self="$$" -v par="$PPID" '$1 != self && $1 != par'
}

# QGC is a downloaded AppImage, not a packaged binary, so look in the usual spots.
launch_qgc() {
    if pgrep -x QGroundControl >/dev/null 2>&1; then
        echo "-- QGroundControl already running, leaving it alone"
        return
    fi
    qgc="${QGC_APPIMAGE:-}"
    if [ -z "$qgc" ]; then
        for c in "$HOME/Downloads/QGroundControl-x86_64.AppImage" \
                 "$HOME/QGroundControl-x86_64.AppImage" \
                 "$HOME/Applications/QGroundControl-x86_64.AppImage" \
                 /opt/QGroundControl-x86_64.AppImage; do
            [ -x "$c" ] && qgc="$c" && break
        done
    fi
    if [ -z "$qgc" ]; then
        echo "-- no QGroundControl AppImage found; start it yourself"
        echo "   (or set QGC_APPIMAGE=/path/to/QGroundControl-x86_64.AppImage)"
        return
    fi
    echo "-- launching $(basename "$qgc")"
    nohup "$qgc" >/tmp/qgc-launch.log 2>&1 &
}

need_device() {
    adb devices | grep -qw device || die "no ADB device. Plug in USB-C and check 'adb devices'."
}

case "${1:-}" in
up)
    need_device

    # The board keeps /data and /etc across reboots, but install if missing.
    if ! adb shell "test -f /data/mavlink-tcp-relay.py && echo ok" | grep -q ok; then
        echo "-- installing relay to /data"
        adb push "$DIR/mavlink-tcp-relay.py" /data/mavlink-tcp-relay.py >/dev/null || die "push failed"
    fi
    if ! adb shell "test -f /etc/systemd/system/$SVC.service && echo ok" | grep -q ok; then
        echo "-- installing systemd unit"
        adb push "$DIR/$SVC.service" "/etc/systemd/system/$SVC.service" >/dev/null || die "push failed"
        adb shell "systemctl daemon-reload"
    fi

    # Refuse to add a second bridge: the relay hands each datagram to ONE reader,
    # so a second one goes deaf and QGC sees a partial stream.
    if [ -n "$(find_bridges)" ]; then
        find_bridges
        die "a bridge is already running (above). Stop it first, or run './voxl-qgc.sh down'."
    fi

    echo "-- starting relay (this stops voxl-mavlink-server by design)"
    adb shell "systemctl start $SVC"
    sleep 1
    [ "$(adb shell "systemctl is-active $SVC" | tr -d '\r')" = active ] \
        || die "relay did not start. Check: adb shell 'journalctl -u $SVC -n 30'"

    echo "-- forwarding PC 14551 -> board 14650"
    adb forward --remove-all >/dev/null 2>&1
    adb forward tcp:14551 tcp:14650 >/dev/null || die "adb forward failed"

    [ "${2:-}" = "--no-qgc" ] || launch_qgc

    echo "-- starting bridge; QGC auto-connects once it is up."
    echo "   Ctrl-C here stops the bridge, then './voxl-qgc.sh down' to revert."
    echo
    exec "$DIR/qgc-bridge.py"
    ;;

down)
    pids=$(find_bridges | awk '{print $1}')
    if [ -n "$pids" ]; then
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null && echo "-- stopped bridge(s): $pids"
    fi
    if adb devices | grep -qw device; then
        adb forward --remove-all >/dev/null 2>&1 && echo "-- removed forwards"
        adb shell "systemctl stop $SVC; systemctl start voxl-mavlink-server"
        echo "-- relay stopped, voxl-mavlink-server restored"
    else
        echo "-- no ADB device; nothing to revert on the board"
        echo "   (a power cycle restores stock configuration by itself)"
    fi
    ;;

status)
    if adb devices | grep -qw device; then
        echo "relay:               $(adb shell "systemctl is-active $SVC" | tr -d '\r')"
        echo "voxl-mavlink-server: $(adb shell 'systemctl is-active voxl-mavlink-server' | tr -d '\r')  (inactive is expected while the relay runs)"
        echo "voxl-px4:            $(adb shell 'systemctl is-active voxl-px4' | tr -d '\r')"
    else
        echo "no ADB device"
    fi
    echo "forwards:            $(adb forward --list | tr '\n' ' ')"
    n=$(find_bridges | wc -l)
    echo "bridges running:     $n  (must be 0 or 1; 2+ makes QGC see a partial stream)"
    find_bridges | sed 's/^/                     /' 
    ;;

*)
    echo "voxl-qgc.sh needs an argument. Usage:"
    echo
    # Print the header comment block, however long it grows.
    awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
    exit 1
    ;;
esac
