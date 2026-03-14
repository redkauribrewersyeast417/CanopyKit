"""Closed-world artifact validation for CanopyKit.

This validator intentionally stays narrow:
- validate only exact structured block syntax that CanopyKit controls
- validate only deterministic completion-evidence presence

Semantic correctness is out of scope here and should remain at the
schema-constrained model layer.
"""

from __future__ import annotations

import re
from typing import Final

CANOPY_BLOCK_NAMES: Final[frozenset[str]] = frozenset(
    {
        "circle",
        "completion",
        "contract",
        "error",
        "evidence",
        "files_changed",
        "handoff",
        "notes",
        "objective",
        "plan",
        "request",
        "result",
        "signal",
        "skill",
        "summary",
        "task",
    }
)

TERMINAL_EVIDENCE_BLOCKS: Final[frozenset[str]] = frozenset(
    {"completion", "evidence", "result", "summary"}
)

BLOCK_TAG_RE: Final[re.Pattern[str]] = re.compile(r"\[(/)?([A-Za-z][A-Za-z0-9_-]*)\]")

EVIDENCE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(
        rf"\[{re.escape(block)}\](.*?)\[/{re.escape(block)}\]",
        re.DOTALL | re.IGNORECASE,
    )
    for block in TERMINAL_EVIDENCE_BLOCKS
)


class CanopyArtifactValidator:
    """Concrete ArtifactValidator for deterministic structural checks."""

    def validate(self, content: str) -> tuple[bool, list[str]]:
        errors: list[str] = []
        self._check_block_names(content, errors)
        self._check_completion_evidence(content, errors)
        return len(errors) == 0, errors

    def _check_block_names(self, content: str, errors: list[str]) -> None:
        unknown_seen: set[str] = set()
        for match in BLOCK_TAG_RE.finditer(content):
            name = match.group(2).lower()
            if name not in CANOPY_BLOCK_NAMES and name not in unknown_seen:
                unknown_seen.add(name)
                errors.append(
                    f"Unknown structured block '[{name}]'; valid names are: {sorted(CANOPY_BLOCK_NAMES)}"
                )

    def _check_completion_evidence(self, content: str, errors: list[str]) -> None:
        lowered = content.lower()
        if "[completion]" not in lowered:
            return

        for pattern in EVIDENCE_PATTERNS:
            match = pattern.search(content)
            if match and match.group(1).strip():
                return

        errors.append(
            "Terminal success artifact is missing completion evidence; include non-empty "
            "[completion], [summary], [result], or [evidence] content"
        )


__all__ = [
    "CANOPY_BLOCK_NAMES",
    "TERMINAL_EVIDENCE_BLOCKS",
    "CanopyArtifactValidator",
]
