"""The corpus's own audit: every argh-contract row is covered, and by something real.

Issue #6 asks for a coverage test that maps row -> case and fails on an uncovered row. This
is that test, plus the thing that makes it honest: three of the twenty rows are **not**
assertable by `python -m cw.testing parity`, because they are only observable in a `--help`
body and the golden format puts help bodies in tier 3 (snapshot, never asserted). Those
three name the test that does cover them instead, and the test checks that that test exists.

A coverage map that silently counted a help-only row as "covered by parity" would be the
most expensive kind of wrong: it would read green while asserting nothing.
"""

import json
import os

import pytest

from cw import testing
from cw.tests import fixtures

#: Canonical spec section 9's compatibility contract, in full. The text is the row, the
#: value is where its coverage actually comes from.
CONTRACT_ROWS = {
    1: "command name = __name__ with _ -> -",
    2: "group name used verbatim (priv git_ops)",
    3: "defaulted POSITIONAL_OR_KEYWORD -> an --option",
    4: "short flags from first char, suppressed on collision; -h stripped",
    5: "flags = inferred + [declared not already present]",
    6: "bool default True -> store_false",
    7: "list/tuple default -> nargs='*'",
    8: "other non-None default -> type=type(default)",
    9: "choices[0] -> type",
    10: "*args -> positional nargs='*'",
    11: "**kwargs contributes no CLI args",
    12: "one @arg disables hints for the WHOLE function",
    13: "annotations read raw (PEP 563 blind)",
    14: "help defaults to '%(default)s'",
    15: "help renders repr(default), None -> '-'",
    16: "egress whitelist: only GeneratorType/list/tuple iterate; dict on ONE line",
    17: "None prints nothing; 0/False/'' DO print",
    18: "generators stream lazily",
    19: "CommandError -> '{cls}: {msg}' on stderr, SystemExit(code)",
    20: "a group's listing row reads group_kwargs['title'], NOT ['help']",
}

#: The three rows `parity` cannot assert, and the test that does assert each one. They are
#: help-rendering rows: the only place they show is a `--help` body, and a `--help` body is
#: tier 3 -- recorded and diffed advisorily, never asserted, because it wraps to COLUMNS and
#: changes shape between Python versions (3.13 reformatted argparse's option column).
#:
#: Each is instead covered by the dev-machine differential, which builds the same parser
#: with argh and with cw *in the same process at the same Python* and asserts the rendered
#: help is byte-identical -- a comparison a committed golden cannot make.
HELP_ONLY_ROWS = {
    14: "tests/argh_parity/test_parity.py::TestHelp",
    15: "tests/argh_parity/test_parity.py::TestHelp",
    20: "tests/argh_parity/test_cli_parity.py",
}


def _rows_covered_by_parity():
    """Every contract row a fixture shape claims to pin."""
    return set().union(*(shape.rows for shape in fixtures.SHAPES.values()))


