# Typed evidence graph

## Scope

The graph builder consumes StageWindows, normalized system events, explicit
association decisions, and one frozen workload topology contract. It does not
infer root causes or read evaluation-only oracle fields.

The first contract set contains:

- W1: Camera -> Planner -> ActionManager -> CAN -> ACK, with distinct
  `ack_received`, `retry_exhausted`, and `send_failed` terminal paths;
- W2: the six-stage service request/response path.

Unknown workloads have no implicit fallback contract.

## Admission rules

1. Every system event must have exactly one association decision.
2. Only `accepted` decisions create nodes inside a trace subgraph.
3. The accepted trace, sequence, stage, and StageWindow must agree.
4. `unmatched`, `ambiguous`, and `rejected` evidence remains in the graph's
   `unassigned` audit collection.
5. Reusing one trace ID with different sequence IDs is rejected.

Stage order is checked against required topology milestones. Extra events such
as Action feedback or CAN retry scheduling remain observable but do not alter
the required path. Missing milestones are represented by `StageWindow` nodes
whose `evidence_state` is `missing`; they have no timestamps or provenance and
are connected with `missing_expected`. Conflicting observed stages are linked
with `contradicts`. Missing placeholders must never be counted as observations.

## Typed evidence

The model freezes the nine node types and seven edge types defined by the design
plan. The current builder materializes Trace, StageWindow, ROS callback, DDS,
syscall, scheduling, CAN command, and ACK terminal evidence. CandidateCause
nodes and `supports` edges are reserved for root-cause inference in Task 6.3.

NetworkX may later provide traversal and analysis, but it does not define the
node semantics, admission policy, topology contract, or diagnostic rules.

## Check

```bash
python3 -m unittest tests.evidence_graph.test_evidence_graph -v
python3 -m unittest discover -s tests -q
python3 -m compileall -q diagnosis tests
```
