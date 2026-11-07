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

The catalog is [`diagnosis/rules/root_cause_catalog.json`](../../diagnosis/rules/root_cause_catalog.json).
It is an ordinary JSON file parsed with the Python standard library; no
YAML-named catalog is used. The catalog identifies evidence semantics; it
contains no tuned numeric thresholds.

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

## What the score is computed from

`infer_trace()` is a per-trace, per-cause threshold scan over the graph's typed
nodes. For each catalog metric it takes the maximum matching node value, then
combines the supported metrics with the frozen weights and subtracts the
conflict and missing penalties.

The graph's edges are **not** part of that computation:

| edge | role |
| --- | --- |
| `BELONGS_TO`, `PRECEDES` | record how a window was admitted and ordered |
| `EXECUTED_BY`, `OVERLAPS` | record the association decision that placed evidence |
| `MISSING_EXPECTED` | materialises a topology gap as a node, so it is auditable |
| `SUPPORTS`, `CONTRADICTS` | added **after** scoring, then read by the report serializer |

So a `PRECEDES` violation does not by itself lower a score, and two graphs that
differ only in their edges produce the same candidates. Topology admission is
enforced earlier instead: an `invalid` validation abstains before scoring, and
a `partial` one halves completeness.

This is deliberate — the graph is an audit and provenance structure that makes a
diagnosis explainable — but it means the README must not imply that inference
reasons over edge structure. Changing the scoring to consume edges is a separate
design change, not a bug fix.

The C++ core under `cpp_core/diagnosis/` exposes graph construction and the
typed node model, but no inference. Cross-language parity for scoring does not
exist yet.

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

## Running the chain

`scripts/run_diagnosis.py` executes capture -> association -> evidence graph ->
inference -> report in one command, so `--diagnosis-report` no longer has to be
written by hand:

```bash
python3 scripts/run_diagnosis.py \
  --runtime data/processed/runtime.jsonl \
  --system data/processed/system.jsonl \
  --profile data/processed/diagnosis-scoring.json \
  --workload w1 \
  --output data/reports/diagnosis.json
```

The output is a `diagnosis-report/v1` record with an `inputs.association`
summary, and it feeds `optimizer/integration/diagnosis_gate.py` directly.
`--trace-id` selects one trace when a capture contains several.

## Check

```bash
python3 -m unittest tests.evidence_graph.test_inference -v
python3 -m unittest discover -s tests -t . -q
python3 -m compileall -q diagnosis tests
```
