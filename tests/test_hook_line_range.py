"""
Tests for lint-check.sh line-range filtering.

The hook must only flag violations that fall within the edited line range, so that:
- pre-existing violations outside the edit do not cause false-positive blocks
- line-number shifts caused by insertions/deletions don't trigger spurious blocks
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOOK = os.path.join(_PROJECT_ROOT, "hooks", "lint-check.sh")
_LINT_BIN = os.path.join(_PROJECT_ROOT, "bin", "lint")

needs_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed",
)


def _env():
    """Point the hook at the current test interpreter so python_fp_lint is importable."""
    env = os.environ.copy()
    env["PYTHON_FP_LINT_CMD"] = f"{sys.executable} -m python_fp_lint"
    # Ensure python_fp_lint is importable when the hook cds into a temp directory.
    # The package may only be on sys.path because the project root is in PYTHONPATH
    # (editable installs via pip install -e . don't always register in site-packages).
    env["PYTHONPATH"] = _PROJECT_ROOT + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return env


def _activate(project_dir):
    subprocess.run(
        ["sh", _LINT_BIN, "on"], cwd=project_dir, capture_output=True, env=_env()
    )


def _deactivate(project_dir):
    subprocess.run(
        ["sh", _LINT_BIN, "off"], cwd=project_dir, capture_output=True, env=_env()
    )


def _run_hook(project_dir, tool_name, tool_input):
    event = {"tool_name": tool_name, "tool_input": tool_input}
    return subprocess.run(
        ["sh", _HOOK],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=project_dir,
        env=_env(),
    )


@pytest.fixture
def gated(tmp_path):
    # Resolve symlinks so the hash matches what the shell computes via $PWD
    # (on macOS, /var/folders/... resolves to /private/var/folders/...)
    real = os.path.realpath(str(tmp_path))
    _activate(real)
    yield real
    _deactivate(real)


@needs_ruff
class TestHookLineRangeFiltering:
    def test_violation_in_edit_range_is_blocked(self, gated):
        """Edit that introduces a violation within its range must be blocked."""
        f = os.path.join(gated, "s.py")
        with open(f, "w") as fh:
            fh.write("x = 1\n# PLACEHOLDER\ny = 2\n")

        result = _run_hook(
            gated,
            "Edit",
            {
                "file_path": f,
                "old_string": "# PLACEHOLDER",
                "new_string": "import os",  # F401 — unused import
                "replace_all": False,
            },
        )
        assert result.returncode == 2, f"Expected block.\n{result.stderr}"

    def test_clean_edit_is_allowed(self, gated):
        """Edit that introduces no violation must be allowed."""
        f = os.path.join(gated, "s.py")
        with open(f, "w") as fh:
            fh.write("x = 1\n# PLACEHOLDER\ny = 2\n")

        result = _run_hook(
            gated,
            "Edit",
            {
                "file_path": f,
                "old_string": "# PLACEHOLDER",
                "new_string": "# clean comment",
                "replace_all": False,
            },
        )
        assert result.returncode == 0, f"Expected allow.\n{result.stderr}"

    def test_existing_violation_outside_range_does_not_block(self, gated):
        """Pre-existing violation outside the edit range must not block."""
        f = os.path.join(gated, "s.py")
        # F401 at line 1; edit targets line 3
        with open(f, "w") as fh:
            fh.write("import os\nx = 1\n# PLACEHOLDER\n")

        result = _run_hook(
            gated,
            "Edit",
            {
                "file_path": f,
                "old_string": "# PLACEHOLDER",
                "new_string": "# clean comment",
                "replace_all": False,
            },
        )
        assert (
            result.returncode == 0
        ), f"Expected allow (violation outside range).\n{result.stderr}"

    def test_shifted_violation_does_not_block(self, gated):
        """Inserting lines before an existing violation shifts its line number out of
        the edit range — must not block."""
        f = os.path.join(gated, "s.py")
        # F401 at line 3; edit inserts 2 lines at line 1, shifting it to line 4
        with open(f, "w") as fh:
            fh.write("# PLACEHOLDER\nx = 1\nimport os\n")

        result = _run_hook(
            gated,
            "Edit",
            {
                "file_path": f,
                "old_string": "# PLACEHOLDER",
                "new_string": "# line a\n# line b",  # range becomes [1, 2]
                "replace_all": False,
            },
        )
        # Post-edit: import os is now at line 4, outside range [1, 2]
        assert (
            result.returncode == 0
        ), f"Expected allow (shifted violation).\n{result.stderr}"

    def test_gate_off_allows_everything(self, tmp_path):
        """When the gate is inactive, hook must not block any edit."""
        f = os.path.join(str(tmp_path), "s.py")
        with open(f, "w") as fh:
            fh.write("x = 1\n")

        result = _run_hook(
            str(tmp_path),
            "Edit",
            {
                "file_path": f,
                "old_string": "x = 1",
                "new_string": "import os",
                "replace_all": False,
            },
        )
        assert result.returncode == 0

    def test_write_with_violation_is_blocked(self, gated):
        """Writing a new file containing a violation must be blocked."""
        f = os.path.join(gated, "new.py")
        result = _run_hook(
            gated,
            "Write",
            {
                "file_path": f,
                "content": "import os\nx = 1\n",
            },
        )
        assert result.returncode == 2, f"Expected block.\n{result.stderr}"

    def test_write_clean_file_is_allowed(self, gated):
        """Writing a clean file must be allowed."""
        f = os.path.join(gated, "new.py")
        result = _run_hook(
            gated,
            "Write",
            {
                "file_path": f,
                "content": "x = 1\n",
            },
        )
        assert result.returncode == 0
