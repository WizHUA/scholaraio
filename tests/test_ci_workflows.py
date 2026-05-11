from __future__ import annotations

from pathlib import Path

import yaml


def test_macos_semantic_smoke_workflow_runs_issue_search_commands() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/macos-semantic-smoke.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["semantic-smoke"]["steps"]

    smoke_step = next(step for step in steps if step.get("name") == "Smoke test issue-65 explore search flow")
    run_script = smoke_step["run"]

    assert "scholaraio explore embed --name issue-65-smoke" in run_script
    assert 'scholaraio explore search --name issue-65-smoke "boundary layer turbulence" --mode semantic' in run_script
    assert 'scholaraio explore search --name issue-65-smoke "boundary layer turbulence" --mode unified' in run_script
    assert 'grep -q "score:" "$SMOKE_ROOT/semantic.out"' in run_script
    assert 'grep -q "score:" "$SMOKE_ROOT/unified.out"' in run_script
    assert "分数:" not in run_script
