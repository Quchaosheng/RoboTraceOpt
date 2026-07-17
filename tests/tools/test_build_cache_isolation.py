import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BuildCacheIsolationTest(unittest.TestCase):
    def test_public_repository_uses_its_own_default_build_cache(self) -> None:
        for relative in (
            "scripts/build_core.sh",
            "scripts/run_smoke_workload.sh",
            "scripts/run_ros2_tracing_smoke.sh",
            "scripts/run_fault_condition.py",
            "scripts/run_optimization_trial.py",
            "README.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("robotraceopt_build", text)
                self.assertNotIn("robotracert_fusion_build", text)


if __name__ == "__main__":
    unittest.main()
