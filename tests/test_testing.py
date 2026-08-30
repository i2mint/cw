"""`cw.testing` -- the standalone harness, its D4 guarantee, and the parity gate.

The round-trip test is the important one: characterize a toy CLI, mutate it, and assert
`replay` notices. A harness that cannot fail is worse than no harness, because it is
believed.
"""

import ast
import io
import json
import os
import pathlib
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
        results = testing.replay(golden)
        assert not [r for r in results if r["status"] == "differs"]
        testing.assert_replay(golden)  # ... and it does not raise

    def test_but_it_is_no_longer_called_identical_either(self, toy):
        """A changed `--help` body is reported as `help-differs`, not swallowed.

        The defect this closes: swapping a dispatcher for one with a different
        `formatter_class` moves every default's rendering and every multi-paragraph
        description, and touches neither the `usage:` line nor any exit code -- so `replay`
        used to print `N/N identical` on a migration whose `--help` visibly changed.
        """
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(
            TOY_CLI.replace('description="A toy."', 'description="Toy!"'), "utf-8"
        )
        statuses = {r["status"] for r in testing.replay(golden)}
        assert "help-differs" in statuses
        assert "identical" in statuses  # the non-help cases are still identical

    def test_strict_help_makes_it_a_failure(self, toy):
        path, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        path.write_text(
            TOY_CLI.replace('description="A toy."', 'description="Toy!"'), "utf-8"
        )
        bad = [
            r
            for r in testing.replay(golden, strict_help=True)
            if r["status"] == "differs"
        ]
        assert bad and "help:" in bad[0]["diff"]
        with pytest.raises(AssertionError):
            testing.assert_replay(golden, strict_help=True)

    def test_a_pure_rewrap_is_not_reported(self, toy):
        """`normalise_help` is width-independent, so COLUMNS alone never trips it."""
        _, prog = toy
        golden = testing.characterize(prog, TOY_CASES)
        results = testing.replay(golden, env={"COLUMNS": "40"})
        assert all(r["status"] == "identical" for r in results)

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


