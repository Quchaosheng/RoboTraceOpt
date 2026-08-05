# Public Evidence Index

Each directory below is a sanitized evidence or archive package with an
explicit protocol, claim boundary, source-artifact hashes, and package-level
`SHA256SUMS.txt`. Package classes are intentionally separate; results must not
be merged across environments or promoted beyond the package manifest.

The source checkout intentionally has no `data/` tree and no tracked raw,
processed, or report outputs. The result files listed below are committed,
sanitized projections under `docs/evidence/`; commands that write `data/` create
local ignored artifacts and do not change the qualification of a package.

| Package | Qualification | Supported claim | Explicitly unsupported |
| --- | --- | --- | --- |
| [`native-f3f4-formal-v3`](native-f3f4-formal-v3/) | Archived candidate projection | No completed public claim; retained for audit and rerun planning only | Native execution, paired F3/F4 effects, formal test evidence, diagnosis accuracy, optimization benefit, hardware safety |
| [`wsl-heldout-association-20260731`](wsl-heldout-association-20260731/) | Limited paper support | Run-held-out path identity and contract admission for two WSL2 overlap workloads | F1-F6 root-cause classification or native formal evidence |
| [`wsl-runtimeevent-overhead-20260712`](wsl-runtimeevent-overhead-20260712/) | Limited paper support | WSL2 proxy comparison of RuntimeEvent disabled, buffered, and flush modes | Native or four-mode tracing/fused overhead |
| [`x5-physical-can-smoke-20260727`](x5-physical-can-smoke-20260727/) | Limited hardware smoke | X5-class arm64 dual-CANable normal-ACK transport path | ECU HIL, drop/timeout comparison, current model-safety proof |

The historical native package directory name is retained for compatibility,
but its current public projection is not accepted as formal evidence. Its raw
trace and per-event identity records are absent, so the archived metadata,
statistics, and figures must not be cited as completed native results. The
limited packages set `formal_experiment_allowed=false` and explain the missing
controls in their public protocol manifests.

`build_formal_evidence_package.py` can rebuild an archival native F3/F4
projection from explicitly supplied inputs; running the builder does not
qualify those inputs or promote them to formal evidence.
`build_limited_evidence_packages.py` rebuilds the WSL overhead and X5 smoke
packages from explicitly supplied source roots. Neither script contains
private default paths; the limited-package builder resamples whole runs for
bootstrap intervals.
