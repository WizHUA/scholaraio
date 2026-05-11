from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_release_metadata import (
    ReleaseMetadata,
    read_release_metadata,
    validate_release_metadata,
    write_github_outputs,
)


def test_release_metadata_accepts_exact_release_tag() -> None:
    metadata = read_release_metadata(root=Path("."), ref_name="v1.4.0")

    validate_release_metadata(metadata)

    assert metadata.is_prerelease is False
    assert metadata.base_version == "1.4.0"


def test_release_metadata_accepts_prerelease_tag_with_current_base_version(tmp_path) -> None:
    metadata = read_release_metadata(root=Path("."), ref_name="v1.4.0-beta.1")
    output = tmp_path / "github-output.txt"

    validate_release_metadata(metadata)
    write_github_outputs(metadata, str(output))

    assert metadata.is_prerelease is True
    assert metadata.base_version == "1.4.0"
    assert metadata.prerelease_label == "beta.1"
    assert "is_prerelease=true" in output.read_text(encoding="utf-8")


def test_release_metadata_rejects_wrong_base_tag_version() -> None:
    metadata = ReleaseMetadata(
        tag_version="1.5.0-beta.1",
        base_version="1.5.0",
        pyproject_version="1.4.0",
        runtime_version="1.4.0",
        citation_version="1.4.0",
        is_prerelease=True,
        prerelease_label="beta.1",
    )

    with pytest.raises(SystemExit, match=r"tag=1\.5\.0"):
        validate_release_metadata(metadata)
