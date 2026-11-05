# QNX deadline debugger

A host-side tool for explaining a missed deadline in a QNX 8.0 workload.
The workload source is prepared. Its first QNX build and capture are next.
There is no measured result yet.

The intended target is QNX OS 8.0 on x86_64 QEMU, built with QNX SDP 8.0.
The host parser and browser timeline will use a trace recorded in that guest.
QEMU measurements describe guest execution and do not establish hardware
real-time guarantees.

## Current setup

QEMU 10.2.1 and QNX Software Center 2.0.4 are installed on the development host.
The free SDP 8.0 licence is deployed to the development account. Software Center
still needs its separate sign-in before downloading SDP and the guest image.
The application is not runnable yet.

QNX's [QEMU setup guide](https://qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.target_images/topic/qsti_qemu/about.html)
describes the free QNX Everywhere license, Software Center and SDP installation.
The [image instructions](https://qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.target_images/topic/qsti_qemu/getting_started.html)
name the `com.qnx.qnx800.quickstart.qemu` package.

## Capture approach

The capture tool is QNX's
[tracelogger](https://qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/t/tracelogger.html).
Its original `.kev` file will remain alongside a text export from
[traceprinter](https://qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/t/traceprinter.html).
The text export is the planned parser input. The exact format and commands will
be recorded after testing them against QNX 8.0 output.

The workload will demonstrate one scheduling fault and one fix. Both runs will
include their configuration, commands, original capture and checksums. The
timeline will link each explanation to captured events, including the delayed
task's ready and running states. A second capture will supply the comparison.

No sample traces, screenshots or improvement figures have been added.

## Workload source

`workload/deadline.c` contains two FIFO threads for a single CPU guest. The
control thread requests 2 ms of CPU time every 100 ms, with a 20 ms deadline
and a release offset of 5 ms. A background thread requests 30 ms every 100 ms.
In `fault` mode its priority is 30, above the control thread's priority of 20.
In `fixed` mode only the background priority changes, to 10.

These are workload settings, not measured execution times or results. The
workload runs 20 jobs per thread. User trace event 100 carries configuration,
thread identity, expected release and deadline, and observed start and finish
timestamps. Kernel thread events must establish when each thread became ready
and ran. A user start marker alone does not show the time spent ready.

After sourcing `qnxsdp-env.sh`, `make` will build `build/deadline` with the
`gcc_ntox86_64` compiler variant. On the QNX guest, the intended commands are
`./deadline fault` and `./deadline fixed` while `tracelogger` records. QNX
compilation, required guest permissions and capture commands remain to verify.
The program fails on scheduling and trace API errors. It requires one guest
CPU and an instrumented kernel. It does not supply a substitute trace on Linux.

## License

Project source uses the [MIT license](LICENSE). QNX software and system images
are obtained separately through QNX Everywhere.
