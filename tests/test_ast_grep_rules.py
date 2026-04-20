# tests/test_ast_grep_rules.py
"""Pure ast-grep rule tests — no Semgrep, no LintGate wiring.

Runs `sg scan` directly against the real rules to validate each rule
and measure ast-grep-only performance.
"""

import json
import os
import shutil
import subprocess

import pytest

_PKG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python_fp_lint")
_SGCONFIG = os.path.join(_PKG_DIR, "sgconfig.yml")

needs_sg = pytest.mark.skipif(
    shutil.which("sg") is None and shutil.which("ast-grep") is None,
    reason="ast-grep (sg) not installed",
)


def _sg_binary():
    return shutil.which("sg") or shutil.which("ast-grep")


def _make_file(tmp_path, content):
    f = tmp_path / "target.py"
    f.write_text(content)
    return str(f)


def _run_sg(filepath):
    """Run ast-grep scan and return list of matched rule IDs."""
    sg = _sg_binary()
    result = subprocess.run(
        [sg, "scan", "--json", "--config", _SGCONFIG, filepath],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=_PKG_DIR,
    )
    if not result.stdout.strip():
        return []
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        entries = []
        for line in result.stdout.strip().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return [e.get("ruleId", "unknown") for e in entries]


# ---------------------------------------------------------------------------
# Simple pattern rules (16)
# ---------------------------------------------------------------------------


@needs_sg
class TestListMutationRules:

    def test_list_append_fails(self, tmp_path):
        f = _make_file(tmp_path, "items = []\nitems.append(1)\n")
        assert "no-list-append" in _run_sg(f)

    def test_list_append_passes(self, tmp_path):
        f = _make_file(tmp_path, "items = [1, 2, 3]\n")
        assert "no-list-append" not in _run_sg(f)

    def test_list_extend_fails(self, tmp_path):
        f = _make_file(tmp_path, "items = []\nitems.extend([1, 2])\n")
        assert "no-list-extend" in _run_sg(f)

    def test_list_extend_passes(self, tmp_path):
        f = _make_file(tmp_path, "items = [1] + [2]\n")
        assert "no-list-extend" not in _run_sg(f)

    def test_list_insert_fails(self, tmp_path):
        f = _make_file(tmp_path, "items = []\nitems.insert(0, 1)\n")
        assert "no-list-insert" in _run_sg(f)

    def test_list_insert_passes(self, tmp_path):
        f = _make_file(tmp_path, "items = [1, 2, 3]\n")
        assert "no-list-insert" not in _run_sg(f)

    def test_list_pop_fails(self, tmp_path):
        f = _make_file(tmp_path, "items = [1, 2]\nitems.pop(0)\n")
        assert "no-list-pop" in _run_sg(f)

    def test_list_pop_passes(self, tmp_path):
        f = _make_file(tmp_path, "items = [1, 2, 3]\n")
        assert "no-list-pop" not in _run_sg(f)

    def test_list_remove_fails(self, tmp_path):
        f = _make_file(tmp_path, "items = [1, 2]\nitems.remove(1)\n")
        assert "no-list-remove" in _run_sg(f)

    def test_list_remove_passes(self, tmp_path):
        f = _make_file(tmp_path, "items = [x for x in [1, 2] if x != 1]\n")
        assert "no-list-remove" not in _run_sg(f)


@needs_sg
class TestDictMutationRules:

    def test_dict_clear_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {'a': 1}\nd.clear()\n")
        assert "no-dict-clear" in _run_sg(f)

    def test_dict_clear_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\n")
        assert "no-dict-clear" not in _run_sg(f)

    def test_dict_update_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\nd.update({'a': 1})\n")
        assert "no-dict-update" in _run_sg(f)

    def test_dict_update_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {**a, **b}\n")
        assert "no-dict-update" not in _run_sg(f)

    def test_dict_setdefault_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\nd.setdefault('key', [])\n")
        assert "no-dict-setdefault" in _run_sg(f)

    def test_dict_setdefault_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {'key': []}\n")
        assert "no-dict-setdefault" not in _run_sg(f)


