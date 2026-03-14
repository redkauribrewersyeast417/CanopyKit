from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FRAGMENTS = (
    "/Users/konradw",
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
FORBIDDEN_TRACKED_PATH_PARTS = (
    ".cursor/",
    "agent_note/",
    "__pycache__/",
    ".pytest_cache/",
    ".env",
    "logs/",
    "data/",
)
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".txt",
    ".gitignore",
}


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        REPO_ROOT / line
        for line in result.stdout.splitlines()
        if line.strip()
    )


def _tracked_text_files() -> list[Path]:
    files: list[Path] = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT)
        if rel.name == "test_public_release_hygiene.py":
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"README", "LICENSE"}:
            files.append(path)
    return files


def test_public_release_surface_avoids_forbidden_tracked_paths():
    violations: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(part in rel for part in FORBIDDEN_TRACKED_PATH_PARTS):
            violations.append(rel)
    assert violations == []


def test_public_release_surface_avoids_private_local_fragments():
    violations: list[str] = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {fragment}")
    assert violations == []
