# Diagnosis evaluation contract

`diagnosis.evaluation` is the shared evaluator for `app_only`, `tracing_only`,
`ebpf_only`, and `fused`. A mode label changes only the report metadata, not
the metric implementation.

## Oracle gate

Every prediction must have exactly one independent oracle label. Missing,
extra, or duplicate trace labels are errors. Each label declares a dataset
role and a session ID. Calibration and test partitions must be disjoint at
both trace and session level; traces from one run cannot be split across the
two roles.

The oracle declares either one root cause or that the system should abstain.
It is consumed only by the evaluator and never by graph construction or
inference.

## Metrics

- Top-1 accuracy and Top-k recall use only samples with an injected root-cause
  label. Top-k evaluates the retained ranking even when the inference gate
  abstains.
- Macro-F1 uses the fault-class subset so it does not duplicate the separate
  abstention metric.
- Abstention accuracy and the published confusion matrix use all samples,
  including evidence-invalid or deliberately incomplete cases.
- Confidence Brier score and ECE use answered fault cases only. Empty
  calibration groups return `null`, not zero.

The evaluator returns sample and session counts with every report. No metric
is a formal result until the input reports and oracle labels belong to a
frozen held-out manifest.

## Check

```bash
python3 -m unittest tests.evidence_graph.test_diagnosis_evaluation -v
python3 -m unittest discover -s tests -q
```
