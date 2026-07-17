# Real W1 clock and process evidence

These files were captured from the same eight-second W1 run on 2026-07-15.
The tracked JSON files are unmodified copies of the local calibration and
process manifests. `w1_run_manifest.json` records their SHA-256 digests and a
digest of the complete raw CTF directory.

The run used:

```bash
bash scripts/run_ros2_tracing_smoke.sh w1 8
```

The complete CTF remains outside Git at the path recorded in the run manifest.
It contained 147,877 events. The bounded fixture contract checks the 13 core
ROS 2 event types used by the adapter. RuntimeEvent v2 produced 622 events
across 30 traces and four processes. The process PID set was compared against
all RuntimeEvent records after the run and matched exactly.

The local monotonic calibration used 1,000 bracketed samples. The estimated
offset was 24 ns and the conservative maximum error was 2,381 ns, below the
100,000 ns acceptance tolerance. This result establishes same-host
comparability only; it is not evidence for PC/RK3568 cross-host alignment.
