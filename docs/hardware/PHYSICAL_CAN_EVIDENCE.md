# Physical CAN Evidence Protocol

## Scope and claim boundary

The retained physical result is a **two-interface physical SocketCAN smoke**:
the application uses `mock_mode=false`, a command crosses a physical CAN bus,
and a responder peer returns the matching ACK. This is useful transport-path
evidence, but it is not a real ECU HIL test, a motor/actuator test, a Bus-Off
recovery result, or a formal X5/native-Linux measurement conclusion.

`physical_can_evidence=true` means that the capture saw two distinct, UP
Linux `can` interfaces and retained the selected transport artifacts. It does
not certify device behavior, functional safety, task success, or controller
deadline compliance.

The current `run_x5_demo.py` workflow is development-only. A future formal
physical-CAN protocol must be frozen separately; this checklist specifies the
minimum retained evidence for that protocol and for any defensible development
capture.

## Required evidence package

Create one new directory per attempt under `data/raw/physical_can/` or
`data/raw/demos/`. Do not reuse an output directory after failure. Retain this
structure before making a physical-CAN claim:

```text
<run-id>/
  provenance/
    hardware_provenance.md
    repository_state.txt
    host_state.txt
  snapshots/
    can0.before.json
    can1.before.json
    can0.after.json
    can1.after.json
  preflight/
    report.json
    report.md
  demo/
    preflight/
      report.json
      report.md
    control/
      candump.log
      responder.jsonl
      socketcan_capture_manifest.json
      physical_ack_report.json
    injected/
      candump.log
      responder.jsonl
      socketcan_capture_manifest.json
      physical_ack_report.json
    demo_summary.json
    physical_comparison.json
    report/
```

The script creates the condition-level `candump.log` and
`socketcan_capture_manifest.json`. Each physical capture manifest includes the
before/after pair it observed, `candump` identity and hash, responder command,
and the capture-file hashes. The top-level snapshots are retained as an
operator-visible record and must agree with the generated manifests on adapter
identity, transport type, and configured bitrate. Traffic counters may differ
because they are sampled at different times.

Raw evidence is intentionally ignored by Git. Keep it on retained local or
removable storage; publish only a redacted derivative when needed.

## Record provenance before the run

From the repository root, use a unique run ID and replace `can0`/`can1` if the
selected interface names differ:

```bash
RUN_ID="physical_can_$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="data/raw/physical_can/${RUN_ID}"
DEMO_DIR="${EVIDENCE_DIR}/demo"
mkdir -p "$EVIDENCE_DIR"/{provenance,snapshots,preflight}

git rev-parse HEAD > "$EVIDENCE_DIR/provenance/repository_state.txt"
git status --short >> "$EVIDENCE_DIR/provenance/repository_state.txt"
uname -a > "$EVIDENCE_DIR/provenance/host_state.txt"
ip -details -json link show can0 > "$EVIDENCE_DIR/snapshots/can0.before.json"
ip -details -json link show can1 > "$EVIDENCE_DIR/snapshots/can1.before.json"
```

`hardware_provenance.md` must record:

- board model, revision, and serial or stable local asset identifier;
- OS image, kernel, and relevant CAN driver/firmware versions;
- runtime and peer adapter vendor/model, USB serial, stable device path,
  SocketCAN interface name, and firmware version when available;
- CAN cable topology, termination measurement, selected bitrate, and the full
  `slcand` command when SLCAN is used;
- UTC start time, operator, Git commit, and any hardware substitutions.

Keep raw serials in the retained evidence package. Before sharing outside the
project, replace them with stable redacted identifiers and state that the
mapping is retained privately.

## Configure adapters

Use the native SocketCAN commands in
[`X5_RUNBOOK.md`](X5_RUNBOOK.md) when netlink reports the CAN bitrate.

For CANable/SLCAN hardware, use stable device paths and one `slcand` process
per interface. At 500 kbit/s the accepted speed code is `-s6`:

```bash
sudo slcand -o -c -s6 /dev/serial/by-id/<runtime-adapter> can0
sudo slcand -o -c -s6 /dev/serial/by-id/<peer-adapter> can1
sudo ip link set can0 up
sudo ip link set can1 up
pgrep -a -x slcand | tee "$EVIDENCE_DIR/provenance/slcand_processes.txt"
ip -details -json link show type can | tee "$EVIDENCE_DIR/provenance/can_links_configured.json"
```

The physical preflight rejects a virtual interface, a down interface, a
`BUS-OFF` link, a mismatch, or ambiguous/missing SLCAN bitrate provenance.

## Preflight and matched capture

Run the read-only preflight into the same evidence package. Never edit a
blocked report; correct the environment and use a new run ID.

```bash
python3 scripts/preflight_x5.py \
  --mode physical-can \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --output-json "$EVIDENCE_DIR/preflight/report.json" \
  --output-md "$EVIDENCE_DIR/preflight/report.md"
```

Run a complete normal/drop pair through the orchestrator. It holds the
transport profile, interfaces, bitrate, duration, and responder executable
constant; only the responder policy differs: `echo` for `control` and `drop`
for `injected`.

```bash
python3 scripts/run_x5_demo.py \
  --execute \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --duration-seconds 8 \
  --output-dir "$DEMO_DIR"
```

`run_x5_demo.py` requires its output directory not to exist, which is why the
orchestrated artifacts live below the pre-created evidence root in `demo/`.

After completion, record the final link state and preserve the generated logs
and manifests unchanged:

```bash
ip -details -json link show can0 > "$EVIDENCE_DIR/snapshots/can0.after.json"
ip -details -json link show can1 > "$EVIDENCE_DIR/snapshots/can1.after.json"
sha256sum \
  "$DEMO_DIR/control/candump.log" \
  "$DEMO_DIR/control/socketcan_capture_manifest.json" \
  "$DEMO_DIR/injected/candump.log" \
  "$DEMO_DIR/injected/socketcan_capture_manifest.json" \
  > "$EVIDENCE_DIR/provenance/operator_capture_sha256.txt"
```

If the run fails, retain the stage logs and failed summary. Do not rerun a
condition in place, replace a `candump` file, or reconstruct a missing
manifest.

## Review before reporting

For a completed development capture, check all of the following:

- `demo/demo_summary.json` reports every stage completed;
- preflight is ready and names the same interfaces/bitrate used by the pair;
- both condition directories contain non-empty `candump.log`, responder
  evidence, and a valid `socketcan_capture_manifest.json`;
- each manifest records distinct physical `can` interfaces before and after
  capture, and its file hashes match the retained files;
- `physical_comparison.json` compares the normal ACK and dropped-ACK paths;
- provenance, snapshots, and manifests agree on interface mapping and bitrate
  (counter values may differ by capture time).

Report it as: "physical two-interface SocketCAN normal/drop development
evidence with a responder peer." Do not shorten that to "ECU HIL," "real motor
control," "Bus-Off validated," or "formal experiment" unless a separately
frozen protocol and matching hardware evidence establish those claims.
