# Planner runtime core

This directory contains the dependency-free C++17 portion of the planner
runtime contract. It preserves the fail-closed rules that can be tested
without ROS or a model provider:

- planner decisions, requests, results, and stable public error codes;
- decision validation;
- TTL, future-skew, duplicate, and failure-window admission;
- deterministic mock decisions;
- typed replay records with unique-match-or-reject behavior.

Build and test this directory independently:

```sh
cmake -S cpp_core/planner -B build/planner
cmake --build build/planner
ctest --test-dir build/planner --output-on-failure
```

## Deferred adapters

The following remain outside this dependency-free core and must be added as
separate adapters:

- canonical JSON and SHA-256 request/response fingerprints;
- JSONL recording file parsing and append-only persistence;
- HTTP/TLS, OpenAI-compatible payloads, and image base64 encoding;
- ROS 2 messages, parameters, QoS, executor integration, and event publishing;
- real sleep/busy-compute timing injection.

Replay currently consumes typed `DecisionRecord` values. A later JSONL
adapter should validate `planner-decision-record/v1` before constructing those
records. This keeps malformed input handling out of the safety core.
