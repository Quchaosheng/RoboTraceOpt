# RDK X5 Experiment and Defense Runbook

## Evidence boundary

The core X5 matrix and the physical CAN demonstration are separate:

- The core matrix supplies native ROS 2, tracing, eBPF, diagnosis, and
  optimization measurements.
- The physical CAN pair supplies additional F6 electrical-bus and ACK lifecycle
  evidence.
- The currently retained physical result is a two-interface SocketCAN smoke
  with a responder peer. It does not establish an ECU HIL result, actuator
  behavior, Bus-Off recovery, bus-load tolerance, or a formal physical-CAN
  experiment.
- The physical control/injected pair is development evidence until a separate
  physical-CAN formal protocol is frozen. The tools enforce this label.
- `vcan`, mock, dry-run, and WSL output cannot set
  `physical_can_evidence=true`.

Use [`PHYSICAL_CAN_EVIDENCE.md`](PHYSICAL_CAN_EVIDENCE.md) for the required
capture package and the exact limits of each claim.

## Hardware wiring

Use two Linux SocketCAN-compatible USB-CAN adapters. Connect the runtime adapter
to the X5 as `can0` and the ACK/fault peer as `can1`.

```text
X5 USB -> can0 ----- CAN-H ---------------- CAN-H ----- can1 <- X5 USB
                  |                              |
                 120 ohm                      120 ohm
                  |                              |
X5 GND ----------- CAN-L ---------------- CAN-L ----------- GND
```

Wire CAN-H to CAN-H, CAN-L to CAN-L, and a common ground. Place exactly one
120-ohm termination at each end. With power removed, the resistance between
CAN-H and CAN-L should be close to 60 ohms. Do not connect UART or CAN pins to a
5 V logic signal.

## Clone and bootstrap

The target is Ubuntu 22.04, aarch64, and ROS 2 Humble.

```bash
git clone https://github.com/Quchaosheng/RoboTraceOpt.git
cd RoboTraceOpt
bash scripts/bootstrap_x5.sh --dry-run
bash scripts/bootstrap_x5.sh --apply
```

The script does not alter the bootloader, kernel command line, or vendor kernel.
If the ROS apt repository is absent, configure the official ROS 2 Humble apt
repository and run `--apply` again.

Build the ROS workspace after sourcing Humble:

```bash
source /opt/ros/humble/setup.bash
bash scripts/build_core.sh
source ~/.cache/robotraceopt_build/install/setup.bash
```

## Configure physical CAN

First identify and record the physical adapter mapping. Never infer identity
from a transient `/dev/ttyACM*` index alone.

```bash
ls -l /dev/serial/by-id/ 2>/dev/null || true
ip -details -json link show type can | jq
```

### Native SocketCAN adapters

For adapters whose CAN controller is exposed directly by the kernel, bring both
interfaces up at the same bitrate:

```bash
ip -details -json link show type can | jq
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can1 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 500000 restart-ms 100
sudo ip link set can1 type can bitrate 500000 restart-ms 100
sudo ip link set can0 up
sudo ip link set can1 up
ip -details link show can0
ip -details link show can1
```

### CANable / SLCAN adapters

For SLCAN adapters, set the CAN bitrate through `slcand`; do not also apply the
native `ip link set ... type can bitrate` commands above. The current checker
recognizes `-s6` as 500 kbit/s and requires exactly one matching `slcand`
process per selected interface when netlink does not report a bitrate.

Replace the device paths with the stable `/dev/serial/by-id/...` paths recorded
for the two adapters:

```bash
sudo slcand -o -c -s6 /dev/serial/by-id/<runtime-adapter> can0
sudo slcand -o -c -s6 /dev/serial/by-id/<peer-adapter> can1
sudo ip link set can0 up
sudo ip link set can1 up
pgrep -a -x slcand
ip -details link show can0
ip -details link show can1
```

If adapter firmware needs an additional `slcand` serial-rate option, record the
full command in the provenance file. Do not leave stale or duplicate `slcand`
processes for either interface: the physical preflight rejects ambiguous
bitrate evidence.

Run a manual electrical smoke test in two terminals:

```bash
candump -L can1
```

```bash
cansend can0 123#01020304
```

The frame must appear on `can1`. Resolve `BUS-OFF`, missing frames, bitrate
mismatch, or termination errors before running RoboTraceOpt.

