# Trace-stage association

## Current method

RuntimeEvent records are grouped by trace, sequence, process, host, and clock.
Within each group, adjacent semantic events define process-local StageWindows.
The final event is a point window unless it carries a non-zero duration.

System evidence is admitted in this order:

1. host identity must match;
2. clock domain must match;
3. callback registration events resolve subscription, timer, or service identity;
4. topology metadata and ROS infrastructure callbacks remain background;
5. timestamp must fall inside a StageWindow for the same PID;
6. an exact TID match outranks a PID-only match;
7. equal best candidates from different trace/stage targets are `ambiguous`;
8. no candidate is `unmatched` background evidence.

No nearest-trace fallback exists in the formal method. The separate
`associate_by_timestamp` function deliberately forces the nearest window and
is retained only as an ablation baseline.

Run the association on normalized inputs with:

```bash
python3 -m diagnosis.evidence_graph.association_report \
  --runtime data/processed/runtime.jsonl \
  --system data/processed/ros2.jsonl \
  --output data/reports/association.json
```

Every decision records source, event type, status, reason code, candidate
count, score, and the accepted trace/stage/window identity when applicable.

## Real same-run smoke

Clean session `robotracert_w1_20260715T111218Z_348` used one W1 run for
both RuntimeEvent and ROS 2 CTF evidence. It produced:

- 642 RuntimeEvent records and 31 traces;
- 99,127 selected ROS 2 events from the complete CTF;
- 642 StageWindows;
- 62 resolved callback identities;
- 4,801 accepted associations;
- 94,326 unmatched background events;
- zero forced or ambiguous formal assignments.

Of the accepted events, 4,589 used PID+TID+time and 212 used PID+time. Callback
identity rules retained 306 infrastructure callbacks and 266 topology metadata
events as background. The overall accepted rate of 4.84% is not an accuracy
metric: executor waiting and unrelated runtime events are also expected to
remain background evidence.

## Remaining Task 3.4 work

Callback handles are now resolved through subscription/timer/service linkage.
`evaluation.evaluate_associations` now computes edge precision, recall, F1,
and mixed-trace rate, and rejects incomplete oracle coverage. The remaining
step is to create an independent label file and freeze the workload topology
policy for business callback-to-stage compatibility. Metrics must not be
reported before that oracle is frozen. The current run summary is not final
association accuracy.
