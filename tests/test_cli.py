# tests/test_cli.py
"""CLI integration tests for python -m python_fp_lint."""

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
# `check` and `precommit` require --config; the shipped example enables
# every rule, so it reproduces the built-in defaults.
CONFIG = os.path.join(REPO_ROOT, "config.example.json")


def _with_config(args):
    """Append --config to subcommands that require it."""
    needs_config = {"check", "precommit"} & set(args)
    return (*args, "--config", CONFIG) if needs_config else args


@pytest.fixture
def clean_file(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n")
    return str(f)


@pytest.fixture
def dirty_file(tmp_path):
    f = tmp_path / "dirty.py"
    f.write_text('d = {}\nd["key"] = "value"\n')
    return str(f)


def _run_raw(*args):
    """Run the CLI verbatim, adding nothing."""
    return subprocess.run(
        [sys.executable, "-m", "python_fp_lint", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _run_check(*args):
    return _run_raw(*_with_config(("check", *args)))


def _run_bare(*args):
    """Run without the 'check' subcommand."""
    return _run_raw(*_with_config(args))


class TestCLI:
    def test_clean_file_exits_zero(self, clean_file):
        result = _run_check(clean_file)
        assert result.returncode == 0
        assert "No violations" in result.stdout

    def test_dirty_file_exits_nonzero(self, dirty_file):
        result = _run_check(dirty_file)
        assert result.returncode == 1
        assert "violation" in result.stdout

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text('d = {}\nd["k"] = 1\n')
        (tmp_path / "b.py").write_text("x = 1\n")
        result = _run_check(str(tmp_path / "a.py"), str(tmp_path / "b.py"))
        assert result.returncode == 1
        assert "no-subscript-mutation" in result.stdout

    def test_no_subcommand_exits_with_help(self):
        result = _run_bare()
        assert result.returncode == 1

    def test_setitem_detected(self, tmp_path):
        f = tmp_path / "setitem.py"
        f.write_text('d = {}\nd.__setitem__("k", 1)\n')
        result = _run_check(str(f))
        assert result.returncode == 1
        assert "no-setitem-call" in result.stdout


class TestJSONOutput:
    def test_clean_file_json(self, clean_file):
        result = _run_bare("--format", "json", "check", clean_file)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["passed"] is True
        assert data["violation_count"] == 0
        assert data["violations"] == []

    def test_dirty_file_json(self, dirty_file):
        result = _run_bare("--format", "json", "check", dirty_file)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["violation_count"] > 0
        v = data["violations"][0]
        assert set(v.keys()) == {"rule", "file", "line", "message"}
        assert isinstance(v["line"], int)

    def test_json_output_is_valid_json(self, dirty_file):
        result = _run_bare("--format", "json", "check", dirty_file)
        json.loads(result.stdout)  # must not raise


class TestDirectoryAndGlob:
    def test_directory_recursive(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "a.py").write_text("x = []\nx.append(1)\n")
        result = _run_bare("--format", "json", "check", str(tmp_path))
        data = json.loads(result.stdout)
        assert data["violation_count"] >= 1
        assert any(v["rule"] == "no-list-append" for v in data["violations"])

    def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("x = []\nx.append(1)\n")
        (tmp_path / "b.txt").write_text("x = []\nx.append(1)\n")
        # Quoted glob — bypasses shell expansion, handled by _expand_paths
        result = _run_bare("--format", "json", "check", str(tmp_path / "*.py"))
        data = json.loads(result.stdout)
        assert data["violation_count"] >= 1
        assert all(v["file"].endswith(".py") for v in data["violations"])

    def test_mix_files_and_dirs(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "mod.py").write_text("x = []\nx.append(1)\n")
        f = tmp_path / "standalone.py"
        f.write_text('d = {}\nd["k"] = 1\n')
        result = _run_bare("--format", "json", "check", str(d), str(f))
        data = json.loads(result.stdout)
        files = {v["file"] for v in data["violations"]}
        assert len(files) == 2


class TestRulesCommand:
    def test_rules_text(self):
        result = _run_bare("rules")
        assert result.returncode == 0
        # Should list some rules (ast-grep, ruff, and beniget)
        assert len(result.stdout) > 0
        assert "ast-grep" in result.stdout
        assert "ruff" in result.stdout
        assert "beniget" in result.stdout

    def test_rules_json(self):
        result = _run_bare("--format", "json", "rules")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0
        backends = {r["backend"] for r in data}
        assert backends == {"ast-grep", "ruff", "beniget"}
        for r in data:
            assert set(r.keys()) == {"id", "message", "severity", "backend"}

    def test_rules_includes_known_rules(self):
        result = _run_bare("--format", "json", "rules")
        data = json.loads(result.stdout)
        ids = {r["id"] for r in data}
        assert "no-list-append" in ids
        assert "no-deep-nesting" in ids
        assert "reassignment" in ids


class TestSchemaCommand:
    def test_schema_is_valid_json(self):
        result = _run_bare("schema")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "check_output" in data
        assert "rules_output" in data

    def test_schema_describes_violations(self):
        result = _run_bare("schema")
        data = json.loads(result.stdout)
        props = data["check_output"]["properties"]
        assert "passed" in props
        assert "violations" in props
        assert "violation_count" in props


class TestSelfLint:
    """Run the linter on this repo's own source code."""

    def test_lintgate_finds_violations_in_own_codebase(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        result = _run_bare(
            "--format", "json", "check", os.path.join(repo_root, "python_fp_lint")
        )
        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["violation_count"] > 0
        rules_hit = {v["rule"] for v in data["violations"]}
        # The linter's own code uses patterns it flags
        assert len(rules_hit) > 1, f"Expected multiple rule types, got: {rules_hit}"


class TestBaselineCommand:
    def _repo(self, tmp_path):
        def git(*args):
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text('d = {}\nd["k"] = 1\n')
        git("add", "mod.py")
        git("commit", "-qm", "init")
        return tmp_path

    def _run(self, repo, *args):
        return subprocess.run(
            [sys.executable, "-m", "python_fp_lint", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def test_update_creates_the_file(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        result = self._run(
            repo, "baseline", "update", "--config", CONFIG, "--baseline", str(path)
        )
        assert result.returncode == 0
        assert json.loads(path.read_text()) == {"total": 1}

    def test_update_overwrites_an_existing_file(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        path.write_text('{"total": 999}\n')
        self._run(
            repo, "baseline", "update", "--config", CONFIG, "--baseline", str(path)
        )
        assert json.loads(path.read_text()) == {"total": 1}

    def test_show_reports_recorded_and_current(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        path.write_text('{"total": 5}\n')
        result = self._run(
            repo,
            "--format",
            "json",
            "baseline",
            "show",
            "--config",
            CONFIG,
            "--baseline",
            str(path),
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {
            "baseline": 5,
            "total": 1,
            "path": str(path),
        }

    def test_show_on_a_missing_file_exits_two(self, tmp_path):
        repo = self._repo(tmp_path)
        result = self._run(
            repo,
            "baseline",
            "show",
            "--config",
            CONFIG,
            "--baseline",
            str(repo / "absent.json"),
        )
        assert result.returncode == 2
        assert "baseline update" in result.stderr

    def test_no_baseline_anywhere_exits_two(self, tmp_path):
        repo = self._repo(tmp_path)
        result = self._run(repo, "baseline", "show", "--config", CONFIG)
        assert result.returncode == 2
        assert "no baseline configured" in result.stderr

    def test_update_into_a_missing_directory_exits_two(self, tmp_path):
        """M1: a raw FileNotFoundError traceback, not a one-line error."""
        repo = self._repo(tmp_path)
        result = self._run(
            repo,
            "baseline",
            "update",
            "--config",
            CONFIG,
            "--baseline",
            str(repo / "absent" / "b.json"),
        )
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        assert "cannot write baseline file" in result.stderr


class TestBaselineRefusesToGuess:
    """A backend that cannot run contributes zero violations, which would read
    as a clean repo and record a baseline of zero.

    In-process rather than a subprocess, because `_which` falls back to the
    interpreter's own bin directory -- where `ruff` and `ast-grep` live -- so
    no amount of PATH manipulation in a child process makes them unreachable.
    """

    class _Args:
        def __init__(self, config, baseline):
            self.config = config
            self.baseline = baseline
            self.format = "text"
            self.ruff_select = None
            self.ast_grep_rules = None
            self.exclude = None
            self.max_complexity = None
            self.max_statements = None
            self.strict = False

    def test_update_exits_two_without_writing(self, tmp_path, monkeypatch):
        from python_fp_lint.__main__ import _run_baseline_update

        path = tmp_path / "b.json"
        monkeypatch.setattr(
            "python_fp_lint.__main__.missing_backends", lambda: ["ruff"]
        )
        with pytest.raises(SystemExit) as exc:
            _run_baseline_update(self._Args(CONFIG, str(path)))
        assert exc.value.code == 2
        assert not path.exists()


class TestPrecommitRatchet:
    DIRTY = 'd = {}\nd["k"] = 1\n'  # one violation
    DIRTIER = 'd = {}\nd["k"] = 1\nd.update({"j": 2})\n'  # two

    def _repo(self, tmp_path, committed, baseline_total):
        def git(*args):
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text(committed)
        # `baseline` comes last: config.example.json carries "baseline": null,
        # and spreading it after would put the key back to null.
        (tmp_path / "fp.json").write_text(
            json.dumps({**json.load(open(CONFIG)), "baseline": "fp-baseline.json"})
        )
        (tmp_path / "fp-baseline.json").write_text(
            json.dumps({"total": baseline_total}) + "\n"
        )
        git("add", "mod.py", "fp.json", "fp-baseline.json")
        git("commit", "-qm", "init")
        return tmp_path

    def _run(self, repo, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "--format",
                "json",
                "precommit",
                "--config",
                str(repo / "fp.json"),
                *args,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def _git_out(self, repo, *args):
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True
        ).stdout

    def test_equal_total_passes(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        result = self._run(repo)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_rise_fails_and_leaves_the_baseline_alone(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "mod.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo)
        assert result.returncode == 1
        assert json.loads(result.stdout)["ratchet"] == {
            "baseline": 1,
            "total": 2,
            "tightened": False,
        }
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 1}

    def test_fall_tightens_and_stages(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=2)
        (repo / "mod.py").write_text(self.DIRTY)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo)
        assert result.returncode == 0
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 1}
        assert "fp-baseline.json" in self._git_out(
            repo, "diff", "--cached", "--name-only"
        )

    def test_no_tighten_passes_without_writing(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=2)
        (repo / "mod.py").write_text(self.DIRTY)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo, "--no-tighten")
        assert result.returncode == 0
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 2}

    def test_pre_existing_violations_do_not_block(self, tmp_path):
        """The whole point: a dirty legacy file can still be committed."""
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "mod.py").write_text(self.DIRTY + "# a comment\n")
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        assert self._run(repo).returncode == 0

    def test_text_output_names_only_staged_violations(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "other.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "other.py"], cwd=repo, check=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "precommit",
                "--config",
                str(repo / "fp.json"),
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 1
        assert "other.py" in result.stdout
        assert "mod.py" not in result.stdout
        assert "1 further violation" in result.stdout
        assert "did not stage" in result.stdout

    def _run_text(self, repo, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "precommit",
                "--config",
                str(repo / "fp.json"),
                *args,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def test_no_tighten_on_a_fall_says_so(self, tmp_path):
        """I1: silence here is how a recorded total drifts above reality."""
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=5)
        result = self._run_text(repo, "--no-tighten")
        assert result.returncode == 0
        assert "ratchet: 5 → 1 (-4)" in result.stdout
        assert "--no-tighten" in result.stdout
        assert "baseline update" in result.stdout

    def test_regression_with_nothing_staged_names_the_violations(self, tmp_path):
        """I2: the CI case. Filtering to a staged set of none printed nothing."""
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=1)
        result = self._run_text(repo, "--no-tighten")
        assert result.returncode == 1
        assert "ratchet: 1 → 2 (+1)" in result.stdout
        assert result.stdout.count("mod.py:") == 2
        assert "further violation" not in result.stdout

    def test_regression_with_nothing_staged_caps_the_list(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=1)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys;"
                "import python_fp_lint.__main__ as m;"
                "m._MAX_REPORTED_VIOLATIONS = 1;"
                "sys.argv = ['python-fp-lint', 'precommit', '--config', "
                f"{str(repo / 'fp.json')!r}];"
                "m.main()",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 1
        assert "… and 1 more (run `check` for the full list)" in result.stdout

    def test_json_counts_do_not_contradict_each_other(self, tmp_path):
        """I3: violation_count is the repo; the array has its own count."""
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "other.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "other.py"], cwd=repo, check=True)
        data = json.loads(self._run(repo).stdout)
        assert data["violation_count"] == 3
        assert data["reported_violation_count"] == 2
        assert len(data["violations"]) == data["reported_violation_count"]
        assert {v["file"] for v in data["violations"]} == {"other.py"}

    def test_a_clean_staged_file_still_names_the_violations(self, tmp_path):
        """A staged set that filters to nothing is the empty-report bug again.

        Realistic whenever the baseline is stale against the index: after a
        pull, a merge, or someone else's commit.
        """
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=1)
        (repo / "clean.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "clean.py"], cwd=repo, check=True)
        result = self._run_text(repo, "--no-tighten")
        assert result.returncode == 1
        assert "ratchet: 1 → 2 (+1)" in result.stdout
        assert result.stdout.count("mod.py:") == 2
        assert "did not stage" not in result.stdout

        data = json.loads(self._run(repo, "--no-tighten").stdout)
        assert data["violation_count"] == 2
        assert data["reported_violation_count"] == 2
        assert len(data["violations"]) == 2

    def test_a_sparse_checkout_does_not_bank_a_windfall(self, tmp_path):
        """`checkout-index -a` skipped skip-worktree entries, exit 0, silently."""
        repo = self._repo(tmp_path, "x = 1\n", baseline_total=2)
        (repo / "keep").mkdir()
        (repo / "keep" / "a.py").write_text("y = 2\n")
        (repo / "away").mkdir()
        (repo / "away" / "b.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "two trees"], cwd=repo, check=True)
        subprocess.run(["git", "sparse-checkout", "set", "keep"], cwd=repo, check=True)
        assert not (repo / "away" / "b.py").exists()  # skip-worktree

        result = self._run(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["ratchet"]["total"] == 2
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 2}

    def test_an_unmerged_index_exits_two(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        base = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        def git(*args, check=True):
            return subprocess.run(
                ["git", *args], cwd=repo, check=check, capture_output=True
            )

        git("checkout", "-q", "-b", "other")
        (repo / "mod.py").write_text(self.DIRTIER)
        git("commit", "-qam", "theirs")
        git("checkout", "-q", base)
        (repo / "mod.py").write_text(self.DIRTY + "e = []\n")
        git("commit", "-qam", "ours")
        git("merge", "other", check=False)

        result = self._run(repo)
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        assert "unmerged" in result.stderr

    def test_json_with_nothing_staged_lists_the_violations(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=1)
        data = json.loads(self._run(repo, "--no-tighten").stdout)
        assert data["violation_count"] == 2
        assert data["reported_violation_count"] == 2
        assert len(data["violations"]) == 2


class TestSchemaCommand:
    def _schema(self):
        result = subprocess.run(
            [sys.executable, "-m", "python_fp_lint", "schema"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 0
        return json.loads(result.stdout)

    def test_describes_the_ratchet_output(self):
        props = self._schema()["precommit_ratchet_output"]["properties"]
        assert set(props["ratchet"]["properties"]) == {
            "baseline",
            "total",
            "tightened",
        }

    def test_describes_both_counts(self):
        props = self._schema()["precommit_ratchet_output"]["properties"]
        assert "reported_violation_count" in props
        assert "NOT the length" in props["violation_count"]["description"]


class TestBaselineFlagScope:
    """M2: --baseline on `check` was accepted and silently ignored."""

    def test_check_rejects_baseline(self, tmp_path):
        (tmp_path / "m.py").write_text("x = 1\n")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "check",
                "--config",
                CONFIG,
                "--baseline",
                "/nonexistent/x.json",
                str(tmp_path / "m.py"),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 2
        assert "unrecognized arguments: --baseline" in result.stderr

    def test_precommit_and_baseline_still_accept_it(self):
        for argv in (
            ["precommit", "--help"],
            ["baseline", "update", "--help"],
            ["baseline", "show", "--help"],
        ):
            result = subprocess.run(
                [sys.executable, "-m", "python_fp_lint", *argv],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": REPO_ROOT},
            )
            assert "--baseline" in result.stdout, argv


class TestPrecommitWithoutBaselineIsUnchanged:
    def test_any_violation_in_a_staged_file_still_blocks(self, tmp_path):
        def git(*args):
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text('d = {}\nd["k"] = 1\n')
        git("add", "mod.py")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "precommit",
                "--config",
                CONFIG,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 1

    def test_strict_checks_backends_before_reading_config(
        self, tmp_path, monkeypatch, capsys
    ):
        """`--strict` must fail on a missing backend before ever opening
        `--config`, so a bad config path never masks the backend error.

        In-process rather than a subprocess, because `_which` falls back to
        the interpreter's own bin directory -- where `ruff` and `ast-grep`
        live -- so no amount of PATH manipulation in a child process makes
        them unreachable (mirrors `TestBaselineRefusesToGuess`).
        """
        from python_fp_lint.__main__ import _run_precommit

        def git(*args):
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        git("init", "-q", "--template=")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "python_fp_lint.__main__.missing_backends", lambda: ["ruff"]
        )

        class Args:
            config = str(tmp_path / "does-not-exist.json")
            baseline = None
            format = "text"
            ruff_select = None
            ast_grep_rules = None
            exclude = None
            max_complexity = None
            max_statements = None
            strict = True
            files = []
            no_tighten = False

        with pytest.raises(SystemExit) as exc:
            _run_precommit(Args())
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "required lint backend(s) not found" in err
        assert "config" not in err.lower()