class TestRowCoverage:
    """Issue #6: every row covered by >= 1 case, and the map is checked, not asserted."""

    def test_every_row_is_covered_by_parity_or_by_a_named_differential(self):
        covered = _rows_covered_by_parity() | set(HELP_ONLY_ROWS)
        missing = sorted(set(CONTRACT_ROWS) - covered)
        assert not missing, "\n".join(f"row {n}: {CONTRACT_ROWS[n]}" for n in missing)

    def test_the_parity_gate_asserts_seventeen_of_the_twenty_rows(self):
        """A number worth stating, because "all 20" would be a lie about three of them."""
        assert len(_rows_covered_by_parity()) == 17
        assert len(HELP_ONLY_ROWS) == 3

    @pytest.mark.parametrize("row,where", sorted(HELP_ONLY_ROWS.items()))
    def test_a_help_only_rows_named_covering_test_exists(self, row, where):
        """The escape hatch is only honest if the test it points at is really there."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), where.split("::")[0]
        )
        missing = f"row {row} points at a test file that is not there"
        assert os.path.exists(path), missing

    def test_no_shape_claims_a_row_that_is_not_in_the_contract(self):
        for shape in fixtures.SHAPES.values():
            unknown = shape.rows - set(CONTRACT_ROWS)
            complaint = f"{shape.name} claims non-existent row(s) {sorted(unknown)}"
            assert not unknown, complaint

    def test_no_shape_claims_a_row_it_could_not_reach(self):
        """A help-only row claimed by a shape would be a claim `parity` cannot honour."""
        for shape in fixtures.SHAPES.values():
            claimed = shape.rows & set(HELP_ONLY_ROWS)
            assert not claimed, (
                f"{shape.name} claims help-rendering row(s) {sorted(claimed)}, which tier 3 "
                f"records but never asserts"
            )


class TestTheCorpusIsReal:
    """Issue #6: every case is a file in the repo with a derivation, not a number in a doc."""

    def test_the_case_count_is_counted_rather_than_asserted(self):
        counted = sum(len(shape.cases) for shape in fixtures.SHAPES.values())
        assert fixtures.case_count() == counted
        assert counted >= 120, "the corpus should not silently shrink"

    def test_the_readme_states_the_real_count_and_the_real_per_shape_counts(self):
        """Issue #6: the count is stated in cw/tests/README.md and matched by a test.

        The spec's "7 repos / 214 cases" was a number in a document with no file behind it.
        This is the check that stops the replacement becoming the same thing.
        """
        readme = open(
            os.path.join(os.path.dirname(testing.DFLT_GOLDENS_DIR), "README.md"),
            encoding="utf-8",
        ).read()
        assert (
            f"{len(fixtures.SHAPES)} shapes / {fixtures.case_count()} cases" in readme
        )
        for shape in fixtures.SHAPES.values():
            assert f"| `{shape.name}` | " in readme, f"{shape.name} is not in the table"
            row = next(
                line for line in readme.splitlines() if f"| `{shape.name}` |" in line
            )
            assert row.rstrip().endswith(f"| {len(shape.cases)} |"), row

    def test_every_shape_says_which_repo_it_models_and_what_it_pins(self):
        for shape in fixtures.SHAPES.values():
            assert shape.models, shape.name
            assert len(shape.pins) > 80, f"{shape.name}'s `pins` is not a derivation"

    def test_every_shape_has_a_committed_golden(self):
        for name in fixtures.SHAPES:
            path = os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
            assert os.path.exists(path), f"{name} has no recorded golden"

    def test_every_golden_has_a_shape_and_every_shape_has_a_golden(self):
        recorded = {
            json.load(
                open(os.path.join(testing.DFLT_GOLDENS_DIR, name), encoding="utf-8")
            )["shape"]
            for name in os.listdir(testing.DFLT_GOLDENS_DIR)
            if name.endswith(".json")
        }
        assert recorded == set(fixtures.SHAPES)

    def test_every_shape_has_a_no_arguments_case_and_a_help_case(self):
        """The two argvs every CLI is asked first, and the two most likely to regress."""
        for shape in fixtures.SHAPES.values():
            assert () in shape.cases, f"{shape.name} has no bare-invocation case"
            assert ("--help",) in shape.cases, f"{shape.name} has no --help case"

    @pytest.mark.parametrize("name", sorted(fixtures.SHAPES))
    def test_every_shape_records_real_command_output(self, name):
        """The guard for a bug that really happened, and was invisible without it.

        `capture` rebinds `sys.stdout` around a run. An early version forgot to flush the
        stream it *displaced* -- the one argh captured at import -- so recording through a
        pipe or a shell redirect drained that buffer after the descriptor was restored and
        wrote goldens whose every command produced no output at all. Every structural check
        still passed: the case count, the exit codes, the usage lines, the provenance. Only
        this one would have failed, so it exists.
        """
        golden = testing.load_golden(
            os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
        )
        substantive = [
            case
            for case in golden["cases"]
            if case["tier"] == 1
            and case["stdout"]
            and not case["stdout"].startswith("usage:")
        ]
        assert len(substantive) >= 3, (
            f"{name}'s golden has almost no command output -- it was probably recorded "
            f"through a pipe by a cw.testing.capture that lost the displaced stream's buffer"
        )

    def test_every_shape_has_at_least_one_failing_case(self):
        """A corpus of only happy paths asserts half a CLI."""
        for name in fixtures.SHAPES:
            golden = testing.load_golden(
                os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
            )
            codes = {case["returncode"] for case in golden["cases"]}
            assert codes - {0}, f"{name} has no case with a non-zero exit code"


class TestTheGoldensCarryTheirProvenance:
    """Issue #7: a golden must say what recorded it, so a stale one can be spotted."""

    @pytest.mark.parametrize("name", sorted(fixtures.SHAPES))
    def test_each_golden_names_argh_its_version_and_the_pinned_env(self, name):
        golden = testing.load_golden(
            os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
        )
        assert golden["recorded_with"]["tool"] == "argh"
        assert golden["recorded_with"]["version"] == "0.31.3"
        assert golden["recorded_with"]["python"]
        assert golden["env"]["COLUMNS"] == testing.DFLT_COLUMNS
        assert golden["newlines"] == "lf"

    @pytest.mark.parametrize("name", sorted(fixtures.SHAPES))
    def test_no_golden_carries_a_windows_newline(self, name):
        """The format stores LF; the comparator is what handles CRLF at replay time."""
        path = os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
        assert b"\\r" not in open(path, "rb").read()

    @pytest.mark.parametrize("name", sorted(fixtures.SHAPES))
    def test_every_golden_is_pure_ascii(self, name):
        """So the Windows console's code page can never become a question.

        The fixtures deliberately emit nothing outside ASCII. That is not a limitation of
        the harness -- `PYTHONUTF8` and `PYTHONIOENCODING` are pinned for exactly this --
        but it removes the last variable between a golden recorded on a Mac and the same
        golden asserted on a cp1252 console.
        """
        path = os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
        open(path, encoding="ascii").read()  # raises UnicodeDecodeError if not

    @pytest.mark.parametrize("name", sorted(fixtures.SHAPES))
    def test_no_golden_carries_a_machine_specific_address(self, name):
        path = os.path.join(testing.DFLT_GOLDENS_DIR, f"{name}.json")
        text = open(path, encoding="utf-8").read()
        assert "0xADDR" not in text or " at 0x1" not in text
        assert testing.scrub_addresses(text) == text


