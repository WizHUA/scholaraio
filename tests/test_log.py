"""Tests for scholaraio.core.log — logging setup, session ID, ui()."""

from __future__ import annotations

import logging
import sys

import pytest

from scholaraio.core.config import _build_config
from scholaraio.core.log import get_logger, get_session_id, reset, setup, ui


@pytest.fixture(autouse=True)
def _reset_log():
    """Reset log module state between tests."""
    reset()
    yield
    reset()


class TestSetup:
    def test_returns_session_id(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert len(sid) == 12
        assert sid.isalnum()

    def test_idempotent(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid1 = setup(cfg)
        sid2 = setup(cfg)
        assert sid1 == sid2

    def test_creates_log_file_parent(self, tmp_path):
        cfg = _build_config(
            {"logging": {"file": "logs/deep/app.log"}},
            tmp_path,
        )
        setup(cfg)
        assert (tmp_path / "logs" / "deep").exists()

    def test_get_session_id_before_setup(self):
        assert get_session_id() == ""

    def test_get_session_id_after_setup(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert get_session_id() == sid

    def test_reconfigures_legacy_console_encoding(self, tmp_path, monkeypatch):
        class FakeStdout:
            encoding = "gbk"

            def __init__(self):
                self.text = ""
                self.reconfigured = False

            def reconfigure(self, *, encoding=None, errors=None):
                self.encoding = encoding
                self.errors = errors
                self.reconfigured = True

            def write(self, text):
                text.encode(self.encoding)
                self.text += text

            def flush(self):
                pass

        fake_stdout = FakeStdout()
        monkeypatch.setattr(sys, "stdout", fake_stdout)

        cfg = _build_config({}, tmp_path)
        setup(cfg)
        ui("Python ✓ 中文")

        assert fake_stdout.reconfigured is True
        assert "Python ✓ 中文" in fake_stdout.text

    def test_replaces_unencodable_console_text_when_reconfigure_is_unavailable(self, tmp_path, monkeypatch):
        class LegacyStdout:
            encoding = "gbk"

            def __init__(self):
                self.text = ""

            def write(self, text):
                text.encode(self.encoding)
                self.text += text
                return len(text)

            def flush(self):
                pass

        legacy_stdout = LegacyStdout()
        monkeypatch.setattr(sys, "stdout", legacy_stdout)

        cfg = _build_config({}, tmp_path)
        setup(cfg)
        ui("Python ✓ 中文")

        assert "Python ? 中文" in legacy_stdout.text


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


class TestUI:
    def test_ui_no_args(self, caplog):
        with caplog.at_level(logging.INFO, logger="scholaraio.ui"):
            ui()
        # Should not crash

    def test_ui_with_message(self, caplog):
        with caplog.at_level(logging.INFO, logger="scholaraio.ui"):
            ui("hello %s", "world")
        assert "hello world" in caplog.text

    def test_ui_custom_logger(self, caplog):
        custom = logging.getLogger("custom.test")
        with caplog.at_level(logging.INFO, logger="custom.test"):
            ui("test msg", logger=custom)
        assert "test msg" in caplog.text
