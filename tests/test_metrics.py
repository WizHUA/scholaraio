"""Contract tests for LLM URL routing."""

from __future__ import annotations

import pytest

from scholaraio.metrics import _build_openai_compat_url, _supports_openai_json_mode


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/chat/completions"),
        (
            "https://ark.cn-beijing.volces.com/api/coding/v3",
            "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
        ),
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1/chat/completions",
        ),
    ],
)
def test_build_openai_compat_url(base_url: str, expected: str) -> None:
    assert _build_openai_compat_url(base_url) == expected


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.deepseek.com", True),
        ("https://api.deepseek.com/v1", True),
        ("https://ark.cn-beijing.volces.com/api/coding/v3", False),
        ("https://api.openai.com/v1/chat/completions", True),
    ],
)
def test_supports_openai_json_mode(base_url: str, expected: bool) -> None:
    assert _supports_openai_json_mode(base_url) is expected