class TestPinnedStdin:
    """A recording must describe the CLI, not the console that recorded it.

    A CLI with an interactive path -- grub drops into a REPL when the query is omitted,
    `cw.confirm` asks a question -- reads stdin. If the recorded child inherits the
    recorder's stdin, the *same case* records two different facts: at a terminal the child
    blocks on a prompt nobody will answer and the case is recorded as a timeout, while
    under CI or pytest it sees an immediate EOF and records the real behaviour. Then a
    golden recorded in CI fails when a developer replays it locally, for a reason that has
    nothing to do with the CLI.
    """

    READS_STDIN = (
        'import sys\n'
        'try:\n'
        '    line = input("prompt> ")\n'
        'except EOFError:\n'
        '    line = "<EOF>"\n'
        'print("read:", line)\n'
    )

    @pytest.fixture
    def reads_stdin(self, tmp_path):
        path = tmp_path / "reads_stdin.py"
        path.write_text(self.READS_STDIN, encoding="utf-8")
        return [sys.executable, str(path)]

    def test_a_command_that_reads_stdin_records_eof_not_a_timeout(self, reads_stdin):
        golden = testing.characterize(reads_stdin, [[]], timeout=10)
        case = golden["cases"][0]
        assert case["returncode"] == 0
        assert "<EOF>" in case["stdout"]

    def test_the_recording_does_not_depend_on_the_recorder_s_own_stdin(
        self, reads_stdin, tmp_path
    ):
        """Record the same case twice, under two different stdins, and compare."""
        driver = tmp_path / "driver.py"
        driver.write_text(
            "import json, sys\n"
            f"sys.path.insert(0, {str(pathlib.Path(testing.__file__).parent.parent)!r})\n"
            "from cw import testing\n"
            f"golden = testing.characterize({reads_stdin!r}, [[]], timeout=10)\n"
            "print(json.dumps(golden['cases'][0]))\n",
            encoding="utf-8",
        )

        def record_with(stdin):
            done = subprocess.run(
                [sys.executable, str(driver)],
                stdin=stdin,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert done.returncode == 0, done.stderr
            return json.loads(done.stdout)

        # An open pipe nobody writes to is what a terminal looks like to the child.
        read_fd, write_fd = os.pipe()
        try:
            from_terminal = record_with(read_fd)
        finally:
            os.close(read_fd)
            os.close(write_fd)
        with open(os.devnull, "rb") as devnull:
            from_devnull = record_with(devnull)

        assert from_terminal == from_devnull
        assert from_terminal["returncode"] == 0


class TestWindowsConsoleScriptShim:
    """A golden recorded on a Mac must assert on a Windows runner -- as promised.

    `argparse` takes its `prog` from `basename(sys.argv[0])`, and a console script is
    installed as `opsward.exe` on Windows. Without scrubbing, the same CLI at the same
    commit reports `usage: opsward ...` on a Mac and `usage: opsward.EXE ...` on the
    runner, and every case that prints a usage line or an error prefix differs -- 22 of
    31 in the case that found this.

    The simulation is exact rather than mocked: the same toy CLI is written under two
    names, one carrying the Windows extension, and the golden recorded from the plain one
    is replayed against the `.exe` one.

    Both are run as `[sys.executable, path]` rather than as executables in their own
    right. A first version wrote a shebang and `chmod +x`, which is exactly the sort of
    POSIX assumption this class exists to catch -- it failed on the Windows runner with
    `OSError: [WinError 193] %1 is not a valid Win32 application`. It also made the test
    weaker than it looks: with the interpreter in front, the console script is *not* the
    command's first word, so this now covers the harder shape too.
    """

    DERIVES_PROG = (
        "import argparse\n"
        "parser = argparse.ArgumentParser(description='A toy.')\n"
        "parser.add_argument('name')\n"
        "parser.parse_args()\n"
    )

    @pytest.fixture
    def two_names(self, tmp_path):
        """The same CLI as `toy` and as `toy.EXE`, both letting argparse derive prog."""
        plain = tmp_path / "toy"
        plain.write_text(self.DERIVES_PROG, encoding="utf-8")
        windows = tmp_path / "toy.EXE"
        windows.write_text(self.DERIVES_PROG, encoding="utf-8")
        return (
            [sys.executable, str(plain)],
            [sys.executable, str(windows)],
        )

    def test_the_exe_suffix_does_not_make_a_recording_os_specific(self, two_names):
        plain, windows = two_names
        golden = testing.characterize(plain, [["--help"], []], timeout=30)
        assert "toy.EXE" not in json.dumps(golden)
        # Replaying the plain-name golden against the .exe shim must be clean.
        testing.assert_replay(golden, prog=windows, strict_help=True)

    def test_only_the_program_s_own_exe_is_scrubbed(self):
        assert testing.scrub_exe_suffix("run setup.exe", "/bin/toy") == "run setup.exe"
        assert testing.scrub_exe_suffix("toy.exe ran", "/bin/toy") == "toy ran"

    def test_the_program_need_not_be_the_command_s_first_word(self):
        command = ["/usr/bin/python", "/tmp/toy.exe"]
        assert testing.scrub_exe_suffix("usage: toy.EXE [-h]", command) == "usage: toy [-h]"


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


class TestTheCommandStringIsSplitPerPlatform:
    """`shlex.split` is POSIX-only, and a Windows command is nothing but backslashes.

    `characterize 'C:\\py\\python.exe C:\\repo\\tool.py'` used to become
    `['C:pypython.exe', 'C:repotool.py']` -- a command nothing can run, reported as
    `FileNotFoundError: [WinError 2]` with no clue where it came from.
    """

    def test_a_list_is_always_taken_as_is(self):
        assert testing._as_command(["python", "-m", "cw"]) == ["python", "-m", "cw"]

    def test_posix_splits_posix(self, monkeypatch):
        monkeypatch.setattr(testing.os, "name", "posix")
        assert testing._as_command("python -m cw") == ["python", "-m", "cw"]

    def test_windows_keeps_its_backslashes(self, monkeypatch):
        monkeypatch.setattr(testing.os, "name", "nt")
        assert testing._as_command(r"C:\py\python.exe C:\repo\tool.py") == [
            r"C:\py\python.exe",
            r"C:\repo\tool.py",
        ]

    def test_windows_still_honours_quoting_for_a_path_with_a_space(self, monkeypatch):
        monkeypatch.setattr(testing.os, "name", "nt")
        assert testing._as_command(r'"C:\Program Files\py.exe" -m cw') == [
            r"C:\Program Files\py.exe",
            "-m",
            "cw",
        ]
