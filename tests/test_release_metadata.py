from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT = (REPO_ROOT / "canopykit" / "__init__.py").read_text(encoding="utf-8")


def _package_version() -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', INIT, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_package_version_matches_pyproject() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1) == _package_version()


def test_changelog_has_current_release_heading() -> None:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{_package_version()}]" in changelog


def test_release_scaffolding_exists() -> None:
    assert (REPO_ROOT / "LICENSE").exists()
    assert (REPO_ROOT / ".github" / "workflows" / "ci.yml").exists()
    assert (REPO_ROOT / "docs" / f"GITHUB_RELEASE_v{_package_version()}.md").exists()