@needs_sg
class TestSetMutationRules:

    def test_set_add_fails(self, tmp_path):
        f = _make_file(tmp_path, "s = set()\ns.add(1)\n")
        assert "no-set-add" in _run_sg(f)

    def test_set_add_passes(self, tmp_path):
        f = _make_file(tmp_path, "s = {1} | {2}\n")
        assert "no-set-add" not in _run_sg(f)

    def test_set_discard_fails(self, tmp_path):
        f = _make_file(tmp_path, "s = {1, 2}\ns.discard(1)\n")
        assert "no-set-discard" in _run_sg(f)

    def test_set_discard_passes(self, tmp_path):
        f = _make_file(tmp_path, "s = {1, 2} - {1}\n")
        assert "no-set-discard" not in _run_sg(f)


@needs_sg
class TestSubscriptMutationRules:

    def test_subscript_mutation_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\nd['key'] = 'value'\n")
        assert "no-subscript-mutation" in _run_sg(f)

    def test_subscript_mutation_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {'key': 'value'}\n")
        assert "no-subscript-mutation" not in _run_sg(f)

    def test_subscript_del_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {'a': 1}\ndel d['a']\n")
        assert "no-subscript-del" in _run_sg(f)

    def test_subscript_del_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {k: v for k, v in d.items() if k != 'a'}\n")
        assert "no-subscript-del" not in _run_sg(f)

    def test_subscript_augmented_mutation_plus_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {'a': 1}\nd['a'] += 1\n")
        assert "no-subscript-augmented-mutation" in _run_sg(f)

    def test_subscript_augmented_mutation_shift_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {'a': 8}\nd['a'] >>= 2\n")
        assert "no-subscript-augmented-mutation" in _run_sg(f)

    def test_subscript_augmented_mutation_passes(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\n")
        assert "no-subscript-augmented-mutation" not in _run_sg(f)

    def test_subscript_tuple_mutation_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\nd['a'], d['b'] = 1, 2\n")
        assert "no-subscript-tuple-mutation" in _run_sg(f)

    def test_subscript_tuple_mutation_passes(self, tmp_path):
        f = _make_file(tmp_path, "a, b = 1, 2\n")
        assert "no-subscript-tuple-mutation" not in _run_sg(f)

    def test_setitem_call_fails(self, tmp_path):
        f = _make_file(tmp_path, "d = {}\nd.__setitem__('k', 'v')\n")
        assert "no-setitem-call" in _run_sg(f)

    def test_operator_setitem_fails(self, tmp_path):
        f = _make_file(
            tmp_path, "import operator\nd = {}\noperator.setitem(d, 'k', 'v')\n"
        )
        assert "no-setitem-call" in _run_sg(f)

    def test_operator_setitem_aliased_fails(self, tmp_path):
        f = _make_file(
            tmp_path, "import operator as op\nd = {}\nop.setitem(d, 'k', 'v')\n"
        )
        assert "no-setitem-call" in _run_sg(f)

    def test_setitem_call_passes(self, tmp_path):
        f = _make_file(tmp_path, "d = {'k': 'v'}\n")
        assert "no-setitem-call" not in _run_sg(f)


@needs_sg
class TestNoneRules:

    def test_is_none_fails(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\nif x is None:\n    pass\n")
        assert "no-is-none" in _run_sg(f)

    def test_is_none_passes(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\n")
        assert "no-is-none" not in _run_sg(f)

    def test_is_not_none_fails(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\nif x is not None:\n    pass\n")
        assert "no-is-not-none" in _run_sg(f)

    def test_is_not_none_passes(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\n")
        assert "no-is-not-none" not in _run_sg(f)

    def test_none_default_param_fails(self, tmp_path):
        f = _make_file(tmp_path, "def f(x=None):\n    return x\n")
        assert "no-none-default-param" in _run_sg(f)

    def test_none_default_param_multiple_fails(self, tmp_path):
        f = _make_file(tmp_path, "def f(x, y=None, z=None):\n    return x\n")
        assert "no-none-default-param" in _run_sg(f)

    def test_none_default_param_non_none_passes(self, tmp_path):
        f = _make_file(tmp_path, "def f(x=0, y=''):\n    return x\n")
        assert "no-none-default-param" not in _run_sg(f)

    def test_none_default_param_bare_assignment_passes(self, tmp_path):
        f = _make_file(tmp_path, "x = None\n")
        assert "no-none-default-param" not in _run_sg(f)


@needs_sg
class TestOptionalNoneRules:

    def test_optional_type_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "from typing import Optional\ndef f(x: Optional[str]):\n    pass\n",
        )
        assert "no-optional-none" in _run_sg(f)

    def test_pipe_none_fails(self, tmp_path):
        f = _make_file(tmp_path, "def f(x: str | None):\n    pass\n")
        assert "no-optional-none" in _run_sg(f)

    def test_none_pipe_fails(self, tmp_path):
        f = _make_file(tmp_path, "def f(x: None | str):\n    pass\n")
        assert "no-optional-none" in _run_sg(f)

    def test_union_none_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "from typing import Union\ndef f(x: Union[str, None]):\n    pass\n",
        )
        assert "no-optional-none" in _run_sg(f)

    def test_union_none_reversed_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "from typing import Union\ndef f(x: Union[None, str]):\n    pass\n",
        )
        assert "no-optional-none" in _run_sg(f)

    def test_clean_type_passes(self, tmp_path):
        f = _make_file(tmp_path, "def f(x: str):\n    pass\n")
        assert "no-optional-none" not in _run_sg(f)

    def test_union_without_none_passes(self, tmp_path):
        f = _make_file(
            tmp_path, "from typing import Union\ndef f(x: Union[str, int]):\n    pass\n"
        )
        assert "no-optional-none" not in _run_sg(f)


@needs_sg
class TestStyleRules:

    def test_static_method_fails(self, tmp_path):
        f = _make_file(
            tmp_path, "class C:\n    @staticmethod\n    def f():\n        pass\n"
        )
        assert "no-static-method" in _run_sg(f)

    def test_static_method_passes(self, tmp_path):
        f = _make_file(tmp_path, "def f():\n    pass\n")
        assert "no-static-method" not in _run_sg(f)


# ---------------------------------------------------------------------------
# Multiline / exception rules (2)
# ---------------------------------------------------------------------------


@needs_sg
class TestExceptionRules:

    def test_except_exception_fails(self, tmp_path):
        f = _make_file(tmp_path, "try:\n    x = 1\nexcept Exception:\n    pass\n")
        assert "no-except-exception" in _run_sg(f)

    def test_except_exception_passes(self, tmp_path):
        f = _make_file(tmp_path, "try:\n    x = 1\nexcept ValueError:\n    pass\n")
        assert "no-except-exception" not in _run_sg(f)


# ---------------------------------------------------------------------------
# Augmented assignment rules (2 — attribute + local with pattern-not)
# ---------------------------------------------------------------------------


@needs_sg
class TestAugmentedAssignmentRules:

    def test_attribute_augmented_mutation_fails(self, tmp_path):
        f = _make_file(tmp_path, "class C:\n    x = 0\nc = C()\nc.x += 1\n")
        assert "no-attribute-augmented-mutation" in _run_sg(f)

    def test_attribute_augmented_mutation_passes(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\n")
        assert "no-attribute-augmented-mutation" not in _run_sg(f)

    def test_local_augmented_mutation_fails(self, tmp_path):
        f = _make_file(tmp_path, "x = 1\nx += 1\n")
        assert "no-local-augmented-mutation" in _run_sg(f)

    def test_local_augmented_mutation_all_operators(self, tmp_path):
        code = (
            "a = 1\na += 1\n"
            "b = 1\nb -= 1\n"
            "c = 1\nc *= 2\n"
            "d = 1\nd /= 2\n"
            "e = 1\ne //= 2\n"
            "f = 1\nf **= 2\n"
            "g = 10\ng %= 3\n"
            "h = 0xFF\nh &= 0x0F\n"
            "i = 0x0F\ni |= 0xF0\n"
            "j = 0xFF\nj ^= 0x0F\n"
            "k = 8\nk >>= 2\n"
            "m = 1\nm <<= 2\n"
        )
        f = _make_file(tmp_path, code)
        rules = _run_sg(f)
        assert rules.count("no-local-augmented-mutation") >= 12

    def test_local_augmented_mutation_attribute_passes(self, tmp_path):
        """obj.attr += val should NOT trigger no-local-augmented-mutation."""
        f = _make_file(tmp_path, "class C:\n    x = 0\nc = C()\nc.x += 1\n")
        assert "no-local-augmented-mutation" not in _run_sg(f)

    def test_local_augmented_mutation_subscript_passes(self, tmp_path):
        """obj[key] += val should NOT trigger no-local-augmented-mutation."""
        f = _make_file(tmp_path, "d = {'a': 1}\nd['a'] += 1\n")
        assert "no-local-augmented-mutation" not in _run_sg(f)


# ---------------------------------------------------------------------------
# Deep nesting + loop mutation (already existed as ast-grep rules)
# ---------------------------------------------------------------------------


@needs_sg
class TestDeepNestingRule:

    def test_for_in_for_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            process(cell)\n",
        )
        assert "no-deep-nesting" in _run_sg(f)

    def test_if_in_for_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "def f(items):\n"
            "    for x in items:\n"
            "        if x > 0:\n"
            "            process(x)\n",
        )
        assert "no-deep-nesting" in _run_sg(f)

    def test_flat_for_passes(self, tmp_path):
        f = _make_file(
            tmp_path, "def f(items):\n" "    for x in items:\n" "        process(x)\n"
        )
        assert "no-deep-nesting" not in _run_sg(f)


@needs_sg
class TestLoopMutationRule:

    def test_append_in_for_fails(self, tmp_path):
        f = _make_file(
            tmp_path,
            "def f(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        result.append(x)\n",
        )
        assert "no-loop-mutation" in _run_sg(f)

    def test_subscript_assign_in_for_fails(self, tmp_path):
        f = _make_file(
            tmp_path, "def f(d, keys):\n" "    for k in keys:\n" "        d[k] = 0\n"
        )
        assert "no-loop-mutation" in _run_sg(f)

    def test_no_mutation_in_for_passes(self, tmp_path):
        f = _make_file(
            tmp_path, "def f(items):\n" "    for x in items:\n" "        process(x)\n"
        )
        assert "no-loop-mutation" not in _run_sg(f)

    def test_mutation_outside_for_passes(self, tmp_path):
        f = _make_file(
            tmp_path,
            "def f(items):\n"
            "    result = []\n"
            "    result.append(42)\n"
            "    return result\n",
        )
        assert "no-loop-mutation" not in _run_sg(f)


# ---------------------------------------------------------------------------
# Vacuous test rule — flags test_* functions with no value-comparison assertion
# ---------------------------------------------------------------------------


@needs_sg
class TestVacuousTestRule:

    def test_only_assert_in_fails(self, tmp_path):
        f = _make_file(tmp_path, 'def test_foo():\n    assert "err" in messages\n')
        assert "test-vacuous" in _run_sg(f)

    def test_only_isinstance_fails(self, tmp_path):
        f = _make_file(
            tmp_path, "def test_foo():\n    assert isinstance(result, dict)\n"
        )
        assert "test-vacuous" in _run_sg(f)

    def test_only_assert_true_fails(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert True\n")
        assert "test-vacuous" in _run_sg(f)

    def test_only_bare_assert_fails(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert result\n")
        assert "test-vacuous" in _run_sg(f)

    def test_no_assert_at_all_fails(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    x = compute()\n")
        assert "test-vacuous" in _run_sg(f)

    def test_assert_eq_passes(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert result == expected\n")
        assert "test-vacuous" not in _run_sg(f)

    def test_assert_neq_passes(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert a != b\n")
        assert "test-vacuous" not in _run_sg(f)

    def test_assert_lt_passes(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert a < b\n")
        assert "test-vacuous" not in _run_sg(f)

    def test_assert_lte_passes(self, tmp_path):
        f = _make_file(tmp_path, "def test_foo():\n    assert a <= b\n")
        assert "test-vacuous" not in _run_sg(f)

    def test_mixed_weak_and_strong_passes(self, tmp_path):
        code = 'def test_foo():\n    assert "err" in messages\n    assert result == expected\n'
        f = _make_file(tmp_path, code)
        assert "test-vacuous" not in _run_sg(f)

    def test_non_test_function_not_flagged(self, tmp_path):
        f = _make_file(tmp_path, "def helper():\n    assert True\n")
        assert "test-vacuous" not in _run_sg(f)
