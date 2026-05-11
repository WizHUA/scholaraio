from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standalone_metadata_show_prints_ui_output(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
paths:
  state_root: data/state
  cache_root: data/cache
  runtime_root: data/runtime
search:
  top_k: 5
embed:
  provider: none
llm:
  api_key: null
""",
        encoding="utf-8",
    )
    md = tmp_path / "paper.md"
    md.write_text(
        "# Metadata CLI Smoke Test\n\n"
        "Alice Smith, Bob Lee\n\n"
        "Journal of Smoke Testing, 2026\n\n"
        "DOI: 10.0000/metadata-cli-smoke\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["SCHOLARAIO_CONFIG"] = str(config)

    result = subprocess.run(
        [sys.executable, "-m", "scholaraio.services.ingest_metadata", "show", str(md)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Title:" in result.stdout
    assert "Metadata CLI Smoke Test" in result.stdout
