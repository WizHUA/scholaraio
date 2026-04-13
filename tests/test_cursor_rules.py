"""Cursor-native rule files stay present and lightweight."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cursor_project_rule_uses_native_mdc_wrapper() -> None:
    rule_path = ROOT / ".cursor" / "rules" / "scholaraio.mdc"

    assert rule_path.exists()
    content = rule_path.read_text(encoding="utf-8")

    assert content.startswith("---\n")
    assert "alwaysApply: true" in content
    assert "AGENTS.md" in content
    assert ".claude/skills/*/SKILL.md" in content
    assert "scholaraio --help" in content
    assert len(content) < 2500


def test_legacy_cursorrules_defers_to_native_project_rule() -> None:
    content = (ROOT / ".cursorrules").read_text(encoding="utf-8")

    assert ".cursor/rules/scholaraio.mdc" in content
    assert "AGENTS.md" in content
    assert len(content) < 1500


def test_cursor_support_does_not_use_mcp() -> None:
    assert not (ROOT / ".cursor" / "mcp.json").exists()
