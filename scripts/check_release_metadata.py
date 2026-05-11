from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


@dataclass(frozen=True)
class ReleaseMetadata:
    tag_version: str
    base_version: str
    pyproject_version: str
    runtime_version: str | None
    citation_version: str | None
    is_prerelease: bool
    prerelease_label: str


def read_release_metadata(root: Path, ref_name: str) -> ReleaseMetadata:
    tag_version = ref_name.removeprefix("v")
    base_version, separator, prerelease_label = tag_version.partition("-")
    pyproject_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

    init_text = (root / "scholaraio" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)

    cff_text = (root / "CITATION.cff").read_text(encoding="utf-8")
    cff_match = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', cff_text, re.MULTILINE)

    return ReleaseMetadata(
        tag_version=tag_version,
        base_version=base_version,
        pyproject_version=pyproject_version,
        runtime_version=init_match.group(1) if init_match else None,
        citation_version=cff_match.group(1).strip() if cff_match else None,
        is_prerelease=bool(separator),
        prerelease_label=prerelease_label,
    )


def validate_release_metadata(metadata: ReleaseMetadata) -> None:
    versions = {
        "tag": metadata.base_version,
        "pyproject": metadata.pyproject_version,
        "runtime": metadata.runtime_version,
        "citation": metadata.citation_version,
    }
    mismatches = [f"{name}={value}" for name, value in versions.items() if value != metadata.pyproject_version]
    if mismatches:
        raise SystemExit(
            "Release metadata mismatch detected. Expected all versions to equal "
            f"{metadata.pyproject_version}, got: {', '.join(mismatches)}"
        )


def write_github_outputs(metadata: ReleaseMetadata, output_path: str | None) -> None:
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write(f"is_prerelease={'true' if metadata.is_prerelease else 'false'}\n")
        fh.write(f"tag_version={metadata.tag_version}\n")
        fh.write(f"base_version={metadata.base_version}\n")


def main() -> None:
    metadata = read_release_metadata(Path("."), os.environ["GITHUB_REF_NAME"])
    validate_release_metadata(metadata)
    write_github_outputs(metadata, os.environ.get("GITHUB_OUTPUT"))

    if metadata.is_prerelease:
        print(
            f"Prerelease tag {metadata.tag_version} aligned with base package version "
            f"{metadata.pyproject_version} ({metadata.prerelease_label})"
        )
    else:
        print(f"Release metadata aligned at version {metadata.pyproject_version}")


if __name__ == "__main__":
    main()
