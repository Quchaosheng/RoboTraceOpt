# Root-cause inference contract

## Current boundary

This module implements the auditable inference mechanism for Chapter 4. It
does not provide a formal scoring profile or diagnosis-accuracy result. The
repository currently contains synthetic contract tests only. Thresholds,
weights, and abstention limits must be calibrated and frozen before final test
runs.

The catalog contains the six planned fault classes:

- application compute delay;
- executor queueing;
- DDS or communication delay;
- blocking syscall or I/O;
- scheduling delay;
- CAN or application ACK failure.

`root_cause_catalog.yaml` uses the JSON subset of YAML 1.2 so it can be parsed
with the Python standard library. The catalog identifies evidence semantics;
it contains no tuned numeric thresholds.

## Scoring gate

`ScoringProfile.from_dict` accepts only `diagnosis-scoring/v1` records that:

1. declare `dataset_role=calibration`;
2. declare `frozen_before_test=true`;
3. provide a stable profile ID and calibration-manifest SHA-256;
4. use identical metric keys for thresholds and weights;
5. use positive thresholds and weights and bounded completeness limits.

The initial score is a weighted count of threshold-supported evidence, minus
fixed conflict and missing-evidence penalties. Values far above a threshold do
not receive an unbounded multiplier. Application-only delay is contradicted
when a configured syscall or scheduling cause has supporting evidence.

## Evidence states and abstention

- `valid`: required sources and topology are complete;
- `partial`: a source or topology path is incomplete;
- `invalid`: an identity, topology, or capture gate failed;
- `not_observed`: a valid source ran but no configured metric was observed.

Invalid topology and invalid evidence always abstain. The inference also
abstains when completeness is below the frozen limit, no candidate reaches the
minimum score, or the Top-1 margin is too small. Partial topology halves the
computed completeness before applying the frozen gate.

Reports use `diagnosis-report/v1` and include Top-1/Top-k only for a diagnosed
result. Candidate rankings, support/conflict/missing evidence, source
availability, calibration-manifest identity, stable reason codes, and original
evidence provenance remain available for audit even after abstention.

## Check

```bash
python3 -m unittest tests.evidence_graph.test_inference -v
python3 -m unittest discover -s tests -q
python3 -m compileall -q diagnosis tests
```
