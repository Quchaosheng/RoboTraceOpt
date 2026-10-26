"""Every published evidence package must say whether its claim can be recomputed.

A number is published while the rows behind it stay private in three of the four
packages here. That can be a legitimate boundary, but it has to be stated in the
package itself: a reader must be able to tell "check this yourself" from "trust this
aggregate" without reading the README prose and hoping the two agree.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence"
MANIFEST_NAMES = ("protocol_manifest.public.json", "PACKAGE_MANIFEST.json")
REQUIRED = ("command", "inputs", "recomputable_from_public_checkout", "reason")


def packages() -> list[Path]:
    return sorted(path for path in EVIDENCE.iterdir() if path.is_dir() and not path.name.startswith("."))


def manifest_for(package: Path) -> Path:
    for name in MANIFEST_NAMES:
        candidate = package / name
        if candidate.is_file():
            return candidate
    raise AssertionError(f"{package.name} has no recognised manifest")


class RecomputeRecordTest(unittest.TestCase):
    def test_every_package_declares_a_recompute_record(self) -> None:
        self.assertTrue(packages(), "no evidence packages found")
        for package in packages():
            with self.subTest(package=package.name):
                record = json.loads(manifest_for(package).read_text()).get("recompute")
                self.assertIsInstance(record, dict, f"{package.name} has no recompute record")
                for key in REQUIRED:
                    self.assertIn(key, record, f"{package.name} recompute is missing {key}")

    def test_a_public_recompute_claim_names_tracked_inputs(self) -> None:
        # Claiming a package is recomputable from the public checkout is the one
        # answer that must be true, because a reader will act on it.
        for package in packages():
            with self.subTest(package=package.name):
                record = json.loads(manifest_for(package).read_text())["recompute"]
                if record["recomputable_from_public_checkout"] is not True:
                    continue
                self.assertTrue(
                    (package / record["inputs"]).exists(),
                    f"{package.name} claims public recompute but {record['inputs']} is not in the package",
                )

    def test_a_private_input_says_why_it_is_private(self) -> None:
        for package in packages():
            with self.subTest(package=package.name):
                record = json.loads(manifest_for(package).read_text())["recompute"]
                if record["recomputable_from_public_checkout"] is not False:
                    continue
                self.assertTrue(
                    record["reason"].strip(),
                    f"{package.name} declares non-recomputable with no reason",
                )


if __name__ == "__main__":
    unittest.main()
