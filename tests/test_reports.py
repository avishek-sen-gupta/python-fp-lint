# tests/test_reports.py
"""Reports render a command's output; the CLI only emits them and exits.

tests/data/report_snapshots.json holds what the CLI printed for each case
below before rendering moved into report objects -- captured by calling the
old __main__._report / _report_ratchet with the same inputs. A render must
match it byte for byte.
"""

import json
import os

import pytest

from python_fp_lint.output import OutputFormat, Stream
from python_fp_lint.ratchet import Verdict
from python_fp_lint.reports import (
    BaselineRecordedReport,
    BaselineShownReport,
    CheckReport,
    NoBaselineReport,
    RatchetReport,
)
from python_fp_lint.result import LintResult, LintViolation

SNAPSHOTS = os.path.join(os.path.dirname(__file__), "data", "report_snapshots.json")

VIOLATIONS = [
    LintViolation("r1", "a.py", 3, "msg one"),
    LintViolation("r2", "b.py", 0, "msg two"),
]
VERDICTS = {
    "regressed": Verdict(2, 4, False),
    "tightened": Verdict(4, 2, True),
    "dropped": Verdict(4, 2, False),
    "equal": Verdict(3, 3, False),
}
NO_BASELINE = (
    'error: no baseline configured; pass --baseline PATH or set "baseline" '
    "in the config file"
)


def _cases():
    """(snapshot name, report, format) for every captured case."""
    checks = [
        (f"check-{label}-{fmt.name.lower()}", CheckReport(result), fmt)
        for fmt in OutputFormat
        for label, result in (
            ("dirty", LintResult(False, VIOLATIONS)),
            ("clean", LintResult(True, [])),
        )
    ]
    ratchets = [
        (
            f"ratchet-{label}-{fmt.name.lower()}-{len(staged)}",
            RatchetReport(verdict, VIOLATIONS * 30, staged),
            fmt,
        )
        for fmt in OutputFormat
        for label, verdict in VERDICTS.items()
        for staged in (frozenset(), frozenset({"a.py"}))
    ]
    return [*checks, *ratchets]


with open(SNAPSHOTS, encoding="utf-8") as _f:
    _EXPECTED = json.load(_f)


@pytest.mark.parametrize(("name", "report", "fmt"), _cases())
def test_render_matches_the_cli_snapshot(name, report, fmt):
    assert (report.render(fmt), report.exit_code, report.stream) == (
        _EXPECTED[name]["render"],
        _EXPECTED[name]["exit"],
        Stream.STDOUT,
    )


def test_every_snapshot_is_exercised():
    assert {name for name, _report, _fmt in _cases()} == set(_EXPECTED)


class TestBaselineRecordedReport:
    REPORT = BaselineRecordedReport(total=85, path="fp-baseline.json")

    def test_text(self):
        assert (
            self.REPORT.render(OutputFormat.TEXT)
            == "baseline recorded: 85 violation(s) -> fp-baseline.json"
        )

    def test_json(self):
        assert json.loads(self.REPORT.render(OutputFormat.JSON)) == {
            "baseline": 85,
            "total": 85,
            "path": "fp-baseline.json",
        }

    def test_exit_and_stream(self):
        assert (self.REPORT.exit_code, self.REPORT.stream) == (0, Stream.STDOUT)


class TestBaselineShownReport:
    REPORT = BaselineShownReport(recorded=85, total=80, path="fp-baseline.json")

    def test_text(self):
        assert self.REPORT.render(OutputFormat.TEXT) == (
            "baseline: 85\ncurrent:  80\npath:     fp-baseline.json"
        )

    def test_json(self):
        assert json.loads(self.REPORT.render(OutputFormat.JSON)) == {
            "baseline": 85,
            "total": 80,
            "path": "fp-baseline.json",
        }

    def test_exit_and_stream(self):
        assert (self.REPORT.exit_code, self.REPORT.stream) == (0, Stream.STDOUT)


class TestNoBaselineReport:
    @pytest.mark.parametrize("fmt", list(OutputFormat))
    def test_renders_the_same_error_in_every_format(self, fmt):
        assert NoBaselineReport().render(fmt) == NO_BASELINE

    def test_exit_and_stream(self):
        report = NoBaselineReport()
        assert (report.exit_code, report.stream) == (2, Stream.STDERR)
