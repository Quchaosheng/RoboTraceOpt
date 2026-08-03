# RoboTraceOpt run-held-out association evidence

## Evidence role

This package records a post hoc run-held-out evaluation of path association on
the existing `paper_formal_20260712` WSL2 / Ubuntu 22.04 / ROS 2 Humble logs.
It is paper-supporting association evidence, not native-Linux formal evidence
and not a multi-class root-cause diagnosis evaluation.

The split is fixed per scenario:

- calibration: `run_01` through `run_05`;
- held-out test: `run_06` through `run_10`;
- scenarios: dual 10 Hz and dual mixed-rate overlap;
- unit: one run invocation on the same host and boot, not an independent reboot.

## Headline results

For the `trace_id_contract` policy:

| Scenario | Held-out oracle traces | Precision | Recall | F1 | Run-bootstrap 95% F1 CI |
| --- | ---: | ---: | ---: | ---: | ---: |
| dual 10 Hz | 6,024 | 1.0000 | 0.9772 | 0.9884 | [0.9793, 0.9939] |
| dual mixed-rate | 5,178 | 1.0000 | 1.0000 | 1.0000 | [1.0000, 1.0000] |

The dual 10 Hz recall loss comes from naturally incomplete paths. The policy
has zero observed mixed-chain and false-admission rates in these held-out runs.
Timestamp-only and sequence-only baselines fail under overlap, while source
plus sequence, trace ID, and trace ID plus contract preserve identity.

## Oracle boundary

The predictor receives only event UID, trace ID, sequence ID, stage, and
timestamp. Public predictions contain no oracle column. Oracle IDs are joined
only by the scoring stage after public groups have been generated. This is a
code-path isolation check, not evidence of an externally preregistered label
seal.

## Provenance and limitations

- All 20 source event files and manifests match the SHA-256 values in
  `results/run_split_manifest.csv`.
- The source commit `65273ead83545d89f1f6bb8daeeded68cc926337` remains in the
  ROS2Probe history.
- Source manifests record `git_dirty=true` and source-tree hash
  `0973596604c8b7acd4a6ad3277ea43035d6c7c4e63b32089513847afa3ffaaaa`.
- The workload uses explicit mock-mode delays on WSL2. Results do not establish
  native scheduler or syscall causality, physical CAN behavior, or real-robot
  timing.
- The labels evaluate association identity and path validity. They do not
  provide F1-F6 root-cause classes, Top-1 diagnosis accuracy, Macro-F1,
  abstention quality, or cross-source diagnosis ablations.

## Package contents

- `evaluate_heldout_association.py`: frozen v2 evaluator used for recomputation;
- `protocol_manifest.public.json`: path-sanitized protocol;
- `results/heldout_summary.csv`: held-out association metrics and run bootstrap
  intervals;
- `results/calibration_timestamp_selection.csv`: calibration-only timestamp
  baseline selection;
- `results/negative_control_summary.csv`: fault-injection validator ablations;
- `results/run_split_manifest.csv`: relative source paths and input hashes;
- `results/source_result_hashes.csv`: hashes of all local full-result files,
  including row-level outputs not copied into this public package.
- `SHA256SUMS.txt`: SHA-256 digest for every distributed file in this directory.

No raw events, row-level oracle labels, or private absolute paths are included.
