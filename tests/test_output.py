# tests/test_output.py
"""Output is written by emit(); diagnostics go through logging. Never print()."""

import logging
import os

import pytest

from python_fp_lint.lint_gate import LintGate, LintSettings
from python_fp_lint.output import Stream, configure_cli_logging, emit

PKG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python_fp_lint")


class TestEmit:
    def test_writes_a_line_to_stdout_by_default(self, capsys):
        emit("hello")
        assert capsys.readouterr() == ("hello\n", "")

    def test_writes_to_stderr_when_asked(self, capsys):
        emit("oops", Stream.STDERR)
        assert capsys.readouterr() == ("", "oops\n")

    def test_no_argument_is_a_blank_line(self, capsys):
        emit()
        assert capsys.readouterr() == ("\n", "")


class TestCliLogging:
    @pytest.fixture(autouse=True)
    def _restore_logger(self):
        logger = logging.getLogger("python_fp_lint")
        saved = (list(logger.handlers), logger.propagate, logger.level)
        yield
        logger.handlers, logger.propagate, logger.level = saved[0], *saved[1:]

    def test_error_is_the_bare_message_on_stderr(self, capsys):
        configure_cli_logging()
        logging.getLogger("python_fp_lint").error("error: bad config")
        assert capsys.readouterr() == ("", "error: bad config\n")

    def test_configuring_twice_does_not_duplicate_lines(self, capsys):
        configure_cli_logging()
        configure_cli_logging()
        logging.getLogger("python_fp_lint.sub").error("once")
        assert capsys.readouterr().err == "once\n"


class TestNoPrintInThePackage:
    def test_package_has_no_print_calls(self, tmp_path):
        gate = LintGate(settings=LintSettings(ruff_select="T20"))
        files = [
            os.path.join(PKG_DIR, f)
            for f in ("__main__.py", "hook_check.py", "output.py")
        ]
        result = gate.evaluate(files, str(tmp_path))
        prints = [(v.file, v.line) for v in result.violations if v.rule == "T201"]
        assert prints == []
