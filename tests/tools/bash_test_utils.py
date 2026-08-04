import shutil
import subprocess
from pathlib import Path


def find_working_bash() -> str | None:
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        resolved = str(Path(candidate))
        if resolved in seen or not Path(resolved).is_file():
            continue
        seen.add(resolved)
        try:
            result = subprocess.run(
                [resolved, "--version"],
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return resolved
    return None
