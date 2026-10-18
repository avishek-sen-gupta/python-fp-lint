# tests/test_settings.py
"""Settings arrive as layers -- one per source -- in which a scalar no source
supplied is UNSET and a collection no source supplied is empty."""

import builtins
import json

import pytest

from python_fp_lint import lint_gate
from python_fp_lint.lint_gate import ConfigError, LintGate, LintSettings
from python_fp_lint.result import LintResult
from python_fp_lint.settings import (
    UNSET,
    ConfigLayer,
    layer_from_config_file,
    resolve_settings,
)

SCALAR_KEYS = (
    "ruff_select",
    "max_complexity",
    "max_statements",
    "max_positional_args",
    "lint_rules_dir",
    "baseline",
)


def _config(directory, values):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "fp.json"
    path.write_text(json.dumps(values))
    return str(path)


class TestConfigFileLayer:
    def test_missing_keys_are_unset(self, tmp_path):
        assert layer_from_config_file(_config(tmp_path, {})) == ConfigLayer()

    def test_null_is_unset(self, tmp_path):
        path = _config(tmp_path, dict.fromkeys(SCALAR_KEYS))
        assert layer_from_config_file(path) == ConfigLayer()

    def test_values_are_carried(self, tmp_path):
        path = _config(
            tmp_path,
            {
                "ruff_select": "E,F",
                "max_statements": 20,
                "exclude": ["a/"],
                "ast_grep_rules": ["no-list-append"],
            },
        )
        assert layer_from_config_file(path) == ConfigLayer(
            ruff_select="E,F",
            max_statements=20,
            exclude=("a/",),
            ast_grep_rules=("no-list-append",),
        )

    def test_empty_ruff_select_is_unset(self, tmp_path):
        path = _config(tmp_path, {"ruff_select": ""})
        assert layer_from_config_file(path).ruff_select is UNSET

    def test_non_list_collections_are_empty(self, tmp_path):
        path = _config(tmp_path, {"exclude": "generated/"})
        assert layer_from_config_file(path).exclude == ()

    def test_relative_paths_anchor_to_the_config_dir(self, tmp_path):
        cfg = tmp_path / "cfg"
        layer = layer_from_config_file(
            _config(cfg, {"lint_rules_dir": "r", "baseline": "b.json"})
        )
        assert (layer.rules_dir, layer.baseline) == (
            str(cfg / "r"),
            str(cfg / "b.json"),
        )

    def test_absolute_paths_pass_through(self, tmp_path):
        layer = layer_from_config_file(
            _config(tmp_path, {"lint_rules_dir": "/opt/r", "baseline": "/var/b.json"})
        )
        assert (layer.rules_dir, layer.baseline) == ("/opt/r", "/var/b.json")

    @pytest.mark.parametrize("value", ["lots", -1, True])
    def test_invalid_ceiling_names_the_key(self, tmp_path, value):
        path = _config(tmp_path, {"max_statements": value})
        with pytest.raises(
            ConfigError, match="max_statements must be a non-negative integer"
        ):
            layer_from_config_file(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="config file not found"):
            layer_from_config_file(str(tmp_path / "absent.json"))

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "fp.json"
        path.write_text("{")
        with pytest.raises(ConfigError, match="cannot read config file"):
            layer_from_config_file(str(path))

    @pytest.mark.parametrize("document", [[], "x"])
    def test_non_object_top_level_is_a_config_error(self, tmp_path, document):
        path = _config(tmp_path, document)
        with pytest.raises(
            ConfigError, match=r"cannot read config file .*: expected a JSON object"
        ):
            layer_from_config_file(path)


class TestResolveSettings:
    """CLI > config file > default, per field; the result has no UNSET left."""

    def test_defaults(self, tmp_path):
        assert (
            resolve_settings(ConfigLayer(), ConfigLayer(), str(tmp_path))
            == LintSettings()
        )

    @pytest.mark.parametrize(
        ("field", "cli_value", "file_value"),
        [
            ("max_complexity", 7, 5),
            ("max_statements", 30, 20),
            ("max_positional_args", 6, 5),
            ("ruff_select", "E", "F"),
            ("exclude", ("cli/",), ("file/",)),
            ("ast_grep_rules", ("no-list-append",), ("no-set-add",)),
        ],
    )
    def test_cli_beats_file_beats_default(self, tmp_path, field, cli_value, file_value):
        file = ConfigLayer(**{field: file_value})
        both = resolve_settings(ConfigLayer(**{field: cli_value}), file, str(tmp_path))
        file_only = resolve_settings(ConfigLayer(), file, str(tmp_path))
        assert (getattr(both, field), getattr(file_only, field)) == (
            cli_value,
            file_value,
        )

    def test_empty_cli_collection_defers_to_file(self, tmp_path):
        settings = resolve_settings(
            ConfigLayer(exclude=()), ConfigLayer(exclude=("g/",)), str(tmp_path)
        )
        assert settings.exclude == ("g/",)

    def test_rules_dir_search(self, tmp_path):
        project_rules = tmp_path / "scripts" / "lint"
        before = resolve_settings(ConfigLayer(), ConfigLayer(), str(tmp_path))
        project_rules.mkdir(parents=True)
        (project_rules / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n")
        after = resolve_settings(ConfigLayer(), ConfigLayer(), str(tmp_path))
        assert (before.rules_dir, after.rules_dir) == (
            lint_gate._package_rules_dir(),
            str(project_rules),
        )

    def test_explicit_rules_dir_wins_unchecked(self, tmp_path):
        settings = resolve_settings(
            ConfigLayer(rules_dir="/nowhere"), ConfigLayer(), str(tmp_path)
        )
        assert settings.rules_dir == "/nowhere"

    def test_gate_does_not_read_config(self, tmp_path, monkeypatch):
        gate = LintGate(settings=LintSettings(rules_dir=str(tmp_path)))

        def no_files(*_args, **_kwargs):
            raise AssertionError("the gate must not open any file")

        monkeypatch.setattr(builtins, "open", no_files)
        assert gate.evaluate([], str(tmp_path)) == LintResult(
            passed=True, violations=[]
        )

    def test_missing_configured_rules_dir_falls_through(self, tmp_path):
        """A config file naming a rules dir that is not there is not trusted:
        the search moves on, rather than running no ast-grep rules at all."""
        settings = resolve_settings(
            ConfigLayer(), ConfigLayer(rules_dir=str(tmp_path / "typo")), str(tmp_path)
        )
        assert settings.rules_dir == lint_gate._package_rules_dir()


@pytest.mark.parametrize("key", ["ruff_select", "lint_rules_dir", "baseline"])
@pytest.mark.parametrize("value", [["E", "F"], 5, True])
def test_wrong_typed_text_setting_is_a_config_error(tmp_path, key, value):
    """A present value of the wrong type is a mistake to report, not a
    setting to ignore: an ignored baseline would silently leave ratchet mode."""
    path = _config(tmp_path, {key: value})
    with pytest.raises(ConfigError, match=f"{key} must be a string"):
        layer_from_config_file(path)