class TestArghIsNotADependency:
    """Issue #7's headline, asserted by the environment rather than by convention."""

    def test_nothing_under_cw_imports_argh(self):
        import pathlib

        root = pathlib.Path(testing.__file__).parent
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                offends = line.startswith(("import argh", "from argh"))
                assert not offends, f"{path}: {line}"

    def test_argh_is_not_a_runtime_dependency_nor_in_the_test_extra(self):
        """Issue #7: CI installs `cw[test]`, and `cw[test]` must not pull LGPL argh."""
        import pathlib
        import tomllib

        root = pathlib.Path(testing.__file__).parent.parent
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        project = config["project"]
        assert project["dependencies"] == []
        extras = project["optional-dependencies"]
        assert not any("argh" in dep for dep in extras["test"])
        # ... and it IS in `dev`, which is where the differential and the recorder live.
        assert any(dep.startswith("argh==") for dep in extras["dev"])

    def test_the_parity_gate_really_runs_with_no_argh_importable(self):
        """The claim, run rather than declared: hide argh and see the gate still pass."""
        import subprocess
        import sys

        blocker = (
            "import sys\n"
            "class Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] == 'argh':\n"
            "            raise ImportError('argh is hidden for this test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, Block())\n"
            "import io\n"
            "from cw.testing import parity\n"
            "out = io.StringIO()\n"
            "code = parity(out=out)\n"
            "print(code, out.getvalue().strip())\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", blocker], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().startswith("0 ")
        assert done.stdout.strip().endswith(": identical")

    def test_the_recorder_lives_outside_the_test_tree(self):
        """Recording is a dev act. It must not be reachable from `pytest`."""
        import pathlib

        root = pathlib.Path(testing.__file__).parent.parent
        assert (root / "misc" / "record_goldens.py").exists()
        assert not (root / "tests" / "record_goldens.py").exists()


class TestTheFixtureModuleItself:
    """The corpus's own small surface. The argh-side builders are covered by the recorder.

    `declare`, `_single_command`, `_subcommands` and `_mutated` describe how *argh* would
    have built each shape, and only `misc/record_goldens.py` runs them -- which is the
    point: they take the `argh` module as an argument so this file can ship inside `cw`
    while argh stays a developer-only install. They are exercised whenever the goldens are
    re-recorded, and their output is what every golden in `goldens/` is made of.
    """

    def test_a_shape_reprs_as_something_a_failure_message_can_use(self):
        shown = repr(fixtures.THEREMIN)
        assert "theremin" in shown and "cases" in shown and "rows" in shown

    def test_a_declaration_with_no_long_flag_says_what_argh_needs(self):
        with pytest.raises(ValueError, match="cannot guess"):
            fixtures._param_name_of(("-i", "-x"))

    def test_config_from_derives_the_cw_spelling_from_the_argh_one(self):
        """One source for both spellings, so the two cannot drift apart."""
        derived = fixtures.config_from(
            [(("-p", "--pipeline"), {"nargs": "?"}), (("--scale",), {"help": "h"})]
        )
        assert derived == {
            "pipeline": {"nargs": "?", "flags": ["-p"]},
            "scale": {"help": "h"},
        }

    def test_a_shape_without_config_resolves_to_no_config(self):
        assert fixtures._resolved_config(fixtures.CONTRACT) is None

    def test_the_contract_shape_refuses_to_run_without_a_CommandError_installed(self):
        """Neither side gets a default: a default here would record the wrong exception."""
        saved = list(fixtures._COMMAND_ERROR)
        fixtures._COMMAND_ERROR.clear()
        try:
            with pytest.raises(RuntimeError, match="no CommandError class installed"):
                fixtures.raises_command_error()
        finally:
            fixtures._COMMAND_ERROR[:] = saved

    def test_the_argh_only_partial_wrapper_matches_the_partial_it_stands_in_for(self):
        """argh cannot take a functools.partial, so the golden uses a hand-written wrapper.

        The parity claim only means something if the two really do the same thing.
        """
        assert fixtures.packages_from_all_setup_cfgs_for_argh(
            "/p"
        ) == fixtures.packages_from_all_setup_cfgs("/p")
