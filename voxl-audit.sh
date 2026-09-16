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
