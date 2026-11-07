import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence"


def packages():
    return sorted(path for path in EVIDENCE.iterdir() if path.is_dir())


def entries(manifest: Path) -> list[tuple[str, str]]:
    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        rows.append((digest, name))
    return rows


class EvidenceChecksumTest(unittest.TestCase):
    def test_every_public_package_has_a_manifest(self) -> None:
        for package in packages():
            with self.subTest(package=package.name):
                self.assertTrue((package / "SHA256SUMS.txt").is_file())

    def test_every_entry_matches_the_committed_file(self) -> None:
        for package in packages():
            manifest = package / "SHA256SUMS.txt"
            for digest, name in entries(manifest):
                with self.subTest(package=package.name, file=name):
                    actual = hashlib.sha256((package / name).read_bytes()).hexdigest()
                    self.assertEqual(actual, digest, f"{package.name}/{name} is stale")

    def test_manifest_covers_every_file_exactly_once(self) -> None:
        for package in packages():
            listed = [name for _, name in entries(package / "SHA256SUMS.txt")]
            self.assertEqual(
                len(listed), len(set(listed)), f"{package.name} lists a file twice"
            )
            committed = sorted(
                str(path.relative_to(package)).replace("\\", "/")
                for path in package.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS.txt"
            )
            self.assertEqual(
                sorted(listed),
                committed,
                f"{package.name} manifest does not match the committed files",
            )

    def test_manifest_rejects_escaping_paths(self) -> None:
        for package in packages():
            for _, name in entries(package / "SHA256SUMS.txt"):
                with self.subTest(package=package.name, file=name):
                    self.assertFalse(name.startswith("/"), "absolute path")
                    self.assertNotIn("..", Path(name).parts, "path escapes the package")


if __name__ == "__main__":
    unittest.main()
