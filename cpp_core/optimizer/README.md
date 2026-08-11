# RoboTraceOpt optimizer C++ core

This directory ports the dependency-free algorithmic optimizer core to C++17.
It deliberately does not parse JSON or depend on ROS: adapters can translate
their input into the strong types in `include/robotraceopt/optimizer`.

## Public API

- `runtime_objective(...)` extracts a latency measurement and completeness
  constraint from `RuntimeReport`.
- `sample_candidates(...)` maps a `DiagnosisCause` to its permitted action and
  creates the same evenly spaced guided grid as the Python implementation.
- `percentile_bootstrap_interval(...)` calculates a percentile interval for a
  bootstrapped median.
- `validate_candidate_objectives(...)` evaluates a single candidate against a
  baseline.
- `evaluate_repeated_candidates(...)` validates block-paired repeated trials,
  including missing/failed-pair rejection and completeness constraints.

Invalid measurements, schedules, thresholds, configuration mismatches and
duplicate records throw `std::invalid_argument`. Successful measurements must
be finite; objective values must be positive for validation, and trace rates
must be in `[0, 1]`. Bootstrap requires at least 100 resamples and a confidence
level strictly between zero and one.

## Build and test

```sh
cmake -S cpp_core/optimizer -B build/optimizer -DBUILD_TESTING=ON
cmake --build build/optimizer
ctest --test-dir build/optimizer --output-on-failure
```

The guided grid is independent of its seed, matching the current Python
policy. Bootstrap uses a specified, local SplitMix64 generator and unbiased
bounded sampling, so a fixed seed is repeatable across supported C++ standard
libraries. Python uses `random.Random` (MT19937) and a different integer-to-
sample mapping; bootstrap draws and finite-resample interval endpoints can
therefore differ between languages. Point estimates, decision rules and
large-resample statistical behavior remain compatible.
