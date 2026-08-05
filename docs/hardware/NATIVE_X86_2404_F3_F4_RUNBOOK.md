# Native Ubuntu 24.04/Jazzy F3/F4 Runbook

This package targets a native x86_64 Ubuntu 24.04 host and ROS 2 Jazzy. It is
not WSL, Docker, or VM evidence. The resulting F3/F4 data must be reported as
a separate Ubuntu 24.04/Jazzy platform partition from existing Ubuntu
22.04/Humble-oriented evidence.

This runbook is a planned qualification procedure. Its presence, and the
historical candidate files under `docs/evidence/native-f3f4-formal-v3/`, do
not establish that a native formal session was completed.

```bash
cd ~/Desktop
unzip RoboTraceOpt_x86_ubuntu2404_F3F4_20260729.zip
cd RoboTraceOpt_x86_ubuntu2404_F3F4_20260729/RoboTraceOpt
sudo bash scripts/install_native_x86_2404_dependencies.sh
sudo bash scripts/run_native_x86_2404_f3_f4.sh
```

The runner first writes a capability report. If eBPF, ROS tracing, or identity
comparability is blocked, it stops without fabricating a result. If the host
passes preflight, it attempts the planned F3/F4 control and injected matrix.
No result may be promoted until the returned raw artifacts pass the current
qualification and integrity checks.

Return the printed experiment directory and capability JSON as one archive:

```bash
cd ~/Desktop/RoboTraceOpt_x86_ubuntu2404_F3F4_20260729/RoboTraceOpt
tar -czf ~/Desktop/F3F4_ubuntu2404_jazzy_results.tar.gz \
  data/raw/experiments/test/native_x86_2404_jazzy_f3f4_* \
  data/raw/environment/native_x86_2404_jazzy_f3f4_*_capabilities.*
```