Before an evidence run, create a new directory and retain the adapter serials,
pre/post `ip -details` snapshots, preflight output, `candump`, both capture
manifests, and the matched normal/drop pair as specified in
[`PHYSICAL_CAN_EVIDENCE.md`](PHYSICAL_CAN_EVIDENCE.md). The raw directory is
intentionally ignored by Git; do not replace it with a prose result summary.

## Preflight

Preflight is read-only. It records the full underlying capability report and
returns status 2 when a requirement is blocked.

```bash
python3 scripts/preflight_x5.py \
  --mode software \
  --output-json data/raw/environment/x5-software-preflight.json \
  --output-md data/raw/environment/x5-software-preflight.md

python3 scripts/preflight_x5.py \
  --mode physical-can \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --output-json data/raw/environment/x5-physical-preflight.json \
  --output-md data/raw/environment/x5-physical-preflight.md
```

Do not edit a blocked report. Fix the reported environment or link state and
generate a new report.

## Rehearse the defense demonstration

Every invocation requires a new output directory.

```bash
python3 scripts/run_x5_demo.py \
  --dry-run \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --duration-seconds 8 \
  --output-dir data/raw/demos/x5_rehearsal_plan_01
```

Review `demo_plan.json`, then execute the same configuration in a new directory:

```bash
python3 scripts/run_x5_demo.py \
  --execute \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --duration-seconds 8 \
  --output-dir data/raw/demos/x5_rehearsal_01
```

The sequence performs preflight, normal ACK capture, dropped-ACK capture, two
three-source adapters, a matched physical comparison, and report generation.
Inspect:

```text
data/raw/demos/x5_rehearsal_01/demo_summary.json
data/raw/demos/x5_rehearsal_01/preflight/report.{json,md}
data/raw/demos/x5_rehearsal_01/control/candump.log
data/raw/demos/x5_rehearsal_01/control/socketcan_capture_manifest.json
data/raw/demos/x5_rehearsal_01/injected/candump.log
data/raw/demos/x5_rehearsal_01/injected/socketcan_capture_manifest.json
data/raw/demos/x5_rehearsal_01/physical_comparison.json
data/raw/demos/x5_rehearsal_01/report/experiment_report.md
data/raw/demos/x5_rehearsal_01/report/experiment_metrics.csv
```

The control path is the normal ACK condition and the injected path is the
dropped-ACK condition. Both must be retained under the same planned hardware
configuration. A successful demonstration still remains development evidence;
only a separately frozen physical-CAN protocol may promote its role.

## Core pilot and held-out session

Generate the formal capability input separately from the defense preflight:

```bash
python3 scripts/check_platform_capabilities.py \
  --label rdk-x5 \
  --can-interface can0 \
  --output-json data/raw/environment/rdk-x5.json \
  --output-md data/raw/environment/rdk-x5.md
```

Run a pilot first. Use a new session name and output directory for every attempt.
The first native pilot should keep the same selected cases, seed, and matrix that
will be used for the held-out run, but set `--dataset-role pilot` only where the
entry point permits that role. Follow the current top-level README command for
the frozen held-out case list after the pilot passes.

Never rerun a failed condition in place. Keep its directory, correct the cause,
and create a new session name. Use `--resume` only for an interrupted formal
session with the identical matrix, capability report, Git commit, role, seed,
and session name.

## Defense operation

Use mains power, active cooling, wired Ethernet, and a clean Git worktree. Start
the demonstration before screen sharing and keep these three files open:

1. physical preflight Markdown;
2. physical comparison JSON;
3. experiment report Markdown.

The live sequence should take three to five minutes: normal ACK, deterministic
drop, diagnosis evidence, and comparison. Do not run the repeated formal
campaign live.

Record one complete rehearsal including the board, CAN adapters, terminal, and
result report. Keep the recording and the successful evidence directory on a
separate USB drive. If a live adapter, cable, display, or network fails during
the defense, show the retained report and recording rather than creating data
or silently switching to vcan.

## Shutdown and recovery

```bash
sudo ip link set can0 down
sudo ip link set can1 down
```

If the demonstration fails, inspect the numbered stage log named in
`demo_summary.json`. A failed summary is deliberately retained. Never change its
status or reuse the directory.
