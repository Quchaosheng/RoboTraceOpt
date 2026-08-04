# Legacy Native x86 Ubuntu 22.04/Humble F3/F4 Runbook

This is the legacy native Ubuntu 22.04 / ROS 2 Humble runbook. It is separate
from the formal native Ubuntu 24.04 / ROS 2 Jazzy package. Use
[`NATIVE_X86_2404_F3_F4_RUNBOOK.md`](NATIVE_X86_2404_F3_F4_RUNBOOK.md) when
reproducing or extending that Jazzy partition; do not merge outputs from the
two environments.

## Why not WSL2

WSL2 runs Linux in a virtualized kernel and exposes namespace PIDs that cannot
be proven identical to eBPF task IDs. F3 and F4 require a native Linux host so
the RuntimeEvent process identity, ROS 2 trace evidence, and eBPF scheduler or
syscall events can be associated without a name-based fallback.

## Qualified host

- Native x86_64 Ubuntu 22.04 (not WSL, Docker, or a virtual machine).
- Internet access for package installation.
- `sudo` permission.
- At least 15 GB free disk space; close other CPU-intensive software.

## Run commands

Copy the supplied `RoboTraceOpt_x86_native_F3F4_20260729.zip` to the Ubuntu
desktop, then run:

```bash
cd ~/Desktop
unzip RoboTraceOpt_x86_native_F3F4_20260729.zip
cd RoboTraceOpt_x86_native_F3F4_20260729/RoboTraceOpt
sudo bash scripts/install_native_x86_dependencies.sh
sudo bash scripts/run_native_x86_f3_f4.sh
```

The second command builds the ROS workspace, writes a read-only capability
report, then runs 40 repetitions: F3 control/injected and F4
control/injected, each with 10 repetitions and an 8-second workload window.
It may take 10--20 minutes depending on package download and trace volume.

Do not interrupt a completed session or reuse its output directory. If the
script stops before the formal run, retain the generated capability JSON and
Markdown files; they state the missing kernel or tracing prerequisite.

## Return package

After a successful run, copy back both paths printed by the script:

```bash
cd ~/Desktop/RoboTraceOpt_x86_native_F3F4_20260729/RoboTraceOpt
tar -czf ~/Desktop/F3F4_native_x86_results.tar.gz \
  data/raw/experiments/test/native_x86_f3f4_* \
  data/raw/environment/native_x86_f3f4_*_capabilities.*
```

Send `F3F4_native_x86_results.tar.gz` to this computer. It contains no API
key because these F3/F4 experiments do not use the AI proxy.
