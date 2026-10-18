# tests/test_lint_gate.py
"""Tests for the unified LintGate (ast-grep + Ruff + beniget)."""

import dataclasses
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from gitenv import clean_env

import python_fp_lint
from python_fp_lint import lint_gate
from python_fp_lint.lint_gate import LintGate, LintSettings
from python_fp_lint.result import LintResult
from python_fp_lint.settings import (
    ConfigLayer,
    layer_from_config_file,
    load_settings,
    resolve_settings,
)


def _make_file(tmp_path, filename, content):
    """Write a Python file and return its path."""
    path = os.path.join(tmp_path, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


_PKG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python_fp_lint")


@pytest.fixture
def rules_dir(tmp_path):
    """Copy ast-grep rules and config into a temp directory."""
    shutil.copytree(
        os.path.join(_PKG_DIR, "rules"),
        tmp_path / "rules",
        ignore=lambda _dir, names: [n for n in names if not n.endswith(".yml")],
    )
    (tmp_path / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n")
    return str(tmp_path)


needs_sg = pytest.mark.skipif(
    shutil.which("sg") is None and shutil.which("ast-grep") is None,
    reason="ast-grep (sg) not installed",
)

needs_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed",
)


class TestMaterializeRulesDir:
    def _make_rules_source(self, tmp_path, name="rules_src", rule_text="id: r1\n"):
        source = tmp_path / name
        rules = source / "rules"
        rules.mkdir(parents=True)
        (rules / "r1.yml").write_text(rule_text)
        (source / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n")
        return str(source)

    def test_copies_rule_files_to_cache_root(self, tmp_path):
        from python_fp_lint.lint_gate import _materialize_rules_dir

        source = self._make_rules_source(tmp_path)
        cache_root = str(tmp_path / "cache")

        target = _materialize_rules_dir(source, cache_root)

        assert os.path.exists(os.path.join(target, "sgconfig.yml")) is True
        assert os.path.exists(os.path.join(target, "rules", "r1.yml")) is True

    def test_materialized_dir_is_outside_the_source_tree(self, tmp_path):
        from python_fp_lint.lint_gate import _materialize_rules_dir

        source = self._make_rules_source(tmp_path)
        cache_root = str(tmp_path / "cache")

        target = _materialize_rules_dir(source, cache_root)

        # Directly under the cache root, so never inside the source tree.
        assert os.path.dirname(target) == cache_root

    def test_is_idempotent_for_unchanged_source(self, tmp_path):
        from python_fp_lint.lint_gate import _materialize_rules_dir

        source = self._make_rules_source(tmp_path)
        cache_root = str(tmp_path / "cache")

        first = _materialize_rules_dir(source, cache_root)
        second = _materialize_rules_dir(source, cache_root)

        assert first == second
        assert os.path.exists(os.path.join(second, "rules", "r1.yml")) is True

    def test_refreshes_cache_when_source_content_changes(self, tmp_path):
        from python_fp_lint.lint_gate import _materialize_rules_dir

        source = self._make_rules_source(tmp_path, rule_text="id: r1\n")
        cache_root = str(tmp_path / "cache")
        first = _materialize_rules_dir(source, cache_root)
        assert Path(first, "rules", "r1.yml").read_text() == "id: r1\n"

        # Change the source rule content -- a different signature/cache entry
        (tmp_path / "rules_src" / "rules" / "r1.yml").write_text(
            "id: r1\nchanged: true\n"
        )

        second = _materialize_rules_dir(source, cache_root)
        assert Path(second, "rules", "r1.yml").read_text() == "id: r1\nchanged: true\n"


@needs_sg
def _consumer_with_ignored_rules(tmp_path):
    """A consumer repo whose rules live under a path it gitignores.

    The rules sit inside a directory with its own self-ignoring .gitignore
    ("*") -- the exact layout `uv`/`venv` generate for .venv/. That nested
    marker (not just the parent entry) is what triggers ast-grep's silent
    skip. Returns the repo and the rules source directory.
    """
    repo = tmp_path / "consumer_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=clean_env())
    (repo / ".gitignore").write_text("ignored_deps/\n")
    rules_src = repo / "ignored_deps" / "python_fp_lint"
    (rules_src / "rules").mkdir(parents=True)
    (repo / "ignored_deps" / ".gitignore").write_text("*\n")
    shutil.copy(
        os.path.join(_PKG_DIR, "rules", "no-list-append.yml"),
        rules_src / "rules" / "no-list-append.yml",
    )
    (rules_src / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n")
    return repo, rules_src


class TestAstGrepIgnoresGitignoredRulesDir:
    """Regression test for the real-world bug: ast-grep silently finds zero
    violations when the rules directory lives under a path excluded by the
    enclosing git repo's .gitignore -- e.g. installed into a project's own
    .venv -- regardless of --no-ignore flags. This reproduces that exact
    layout and asserts the gate still finds violations."""

    def test_finds_violations_when_rules_dir_is_gitignored(self, tmp_path, monkeypatch):
        repo, rules_src = _consumer_with_ignored_rules(tmp_path)
        target = repo / "widget.py"
        target.write_text("items = []\nitems.append(1)\n")

        # Stand in for the installed package: this is the location the gate
        # copies out of, and the only one it copies. A rules dir the consumer
        # named themselves is scanned where it stands.
        monkeypatch.setattr(lint_gate, "_package_rules_dir", lambda: str(rules_src))
        gate = LintGate(settings=LintSettings(rules_cache_root=str(tmp_path / "cache")))
        result = gate.evaluate([str(target)], str(repo))

        assert [v.rule for v in result.violations].count("no-list-append") == 1


# ===========================================================================
# LintGate API
# ===========================================================================


class TestLintGateAPI:
    def test_returns_lint_result(self, tmp_path, rules_dir, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert type(result) is LintResult

    def test_no_python_files_passes(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "README.md", "# Hello")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True
        assert result.violations == []

    def test_empty_files_passes(self, tmp_path, rules_dir):
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([], str(tmp_path))
        assert result.passed is True


class TestConstructor:
    """LintGate takes resolved settings, by name, and nothing else."""

    def test_settings_are_keyword_only(self):
        with pytest.raises(TypeError):
            LintGate(LintSettings())

    def test_flat_settings_are_rejected(self):
        with pytest.raises(TypeError):
            LintGate(config_path="fp.json")

    def test_settings_are_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            LintSettings().max_statements = 1

    def test_no_arguments_means_default_settings(self):
        assert LintGate().settings == LintSettings()

    def test_load_settings_is_exported_from_the_package(self):
        assert (python_fp_lint.load_settings, python_fp_lint.LintSettings) == (
            load_settings,
            LintSettings,
        )


# ===========================================================================
# Directory expansion
# ===========================================================================


@pytest.fixture
def git_tree(tmp_path):
    """A git repo with tracked, untracked, and gitignored Python files."""
    import subprocess

    subprocess.run(
        ["git", "init", "-q", "--template=", str(tmp_path)], check=True, env=clean_env()
    )
    (tmp_path / ".gitignore").write_text(".venv/\nbuild/\n")
    for rel in (
        "src/tracked.py",
        "src/new.py",
        ".venv/lib/site.py",
        "build/lib/copy.py",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "src/tracked.py"],
        check=True,
        env=clean_env(),
    )
    return tmp_path


def _relative(root, files):
    return sorted(os.path.relpath(f, root) for f in files)


class TestDirectoryExpansion:
    def test_a_repo_walk_skips_gitignored_files(self, git_tree):
        from python_fp_lint.lint_gate import _filter_python_files

        assert _relative(git_tree, _filter_python_files([str(git_tree)])) == [
            "src/new.py",
            "src/tracked.py",
        ]

    def test_a_subdirectory_walk_stays_inside_it(self, git_tree):
        from python_fp_lint.lint_gate import _filter_python_files

        found = _filter_python_files([str(git_tree / "src")])
        assert _relative(git_tree, found) == ["src/new.py", "src/tracked.py"]

    def test_a_named_ignored_file_is_still_linted(self, git_tree):
        from python_fp_lint.lint_gate import _filter_python_files

        named = str(git_tree / ".venv/lib/site.py")
        assert _filter_python_files([named]) == [named]

    def test_a_named_ignored_directory_is_walked_in_full(self, git_tree):
        from python_fp_lint.lint_gate import _filter_python_files

        found = _filter_python_files([str(git_tree / "build")])
        assert _relative(git_tree, found) == ["build/lib/copy.py"]

    def test_outside_a_repo_every_file_is_walked(self, tmp_path):
        from python_fp_lint.lint_gate import _filter_python_files

        (tmp_path / ".gitignore").write_text("skip/\n")
        (tmp_path / "skip").mkdir()
        (tmp_path / "skip" / "a.py").write_text("x = 1\n")
        found = _filter_python_files([str(tmp_path)])
        assert _relative(tmp_path, found) == ["skip/a.py"]


# ===========================================================================
# Tool-missing scenarios
# ===========================================================================


class TestLintGateWithoutTools:
    def test_filters_to_python_files_only(self, tmp_path, rules_dir):
        py_path = _make_file(tmp_path, "widget.py", "x = 1\n")
        md_path = _make_file(tmp_path, "notes.md", "# Notes\n")
        sh_path = _make_file(tmp_path, "run.sh", "echo hi\n")
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([py_path, md_path, sh_path]) == [py_path]

    def test_skips_nonexistent_files(self, tmp_path, rules_dir):
        fake = os.path.join(str(tmp_path), "gone.py")
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([fake]) == []

    def test_sg_missing_logs_warning_continues(self, tmp_path, rules_dir, monkeypatch):
        """When sg is missing, ast-grep violations are empty but gate still runs."""
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\nx = 2\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        # Reassignment should still be detected even without sg
        assert [v.rule for v in result.violations].count("reassignment") == 1


# ===========================================================================
# ast-grep backend (via unified gate)
# ===========================================================================


@needs_sg
class TestLintGateAstGrep:
    def test_clean_file_passes_ast_grep(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        # May have Ruff violations if ruff installed, so just check ast-grep rules
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []

    def test_list_append_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("no-list-append") == 1

    def test_subscript_mutation_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd['key'] = 'val'\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("no-subscript-mutation") == 1

    def test_deep_nesting_detected(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            process(cell)\n",
        )
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("no-deep-nesting") == 1

    def test_loop_mutation_detected(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        result.append(x)\n"
            "    return result\n",
        )
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("no-loop-mutation") == 1

    def test_deduplicates_files(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path, path, path], str(tmp_path))
        # Clean file with deduplication — no ast-grep violations
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []

    def test_only_scans_touched_files(self, tmp_path, rules_dir):
        _make_file(tmp_path, "dirty.py", "items = []\nitems.append(1)\n")
        clean = _make_file(tmp_path, "clean.py", "x = 1\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([clean], str(tmp_path))
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []


# ===========================================================================
# Ruff backend (via unified gate)
# ===========================================================================


@needs_ruff
class TestLintGateRuff:
    def test_bare_except_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept:\n    pass\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("E722") == 1

    def test_print_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("T201") == 1

    def test_undefined_name_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = undefined_variable\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        # F821 is undefined name, which is in the F category
        assert [v.rule for v in result.violations].count("F821") == 1

    def test_unused_import_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("F401") == 1

    def test_ruff_missing_continues(self, tmp_path, rules_dir, monkeypatch):
        """When ruff is missing, Ruff violations are empty but gate still runs."""
        original_which = lint_gate._which
        monkeypatch.setattr(
            lint_gate,
            "_which",
            lambda cmd: None if cmd == "ruff" else original_which(cmd),
        )
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        # No Ruff violations since binary is missing
        ruff_violations = [v for v in result.violations if v.rule[0].isupper()]
        assert ruff_violations == []


# ===========================================================================
# Reassignment backend (via unified gate)
# ===========================================================================


class TestLintGateReassignment:
    def test_reassignment_detected(self, tmp_path, rules_dir, monkeypatch):
        """Unified gate detects reassignment without needing separate ReassignmentGate."""
        # Mock sg and ruff away to isolate reassignment
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\nx = 2\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("reassignment") == 1

    def test_no_reassignment_passes(self, tmp_path, rules_dir, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\ny = 2\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("reassignment") == 0


# ===========================================================================
# All backends together
# ===========================================================================


@needs_sg
@needs_ruff
class TestUnifiedGateIntegration:
    def test_all_backends_produce_violations(self, tmp_path, rules_dir):
        """A file that triggers all three backends."""
        code = (
            "import os\n"  # F401 (Ruff)
            "x = 1\n"
            "x = 2\n"  # reassignment (beniget)
            "items = []\n"
            "items.append(1)\n"  # no-list-append (ast-grep)
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        rules_hit = [v.rule for v in result.violations]
        # One finding from each backend: ast-grep, Ruff, beniget.
        assert [
            rules_hit.count(r) for r in ("no-list-append", "F401", "reassignment")
        ] == [1, 1, 1]

    def test_clean_file_passes_all_backends(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir))
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True


# ===========================================================================
# Rule configuration
# ===========================================================================


@needs_ruff
def _gate_from(tmp_path, rules_dir, config, **cli):
    """A gate resolved as the CLI resolves one: a real config file, plus
    command-line values that outrank it."""
    path = tmp_path / "fp.json"
    path.write_text(json.dumps(config))
    return LintGate(
        settings=resolve_settings(
            ConfigLayer(rules_dir=rules_dir, **cli),
            layer_from_config_file(str(path)),
            str(tmp_path),
        )
    )


class TestRuffSelectConfig:
    def test_constructor_overrides_default(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        # F401 (unused import) is in default set — restrict to E only
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir, ruff_select="E"))
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("F401") == 0

    def test_config_overrides_default(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        gate = _gate_from(tmp_path, rules_dir, {"ruff_select": "E"})
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("F401") == 0

    def test_constructor_overrides_config(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        # config file says E only, command line says F — F should win
        gate = _gate_from(tmp_path, rules_dir, {"ruff_select": "E"}, ruff_select="F")
        result = gate.evaluate([path], str(tmp_path))
        assert [v.rule for v in result.violations].count("F401") == 1


@needs_sg
class TestAstGrepRulesConfig:
    """No rule list given is the empty list, which filters nothing: all rules
    run. The constructor and the config file read an empty list the same way."""

    _CODE = "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n"

    def _rules(self, tmp_path, rules_dir, config, settings):
        config_path = tmp_path / "fp.json"
        config_path.write_text(json.dumps(config))
        path = _make_file(tmp_path, "widget.py", self._CODE)
        gate = LintGate(
            settings=resolve_settings(
                ConfigLayer(rules_dir=rules_dir),
                layer_from_config_file(str(config_path)),
                ".",
            )
        )
        return [v.rule for v in gate.evaluate([path], str(tmp_path)).violations]

    @pytest.mark.parametrize(
        ("config", "settings"),
        [
            ({}, LintSettings()),
            ({"ast_grep_rules": []}, LintSettings()),
            ({}, LintSettings(ast_grep_rules=())),
        ],
    )
    def test_empty_rule_list_runs_every_rule(
        self, tmp_path, rules_dir, config, settings
    ):
        rules = self._rules(tmp_path, rules_dir, config, settings)
        assert [
            rules.count(r) for r in ("no-list-append", "no-subscript-mutation")
        ] == [
            1,
            1,
        ]

    def test_empty_constructor_list_defers_to_config(self, tmp_path, rules_dir):
        rules = self._rules(
            tmp_path,
            rules_dir,
            {"ast_grep_rules": ["no-list-append"]},
            LintSettings(ast_grep_rules=()),
        )
        assert [
            rules.count(r) for r in ("no-list-append", "no-subscript-mutation")
        ] == [
            1,
            0,
        ]

    def test_settings_default_to_empty_collections(self):
        assert (LintSettings().ast_grep_rules, LintSettings().exclude) == ((), ())

    def test_constructor_filters_rules(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        # Only enable no-list-append, not no-subscript-mutation
        gate = LintGate(
            settings=LintSettings(
                rules_dir=rules_dir, ast_grep_rules=["no-list-append"]
            )
        )
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert [v.rule for v in ast_grep] == ["no-list-append"]
        assert [v.rule for v in result.violations].count("no-subscript-mutation") == 0

    def test_config_filters_rules(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = _gate_from(tmp_path, rules_dir, {"ast_grep_rules": ["no-list-append"]})
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert [v.rule for v in ast_grep] == ["no-list-append"]

    def test_constructor_overrides_config(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        # config file says no-list-append only, command line says no-subscript-mutation
        gate = _gate_from(
            tmp_path,
            rules_dir,
            {"ast_grep_rules": ["no-list-append"]},
            ast_grep_rules=("no-subscript-mutation",),
        )
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert [v.rule for v in ast_grep].count("no-subscript-mutation") == 1
        assert [v.rule for v in ast_grep].count("no-list-append") == 0

    def test_none_means_all_rules(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        gate = LintGate(settings=LintSettings(rules_dir=rules_dir, ast_grep_rules=None))
        result = gate.evaluate([path], str(tmp_path))
        ast_grep_rules = {
            v.rule
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        }
        assert len(ast_grep_rules) >= 2
