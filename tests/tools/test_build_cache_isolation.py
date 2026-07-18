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

    def test_build_cache_is_reset_when_workspace_binding_changes(self) -> None:
        script = (ROOT / "scripts/build_core.sh").read_text(encoding="utf-8")

        self.assertIn('WORKSPACE_MARKER="${SAFE_ROOT}/workspace_root"', script)
        self.assertIn('CURRENT_WORKSPACE="$(realpath "${WORKSPACE_ROOT}")"', script)
        self.assertIn('CACHED_WORKSPACE="$(cat "${WORKSPACE_MARKER}")"', script)
        self.assertIn('[[ "${CACHED_WORKSPACE}" != "${CURRENT_WORKSPACE}" ]]', script)
        self.assertIn('rm -rf -- "${BUILD_BASE}" "${INSTALL_BASE}"', script)
        self.assertIn('printf \'%s\\n\' "${CURRENT_WORKSPACE}" > "${WORKSPACE_MARKER}"', script)


if __name__ == "__main__":
    unittest.main()
