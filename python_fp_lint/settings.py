# python_fp_lint/settings.py
"""Settings, from the sources that supply them to the values the gate runs on.

Each source -- the config file, the command line -- is read by an adapter into
a ConfigLayer: what that one source said. A scalar it did not say is UNSET; a
collection it did not say is empty. UNSET never leaves this module's layers.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeVar

from python_fp_lint.lint_gate import (
    _DEFAULT_MAX_COMPLEXITY,
    _DEFAULT_MAX_POSITIONAL_ARGS,
    _DEFAULT_MAX_STATEMENTS,
    _DEFAULT_RUFF_SELECT,
    ConfigError,
    LintSettings,
    _package_rules_dir,
    _validate_ceiling,
)

T = TypeVar("T")


class Unset(Enum):
    """The one value meaning "this source did not supply the setting"."""

    UNSET = auto()


UNSET = Unset.UNSET


@dataclass(frozen=True)
class ConfigLayer:
    """What one source said. Anything it did not say is UNSET or empty."""

    ruff_select: str | Unset = UNSET
    ast_grep_rules: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    max_complexity: int | Unset = UNSET
    max_statements: int | Unset = UNSET
    max_positional_args: int | Unset = UNSET
    rules_dir: str | Unset = UNSET
    baseline: str | Unset = UNSET


def layer_from_config_file(path: str) -> ConfigLayer:
    """The config file as a layer. Relative paths in it are relative to the
    file itself, so a config can be checked in beside what it names."""
    data = _as_object(_read_json(path), path)
    base = os.path.dirname(os.path.abspath(path))
    return ConfigLayer(
        ruff_select=_text(data.get("ruff_select")),
        ast_grep_rules=_strings(data.get("ast_grep_rules")),
        exclude=_strings(data.get("exclude")),
        max_complexity=_ceiling(data, "max_complexity"),
        max_statements=_ceiling(data, "max_statements"),
        max_positional_args=_ceiling(data, "max_positional_args"),
        rules_dir=_anchored(data.get("lint_rules_dir"), base),
        baseline=_anchored(data.get("baseline"), base),
    )


def _read_json(path: str):
    if not os.path.exists(path):
        raise ConfigError(f"config file not found: {path}")
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc


def _as_object(document, path: str) -> dict:
    """The document's keys, with JSON nulls dropped.

    A null and a missing key both mean "not given". Dropping nulls here is the
    only place JSON's None is looked at; past this point a key is either
    present with a value or absent.
    """
    if not isinstance(document, dict):
        raise ConfigError(f"cannot read config file {path}: expected a JSON object")
    return {key: value for key, value in document.items() if value is not None}


def _ceiling(data: Mapping, key: str) -> int | Unset:
    return _validate_ceiling(key, data[key]) if key in data else UNSET


def _text(value) -> str | Unset:
    return value if isinstance(value, str) and value else UNSET


def _strings(value) -> tuple[str, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _anchored(value, base: str) -> str | Unset:
    # os.path.join leaves an absolute value as it is.
    return os.path.join(base, value) if isinstance(value, str) and value else UNSET


def resolve_settings(
    cli: ConfigLayer, file: ConfigLayer, project_root: str
) -> LintSettings:
    """The settings in force: per field, the command line, else the config file,
    else the built-in default. No UNSET survives this."""
    return LintSettings(
        ruff_select=_first(cli.ruff_select, file.ruff_select, _DEFAULT_RUFF_SELECT),
        ast_grep_rules=cli.ast_grep_rules or file.ast_grep_rules,
        exclude=cli.exclude or file.exclude,
        max_complexity=_first(
            cli.max_complexity, file.max_complexity, _DEFAULT_MAX_COMPLEXITY
        ),
        max_statements=_first(
            cli.max_statements, file.max_statements, _DEFAULT_MAX_STATEMENTS
        ),
        max_positional_args=_first(
            cli.max_positional_args,
            file.max_positional_args,
            _DEFAULT_MAX_POSITIONAL_ARGS,
        ),
        rules_dir=_rules_dir(cli, file, project_root),
    )


def load_settings(config_path: str, project_root: str = ".") -> LintSettings:
    """The settings a config file asks for, with nothing overridden."""
    return resolve_settings(
        ConfigLayer(), layer_from_config_file(config_path), project_root
    )


def _first(cli: T | Unset, file: T | Unset, default: T) -> T:
    """The first value a source supplied, else the default."""
    return next((value for value in (cli, file) if value is not UNSET), default)


def _rules_dir(cli: ConfigLayer, file: ConfigLayer, project_root: str) -> str:
    """A rules dir given directly is used as given. Otherwise the first of the
    config file's lint_rules_dir and <project_root>/scripts/lint that holds an
    sgconfig.yml, else the package's own rules -- which always do. The config
    file outranks the package copy deliberately: the package copy always
    exists, so anything below it in the order could never win."""
    match cli.rules_dir:
        case str(explicit):
            return explicit
        case Unset.UNSET:
            return _search_rules_dir(file.rules_dir, project_root)


def _search_rules_dir(configured: str | Unset, project_root: str) -> str:
    candidates = [
        *([configured] if isinstance(configured, str) else []),
        os.path.join(project_root, "scripts", "lint"),
    ]
    return next((c for c in candidates if _is_rules_dir(c)), _package_rules_dir())


def _is_rules_dir(path: str) -> bool:
    return os.path.isdir(path) and os.path.exists(os.path.join(path, "sgconfig.yml"))
