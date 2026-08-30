"""`cw.testing` -- the standalone harness, its D4 guarantee, and the parity gate.

The round-trip test is the important one: characterize a toy CLI, mutate it, and assert
`replay` notices. A harness that cannot fail is worse than no harness, because it is
believed.
"""

import ast
import io
import json
import os
import subprocess
import sys
import textwrap

import pytest

from cw import testing

P = sys.executable

#: What `cw/testing.py` is allowed to import at module scope. This is the D4 contract, and
#: it is the reason the file can be copied into a repo that will never depend on cw.
ALLOWED_MODULE_IMPORTS = {
    "argparse",
    "difflib",
    "json",
    "os",
    "re",
    "shlex",
    "subprocess",
    "sys",
}


# =======================================================================================
# D4: the standalone guarantee, asserted by reading the file rather than by trusting it
# =======================================================================================


def _module_scope_imports(path):
    """Every module imported at module scope by ``path``, by top-level package name."""
    with open(path, "r", encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    names = set()
    for node in tree.body:  # module scope ONLY -- a function-local import is the point
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class TestStandalone:
    """D4: `cw/testing.py` is one file, stdlib-only, copyable into any repo."""

    def test_module_scope_imports_are_exactly_the_allowed_stdlib_set(self):
        found = _module_scope_imports(testing.__file__)
        assert found == ALLOWED_MODULE_IMPORTS

    def test_it_imports_no_cw_and_no_i2_at_module_scope(self):
        found = _module_scope_imports(testing.__file__)
        assert "cw" not in found and "i2" not in found

    def test_parity_imports_cw_lazily_inside_the_function(self):
        """The one cw import in the file is inside `parity`, which is what D4 allows."""
        source = open(testing.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        inside = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cw")
        ]
        assert inside, "parity must import cw somewhere"
        all_indented = all(node.col_offset > 0 for node in inside)
        assert all_indented, "a cw import is at module scope"

    def test_the_file_really_runs_standalone(self, tmp_path):
        """Copy it somewhere with no cw on the path and use it. That is the guarantee."""
        copy = tmp_path / "testing.py"
        copy.write_text(
            open(testing.__file__, encoding="utf-8").read(), encoding="utf-8"
        )
        result = subprocess.run(
            [
                P,
                "-c",
                "import sys, testing; "
                "assert not [m for m in sys.modules if m.split('.')[0] == 'cw']; "
                "print(testing.normalise_usage('usage: x [-h]\\n\\nbody'))",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(tmp_path),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "usage: x [-h]"


# =======================================================================================
# Normalisation
# =======================================================================================


class TestNormalisation:
    """The three normalisations, and the line each one refuses to cross."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("a\r\nb", "a\nb"),
            ("a\rb", "a\nb"),
            ("a\nb", "a\nb"),
            ("", ""),
        ],
    )
    def test_newlines_normalise_for_the_windows_runner(self, text, expected):
        assert testing.normalise_text(text) == expected

    def test_a_crlf_golden_asserts_clean_against_lf_output(self):
        """The Windows decision (option A), end to end at the comparator."""
        recorded = {
            "tier": 1,
            "returncode": 0,
            "stdout": "one\r\ntwo\r\n",
            "stderr": "",
            "usage": "",
        }
        fresh = dict(recorded, stdout="one\ntwo\n")
        assert testing.compare_case(recorded, fresh) == ""

    def test_usage_is_collapsed_so_it_is_columns_independent(self):
        narrow = "usage: prog\n       [--alpha]\n       [--beta] x\n\nbody"
        wide = "usage: prog [--alpha] [--beta] x\n\nbody"
        assert testing.normalise_usage(narrow) == testing.normalise_usage(wide)

    def test_usage_stops_at_the_first_blank_line(self):
        text = "usage: prog [-h]\n\npositional arguments:\n  usage: not this\n"
        assert testing.normalise_usage(text) == "usage: prog [-h]"

    def test_addresses_are_scrubbed_because_a_heap_pointer_is_not_a_behaviour(self):
        assert (
            testing.scrub_addresses("<list_iterator object at 0x1017642e0>")
            == "<list_iterator object at 0xADDR>"
        )

    def test_scrubbing_leaves_ordinary_text_alone(self):
        assert testing.scrub_addresses("exit code 0x0 is not a thing") == (
            "exit code 0x0 is not a thing"
        )


# =======================================================================================
# Cases: both spellings, because shlex is POSIX-only
# =======================================================================================


class TestReadCases:
    """`read_cases` parses a shlex line AND a JSON list -- issue #14's Windows path."""

    def test_both_spellings_produce_the_same_argv(self, tmp_path):
        path = tmp_path / "cases.txt"
        path.write_text(
            textwrap.dedent(
                """\
                # a comment, and a blank line follow

                quickstart . --ignore
                ["quickstart", ".", "--ignore"]
                ["with a space", "and \\"quotes\\""]
                """
            ),
            encoding="utf-8",
        )
        cases = testing.read_cases(path)
        assert cases[0] == cases[1] == ["quickstart", ".", "--ignore"]
        assert cases[2] == ["with a space", 'and "quotes"']

    def test_comments_and_blank_lines_are_skipped(self, tmp_path):
        path = tmp_path / "cases.txt"
        path.write_text("# nothing\n\n  \nreal\n", encoding="utf-8")
        assert testing.read_cases(path) == [["real"]]


# =======================================================================================
# The round trip: characterize a real CLI, mutate it, and assert replay notices
# =======================================================================================

TOY_CLI = '''\
"""A toy argparse CLI, so the round trip runs against a real console script."""
import argparse, sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="toy", description="A toy.")
    parser.add_argument("name")
    parser.add_argument("--loudly", action="store_true")
    args = parser.parse_args(argv)
    print(f"HELLO {args.name}" if args.loudly else f"hello {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

TOY_CASES = [["world"], ["world", "--loudly"], ["--help"], []]


@pytest.fixture
def toy(tmp_path):
    """A real console script on disk, plus the command that runs it."""
    path = tmp_path / "toy.py"
    path.write_text(TOY_CLI, encoding="utf-8")
    return path, [P, str(path)]


class TestRoundTrip:
    """characterize -> replay -> mutate -> replay fails. The harness's own falsifiability."""

    def test_characterize_records_all_three_tiers(self, toy):
        _, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        assert golden["cw_golden"] == testing.GOLDEN_VERSION
        assert [case["argv"] for case in golden["cases"]] == TOY_CASES
        greeting = golden["cases"][0]
        assert greeting["returncode"] == 0
        assert greeting["stdout"] == "hello world\n"
        assert greeting["tier"] == 1
        assert golden["cases"][2]["tier"] == 3, "--help is tier 3"
        assert golden["cases"][3]["usage"].startswith("usage: toy")

    def test_replay_of_an_unchanged_cli_is_identical(self, toy):
        _, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        assert all(r["status"] == "identical" for r in testing.replay(golden))
        testing.assert_replay(golden)  # does not raise

    def test_replay_notices_a_mutation_and_says_what_changed(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(TOY_CLI.replace("hello {", "howdy {"), encoding="utf-8")
        with pytest.raises(AssertionError) as caught:
            testing.assert_replay(golden)
        message = str(caught.value)
        assert "1 of 4 cases changed behaviour" in message
        assert "- hello world" in message and "+ howdy world" in message

    def test_replay_notices_a_lost_flag(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(
            TOY_CLI.replace('parser.add_argument("--loudly", action="store_true")', ""),
            encoding="utf-8",
        )
        statuses = [r["status"] for r in testing.replay(golden)]
        assert statuses.count("differs") >= 2, statuses

    def test_a_tier_three_help_change_is_NOT_a_failure(self, toy):
        """The whole point of tier 3: help text moves, and the gate does not go red."""
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(
            TOY_CLI.replace('description="A toy."', 'description="Toy!"'), "utf-8"
        )
        assert all(r["status"] == "identical" for r in testing.replay(golden))

    def test_but_diff_help_reports_it_advisorily(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(
            TOY_CLI.replace('description="A toy."', 'description="Toy!"'), "utf-8"
        )
        advisory = testing.diff_help(golden)
        assert "-A toy." in advisory and "+Toy!" in advisory

    def test_diff_help_is_empty_when_nothing_moved(self, toy):
        _, prog = toy
        assert testing.diff_help(testing.characterize(prog, TOY_CASES)) == ""


class TestExpectDiff:
    """`expect_diff` marks an intended break -- in both directions."""

    def test_an_intended_break_is_not_a_failure(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(TOY_CLI.replace("hello {", "howdy {"), encoding="utf-8")
        testing.assert_replay(golden, expect_diff=[["world"]])

    def test_an_intended_break_that_did_not_happen_IS_a_failure(self, toy):
        """A migration note claiming a break that did not occur is also wrong."""
        _, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        with pytest.raises(AssertionError, match="unchanged"):
            testing.assert_replay(golden, expect_diff=[["world"]])

    def test_expect_diff_accepts_a_shlex_string_too(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(TOY_CLI.replace("hello {", "howdy {"), encoding="utf-8")
        testing.assert_replay(golden, expect_diff=["world"])


class TestGoldenFile:
    """The committed artefact: stable, versioned, and self-describing."""

    def test_written_goldens_are_stable_under_re_recording(self, toy, tmp_path):
        _, prog = toy
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        testing.characterize(prog, TOY_CASES, out_path=first)
        testing.characterize(prog, TOY_CASES, out_path=second)
        assert first.read_text() == second.read_text()

    def test_a_golden_is_sorted_and_newline_terminated(self, toy, tmp_path):
        _, prog = toy
        path = tmp_path / "g.json"
        testing.characterize(prog, TOY_CASES, out_path=path)
        text = path.read_text()
        assert text.endswith("\n")
        assert json.loads(text) == json.loads(text)  # parses
        assert text.index('"cases"') < text.index('"prog"'), "keys are sorted"

    def test_loading_something_that_is_not_a_golden_says_so(self):
        with pytest.raises(ValueError, match="not a cw golden"):
            testing.load_golden({"cases": []})

    def test_a_golden_from_a_future_format_says_to_re_record(self):
        with pytest.raises(ValueError, match="Re-record"):
            testing.load_golden({"cw_golden": 99, "cases": []})

    def test_a_timeout_is_reported_rather_than_raised(self, tmp_path):
        slow = tmp_path / "slow.py"
        slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        golden = testing.characterize([P, str(slow)], [[]], timeout=0.4)
        assert golden["cases"][0]["returncode"] is None
        assert "timed out" in golden["cases"][0]["stderr"]


class TestPinnedEnv:
    """Recording pins the environment; it must also put it back."""

    def test_columns_is_pinned_inside_and_restored_outside(self):
        before = os.environ.get("COLUMNS")
        with testing.pinned_env():
            assert os.environ["COLUMNS"] == testing.DFLT_COLUMNS
        assert os.environ.get("COLUMNS") == before

    def test_argcomplete_is_removed_so_it_cannot_hijack_a_recording(self):
        os.environ["_ARGCOMPLETE"] = "1"
        try:
            with testing.pinned_env():
                assert "_ARGCOMPLETE" not in os.environ
            assert os.environ["_ARGCOMPLETE"] == "1"
        finally:
            os.environ.pop("_ARGCOMPLETE", None)


class TestExitStatus:
    """`capture` reproduces what the interpreter does with a `SystemExit`."""

    @pytest.mark.parametrize(
        "call,code,err",
        [
            (lambda: None, 0, ""),
            (lambda: 0, 0, ""),
            (lambda: 3, 3, ""),
            (lambda: (_ for _ in ()).throw(SystemExit()), 0, ""),
            (lambda: (_ for _ in ()).throw(SystemExit(4)), 4, ""),
            (lambda: (_ for _ in ()).throw(SystemExit("bye")), 1, "bye\n"),
        ],
    )
    def test_the_six_shapes_an_exit_can_take(self, call, code, err):
        outcome = testing.capture(call)
        assert (outcome["returncode"], outcome["stderr"]) == (code, err)

    def test_a_crash_is_recorded_without_a_machine_specific_traceback(self):
        outcome = testing.capture(lambda: {}["nope"])
        assert outcome["returncode"] == 1
        assert outcome["stderr"] == "KeyError: 'nope'\n"
        assert 'File "' not in outcome["stderr"]


# =======================================================================================
# The gate itself
# =======================================================================================


class TestParity:
    """`python -m cw.testing parity` -- the definition of v1."""

    def test_it_passes(self):
        out = io.StringIO()
        assert testing.parity(out=out) == 0
        assert out.getvalue().strip().endswith(": identical")

    def test_it_reports_real_derived_numbers(self):
        from cw.tests import fixtures

        out = io.StringIO()
        testing.parity(out=out)
        assert (
            f"{len(fixtures.SHAPES)} shapes / {fixtures.case_count()} cases"
            in out.getvalue()
        )

    def test_an_empty_goldens_directory_fails_rather_than_passing_vacuously(
        self, tmp_path
    ):
        out = io.StringIO()
        assert testing.parity(tmp_path, out=out) == 1
        assert "no goldens" in out.getvalue()

    def test_a_tampered_golden_makes_it_fail_with_a_readable_diff(self, tmp_path):
        """The gate must be able to go red, and to say why in words."""
        source = os.path.join(testing.DFLT_GOLDENS_DIR, "contract.json")
        golden = json.load(open(source, encoding="utf-8"))
        for case in golden["cases"]:
            if case["argv"] == ["returns-dict"]:
                case["stdout"] = "a\nb\n"  # as if a dict were iterated
        testing.write_golden(golden, tmp_path / "contract.json")
        out = io.StringIO()
        assert testing.parity(tmp_path, out=out) == 1
        report = out.getvalue()
        assert "1 DIFFER" in report
        assert "$ returns-dict" in report
        assert "{'a': 1, 'b': 2}" in report

    def test_it_runs_as_a_subprocess_and_exits_zero(self):
        result = subprocess.run(
            [P, "-m", "cw.testing", "parity"], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().endswith(": identical")

    def test_the_gate_pulls_no_argh(self):
        """The CI claim, asserted by the process rather than by convention."""
        result = subprocess.run(
            [
                P,
                "-c",
                "import sys; from cw.testing import parity; import io; "
                "parity(out=io.StringIO()); "
                "print(sorted(m for m in sys.modules if m.split('.')[0] == 'argh'))",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "[]"


class TestCommandLine:
    """`python -m cw.testing` -- built with argparse, because it must not import cw."""

    def test_no_command_prints_usage_and_exits_zero(self):
        result = subprocess.run([P, "-m", "cw.testing"], capture_output=True, text=True)
        assert result.returncode == 0
        assert result.stdout.startswith("usage: python -m cw.testing")

    def test_characterize_and_replay_from_the_command_line(self, toy, tmp_path):
        path, prog = toy
        cases = tmp_path / "cases.txt"
        cases.write_text('["world"]\n["world", "--loudly"]\n', encoding="utf-8")
        golden = tmp_path / "toy.json"
        record = subprocess.run(
            [
                P,
                "-m",
                "cw.testing",
                "characterize",
                f"{P} {path}",
                "--cases",
                str(cases),
                "-o",
                str(golden),
            ],
            capture_output=True,
            text=True,
        )
        assert record.returncode == 0, record.stderr
        assert "recorded 2 cases" in record.stdout

        again = subprocess.run(
            [P, "-m", "cw.testing", "replay", str(golden)],
            capture_output=True,
            text=True,
        )
        assert again.returncode == 0, again.stdout
        assert "2/2 identical" in again.stdout

        path.write_text(TOY_CLI.replace("hello {", "howdy {"), encoding="utf-8")
        broken = subprocess.run(
            [P, "-m", "cw.testing", "replay", str(golden)],
            capture_output=True,
            text=True,
        )
        assert broken.returncode == 1
        assert "1/2 identical" in broken.stdout


class TestCommandLineInProcess:
    """`main()` called directly, so the CLI's own branches are covered rather than shelled.

    `TestCommandLine` runs the same commands as subprocesses, which is the honest end-to-end
    check but leaves `main` and `_cli` invisible to coverage. Both matter: a subprocess proves
    the entry point exists, and this proves each branch of it does something.
    """

    def test_parity_verbose_names_every_shape(self, capsys):
        assert testing.main(["parity", "-v"]) == 0
        report = capsys.readouterr().out
        from cw.tests import fixtures

        for name in fixtures.SHAPES:
            assert f"  {name}: " in report

    def test_parity_over_an_explicit_goldens_directory(self, capsys):
        assert testing.main(["parity", testing.DFLT_GOLDENS_DIR]) == 0
        assert capsys.readouterr().out.strip().endswith(": identical")

    def test_no_command_prints_usage(self, capsys):
        assert testing.main([]) == 0
        assert capsys.readouterr().out.startswith("usage: python -m cw.testing")

    def test_characterize_replay_and_diff_help(self, toy, tmp_path, capsys):
        path, prog = toy
        cases = tmp_path / "cases.txt"
        cases.write_text('["world"]\n["--help"]\n', encoding="utf-8")
        golden = tmp_path / "toy.json"

        assert (
            testing.main(
                [
                    "characterize",
                    f"{P} {path}",
                    "--cases",
                    str(cases),
                    "-o",
                    str(golden),
                    "--note",
                    "before the migration",
                ]
            )
            == 0
        )
        assert "recorded 2 cases" in capsys.readouterr().out
        assert testing.load_golden(golden)["note"] == "before the migration"

        assert testing.main(["replay", str(golden)]) == 0
        assert "2/2 identical" in capsys.readouterr().out

        assert testing.main(["diff-help", str(golden)]) == 0
        assert "no --help changes" in capsys.readouterr().out

        path.write_text(TOY_CLI.replace("hello {", "howdy {"), encoding="utf-8")
        assert testing.main(["replay", str(golden)]) == 1
        assert "1/2 identical" in capsys.readouterr().out

        assert testing.main(["replay", str(golden), "--expect-diff", "world"]) == 0

    def test_characterize_takes_a_cases_FILE_as_well_as_a_list(self, toy, tmp_path):
        """`characterize(cases=<path>)` -- the spelling the command line uses."""
        _, prog = toy
        cases = tmp_path / "cases.txt"
        cases.write_text('["world"]\n', encoding="utf-8")
        golden = testing.characterize(prog, cases)
        assert [case["argv"] for case in golden["cases"]] == [["world"]]

    def test_a_stream_the_command_already_closed_does_not_break_the_capture(self):
        """`_flush` forgives a closed stream, because a CLI is allowed to close its own."""

        def closes_its_own_stdout():
            sys.stdout.close()
            return 0

        assert testing.capture(closes_its_own_stdout)["returncode"] == 0


class TestAGoldenReplaysOnAnyCPython:
    """The gate's goldens were recorded on one interpreter and asserted on the matrix.

    cw's CI runs 3.10 and 3.12, and argparse's *own* rendering differs between them. Those
    differences belong to CPython, not to cw -- argh and cw print the same bytes as each
    other on any one interpreter -- so `canonical_argparse_text` neutralises exactly two of
    them and nothing else. Without it `python -m cw.testing parity` is red on 3.10 with a
    correct cw, which is the worst kind of gate: one that cries wolf.
    """

    def test_the_invalid_choice_quoting_change_is_forgiven(self):
        """argparse quoted its choices up to 3.11 and stopped in 3.12."""
        upto_311 = "x: error: invalid choice: 'q' (choose from 'a', 'b')"
        since_312 = "x: error: invalid choice: 'q' (choose from a, b)"
        assert testing.canonical_argparse_text(upto_311) == since_312
        assert testing.canonical_argparse_text(since_312) == since_312

    def test_the_usage_block_rewrap_is_forgiven(self):
        """3.13 stopped wrapping a trailing `...` onto its own line."""
        upto_312 = "usage: p [-h]\n       {a,b}\n       ...\n\nnext"
        since_313 = "usage: p [-h] {a,b} ...\n\nnext"
        assert testing.canonical_argparse_text(upto_312) == since_313
        assert testing.canonical_argparse_text(since_313) == since_313

    def test_a_case_differing_only_by_interpreter_compares_equal(self):
        recorded = {
            "tier": 1,
            "returncode": 2,
            "stdout": "",
            "stderr": "err: invalid choice: 'q' (choose from 'a', 'b')\n",
            "usage": "",
        }
        fresh = dict(recorded, stderr="err: invalid choice: 'q' (choose from a, b)\n")
        assert testing.compare_case(recorded, fresh) == ""

    def test_it_forgives_ONLY_those_two_and_still_sees_a_real_difference(self):
        """The normalisation must not have quietly become `assert True`."""
        recorded = {
            "tier": 1,
            "returncode": 0,
            "stdout": "hi\n",
            "stderr": "",
            "usage": "",
        }
        # a different choice set is a real grammar change, not a rendering difference
        a = {"tier": 1, "returncode": 2, "stdout": "", "stderr": "", "usage": ""}
        assert testing.compare_case(recorded, dict(recorded, stdout="ho\n")) != ""
        assert testing.compare_case(recorded, dict(recorded, returncode=1)) != ""
        assert (
            testing.compare_case(
                dict(a, stderr="(choose from 'a', 'b')"),
                dict(a, stderr="(choose from 'a', 'c')"),
            )
            != ""
        )
        # and the usage collapse must not swallow a missing option
        assert (
            testing.compare_case(
                dict(a, stdout="usage: p [-h] [-v]\n"),
                dict(a, stdout="usage: p [-h]\n"),
            )
            != ""
        )
