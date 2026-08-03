# X5 Physical CAN Normal-ACK Smoke Evidence

This sanitized package preserves the strongest existing X5 dual-CANable capture. It is **hardware smoke evidence**, not ECU HIL and not a formal fault-control experiment.

## Observed

- arm64 Ubuntu 22.04.5 with a PREEMPT_RT kernel.
- Two physical CANable/SocketCAN interfaces at 500 kbit/s.
- One 40-second camera-to-action-to-CAN session.
- 34 runtime sends, 34 matched runtime ACKs, and 100% payload matching.
- 34 retained 1280x720 USB-camera frames; public archive carries hashes rather than scene images.

## Boundaries

- Only the normal ACK path was captured; there is no paired drop/timeout condition.
- The planner backend was mock. The physical claim applies to camera capture and CAN transport, not model inference or the current fail-closed runtime.
- This is not an ECU or vehicle HIL setup.

Local paths, machine identifiers, boot identifiers, and camera serial values are removed. Source hashes bind the package to the preserved local capture.
