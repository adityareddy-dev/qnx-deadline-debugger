#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: sh scripts/boot-qemu.sh /path/to/qemu/output/disk-qemu" >&2
    exit 1
fi
image=$(realpath "$1")
state_dir=${QNX_GUEST_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/qnx-deadline-debugger}
mkdir -p "$state_dir"
if [ ! -f "$state_dir/guest.qcow2" ]; then
    qemu-img create -f qcow2 -F raw -b "$image" "$state_dir/guest.qcow2"
fi
exec qemu-system-x86_64 -accel tcg -machine pc -cpu max -smp 1 -m 2048 \
    -drive "file=$state_dir/guest.qcow2,format=qcow2,if=ide" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2228-:22 \
    -device virtio-net-pci,netdev=net0 -display none -serial mon:stdio -no-reboot
