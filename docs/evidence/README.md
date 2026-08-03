# Public Evidence Index

Each directory below is a sanitized evidence package with an explicit protocol,
claim boundary, source-artifact hashes, and package-level `SHA256SUMS.txt`.
Evidence classes are intentionally separate; results must not be merged across
environments or promoted beyond the package manifest.

| Package | Qualification | Supported claim | Explicitly unsupported |
| --- | --- | --- | --- |
| [`native-f3f4-formal-v3`](native-f3f4-formal-v3/) | Formal native test evidence | Native Ubuntu 24.04 / Jazzy F3 complete-path recovery and F4 blocking-delay effects | Diagnosis Top-1/Macro-F1, optimization benefit, hardware safety |
| [`wsl-heldout-association-20260731`](wsl-heldout-association-20260731/) | Limited paper support | Run-held-out path identity and contract admission for two WSL2 overlap workloads | F1-F6 root-cause classification or native formal evidence |
| [`wsl-runtimeevent-overhead-20260712`](wsl-runtimeevent-overhead-20260712/) | Limited paper support | WSL2 proxy comparison of RuntimeEvent disabled, buffered, and flush modes | Native or four-mode tracing/fused overhead |
| [`x5-physical-can-smoke-20260727`](x5-physical-can-smoke-20260727/) | Limited hardware smoke | X5-class arm64 dual-CANable normal-ACK transport path | ECU HIL, drop/timeout comparison, current model-safety proof |

The formal package retains the exact experiment commit, session qualification,
statistics, and figures. The limited packages set
`formal_experiment_allowed=false` and explain the missing controls in their
public protocol manifests.

`build_formal_evidence_package.py` rebuilds the native F3/F4 projection from
explicitly supplied session, environment, analysis, statistics, scheduler, and
figure roots. `build_limited_evidence_packages.py` rebuilds the WSL overhead
and X5 smoke packages from explicitly supplied source roots. Neither script
contains private default paths; the limited-package builder resamples whole
runs for bootstrap intervals.
