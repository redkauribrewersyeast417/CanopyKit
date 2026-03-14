from __future__ import annotations

from canopykit.artifact_validator import CanopyArtifactValidator


def test_plain_text_is_valid():
    validator = CanopyArtifactValidator()
    is_valid, errors = validator.validate("plain text")
    assert is_valid is True
    assert errors == []


def test_known_canopy_blocks_are_valid():
    validator = CanopyArtifactValidator()
    is_valid, errors = validator.validate("[signal]\nhello\n[/signal]")
    assert is_valid is True
    assert errors == []


def test_unknown_block_is_rejected():
    validator = CanopyArtifactValidator()
    is_valid, errors = validator.validate("[bogus]\nhello\n[/bogus]")
    assert is_valid is False
    assert any("bogus" in error for error in errors)


def test_completion_requires_nonempty_evidence():
    validator = CanopyArtifactValidator()
    is_valid, errors = validator.validate("[completion]\n   \n[/completion]")
    assert is_valid is False
    assert any("completion evidence" in error.lower() for error in errors)


def test_summary_can_satisfy_completion_evidence():
    validator = CanopyArtifactValidator()
    is_valid, errors = validator.validate(
        "[completion][/completion]\n[summary]\ncompleted with proof\n[/summary]"
    )
    assert is_valid is True
    assert errors == []
