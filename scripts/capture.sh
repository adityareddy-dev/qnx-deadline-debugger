#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: sh capture.sh /absolute/path/deadline /new/capture/directory" >&2
    exit 1
fi
workload=$1
capture_dir=$2
case "$workload" in /*) ;; *) echo "Use an absolute workload path" >&2; exit 1 ;; esac
mkdir -p "$capture_dir"
cd "$capture_dir"
logger_pid=
trap 'if [ -n "$logger_pid" ]; then kill -INT "$logger_pid" 2>/dev/null || true; fi' EXIT
trap 'exit 1' INT TERM

for mode in fault fixed; do
    if [ -e "$mode.kev" ]; then
        echo "$mode.kev already exists. Choose a new capture directory." >&2
        exit 1
    fi
    tracelogger -w -c -s 8 -k 128 -b 128 -F1 -F2 -F6 -F7 \
        -f "$mode.kev" > "$mode.log" 2>&1 &
    logger_pid=$!
    sleep 1
    "$workload" "$mode"
    wait "$logger_pid"
    logger_pid=
done
uname -a > guest.txt
echo "Captured fault.kev and fixed.kev. Export both with traceprinter on the host."
