# QNX deadline debugger

A host-side tool for explaining a missed deadline in a QNX 8.0 workload.
The first capture and workload are next to build. There is no measured result yet.

The intended target is QNX OS 8.0 on x86_64 QEMU, built with QNX SDP 8.0.
The host parser and browser timeline will use a trace recorded in that guest.
QEMU measurements describe guest execution and do not establish hardware
real-time guarantees.

## Current setup

QEMU 10.2.1 is available on the development host. QNX SDP, an activated license,
and a QNX guest image are still needed before compiling or recording the workload.
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

## License

Project source uses the [MIT license](LICENSE). QNX software and system images
are obtained separately through QNX Everywhere.
