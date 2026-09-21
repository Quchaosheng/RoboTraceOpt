import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

UNAVAILABLE_REPOSITORIES = (
    "ROS2Probe",
    "RoboTraceRT",
)

DOCS_WITH_LINEAGE_CLAIM = (
    "README.md",
    "README.zh-CN.md",
)


def tracked_markdown_files() -> list[Path]:
    """Markdown files whose links are published as public claims."""
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not set(path.relative_to(ROOT).parts) & {".git", "build", "install"}
    )


class PublicDocsLinksTest(unittest.TestCase):
    def test_public_docs_do_not_link_to_unavailable_repositories(self) -> None:
        for path in tracked_markdown_files():
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            for repository in UNAVAILABLE_REPOSITORIES:
                needle = f"github.com/Quchaosheng/{repository}"
                with self.subTest(relative=relative):
                    self.assertNotIn(needle, text)

    def test_lineage_sections_state_that_sources_are_unavailable(self) -> None:
        for relative in DOCS_WITH_LINEAGE_CLAIM:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for repository in UNAVAILABLE_REPOSITORIES:
                with self.subTest(relative=relative, repository=repository):
                    self.assertIn(f"`{repository}`", text)
        self.assertIn(
            "no longer publicly available",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "不再公开",
            (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
        )

    def test_both_readmes_document_the_license(self) -> None:
        self.assertIn(
            "## License",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "## 许可证",
            (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
