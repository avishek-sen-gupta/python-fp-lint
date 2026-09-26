# tests/test_baseline.py
"""The ratchet's baseline file and its path resolution."""

import json

import pytest

from python_fp_lint import baseline
from python_fp_lint.lint_gate import LintGate


class TestReadWrite:
    def test_round_trips(self, tmp_path):
        path = str(tmp_path / "fp-baseline.json")
        baseline.write(path, 4312)
        assert baseline.read(path) == 4312

    def test_writes_exactly_the_total_and_a_newline(self, tmp_path):
        path = tmp_path / "fp-baseline.json"
        baseline.write(str(path), 7)
        assert path.read_text() == '{"total": 7}\n'

    def test_zero_is_a_valid_total(self, tmp_path):
        path = str(tmp_path / "b.json")
        baseline.write(path, 0)
        assert baseline.read(path) == 0


class TestReadRejectsBadFiles:
    """Review Focus 1 and 2: a bad baseline must never parse as zero."""

    def test_missing_file_names_the_fix(self, tmp_path):
        path = str(tmp_path / "absent.json")
        with pytest.raises(baseline.BaselineError, match="baseline update"):
            baseline.read(path)

    def test_merge_conflict_markers_raise(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(
            '<<<<<<< HEAD\n{"total": 10}\n=======\n{"total": 12}\n>>>>>>> x\n'
        )
        with pytest.raises(baseline.BaselineError, match="cannot read"):
            baseline.read(str(path))

    def test_truncated_json_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text('{"total":')
        with pytest.raises(baseline.BaselineError, match="cannot read"):
            baseline.read(str(path))

    def test_json_list_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_missing_total_key_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"count": 5}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_string_total_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": "4312"}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_negative_total_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": -1}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_bool_total_raises(self, tmp_path):
        """`True` is an int in Python. It is not a violation count."""
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": True}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))


class TestResolvePath:
    def test_no_config_value_means_no_ratchet(self):
        assert baseline.resolve_path(None, None, "/proj/fp.json") is None

    def test_cli_value_wins(self):
        assert (
            baseline.resolve_path("/tmp/cli.json", "cfg.json", "/proj/fp.json")
            == "/tmp/cli.json"
        )

    def test_cli_value_wins_even_with_no_config_key(self):
        assert baseline.resolve_path("/tmp/cli.json", None, None) == "/tmp/cli.json"

    def test_relative_config_value_resolves_against_the_config_file(self):
        assert (
            baseline.resolve_path(None, "fp-baseline.json", "/proj/cfg/fp.json")
            == "/proj/cfg/fp-baseline.json"
        )

    def test_absolute_config_value_is_left_alone(self):
        assert (
            baseline.resolve_path(None, "/var/b.json", "/proj/fp.json") == "/var/b.json"
        )


class TestGateResolution:
    def test_constructor_beats_config_file(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text(json.dumps({"baseline": "from-config.json"}))
        gate = LintGate(config_path=str(cfg), baseline="/tmp/from-ctor.json")
        assert gate.resolve_baseline() == "/tmp/from-ctor.json"

    def test_falls_back_to_config_file(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text(json.dumps({"baseline": "b.json"}))
        gate = LintGate(config_path=str(cfg))
        assert gate.resolve_baseline() == str(tmp_path / "b.json")

    def test_none_when_nothing_configured(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text("{}")
        assert LintGate(config_path=str(cfg)).resolve_baseline() is None
