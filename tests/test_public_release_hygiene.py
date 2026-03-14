from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_GLOBS = (
    "README.md",
    "pyproject.toml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/**/*.md",
    "examples/**/*.json",
    "tests/**/*.py",
    "canopykit/**/*.py",
)
FORBIDDEN_FRAGMENTS = (
    "/Users/konradwalus",
    "ClawPack",
    "CanopyClaw",
    "canopyclaw",
    "docs/CANOPYCLAW_",
    "CANOPYCLAW_IMPLEMENTATION_QUEUE",
    "CANOPYCLAW_OVERNIGHT_STATUS",
    "codex_agent_api_key",
    "Forge_McClaw",
    "Goose_McClaw",
    "forge_mcclaw",
    "user_forge",
    "user_goose",
    "Mo_Money",
    "Asmon_McClaw",
    "ClawBOT",
    "Clawski",
    "Maddog",
    "Codex_Agent",
    "http://127.0.0.1:7770",
    "https://github.com/kwalus/CanopyClaw",
)


def _tracked_public_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SCAN_GLOBS:
        files.extend(path for path in REPO_ROOT.glob(pattern) if path.is_file())
    return sorted(path for path in set(files) if path.name != "test_public_release_hygiene.py")


def test_public_release_surface_avoids_private_local_fragments():
    violations: list[str] = []
    for path in _tracked_public_files():
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {fragment}")
    assert violations == []
