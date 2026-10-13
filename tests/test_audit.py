"""``cw.audit``: the gate for a migration that is finished in the metadata but not the source.

The motivating case (i2mint/cw#41): a CLI migrated with a zero ``--help`` diff still had
``from argh import CommandError`` and a live ``argh.dispatch_commands`` under a
``__main__`` guard. No golden can see either; reading the source can.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cw.audit import (
    Finding,
    assert_no_argh,
    audit,
    audit_dependencies,
    audit_source,
    format_findings,
)

REPO = Path(__file__).resolve().parents[1]


def codes(source):
    return [f.code for f in audit_source(textwrap.dedent(source))]


class TestImports:
    @pytest.mark.parametrize(
        "line",
        [
            "import argh",
            "import argh.assembling",
            "import argh as a",
            "from argh import arg",
            "from argh.assembling import NameMappingPolicy",
        ],
    )
    def test_every_form_of_importing_argh_is_found(self, line):
        assert codes(line) == ["import"]

    def test_an_import_inside_try_except_is_still_found(self):
        # priv's actual shape: the fallback made it look harmless.
        source = """
        try:
            from argh import CommandError
        except ImportError:
            CommandError = ValueError
        """
        assert codes(source) == ["command-error", "import"]

    def test_the_command_error_finding_explains_class_identity(self):
        (finding, _) = sorted(
            audit_source("from argh import CommandError"), key=lambda f: f.code
        )
        assert finding.code == "command-error"
        assert "is not cw.CommandError" in finding.message

    def test_command_error_through_an_alias_is_found(self):
        assert "command-error" in codes("import argh as a\nraise a.CommandError('x')")

    def test_cw_compat_aliased_as_argh_is_not_argh(self):
        source = "from cw import compat as argh\nargh.dispatch_commands([f])\n"
        assert codes(source) == []

    def test_a_mention_in_a_string_or_comment_is_not_an_import(self):
        assert codes('x = "import argh"  # from argh import arg\n') == []

    def test_the_pragma_exempts_its_line_only(self):
        source = "import argh  # cw-audit: ignore\nimport argh\n"
        assert [f.line for f in audit_source(source)] == [2]

    def test_a_file_that_does_not_parse_is_a_finding_not_a_crash(self):
        assert codes("def (:\n") == ["syntax"]


class TestDispatch:
    def test_dispatch_commands_through_the_module(self):
        assert codes("import argh\nargh.dispatch_commands([f])") == [
            "import",
            "dispatch",
        ]

    def test_a_name_imported_from_argh_is_tracked(self):
        assert "dispatch" in codes("from argh import dispatch_command as d\nd(f)")

    def test_arghparser_construction_is_found(self):
        assert "dispatch" in codes("import argh\np = argh.ArghParser()")

    def test_main_guard_is_named_as_reachable(self):
        source = """
        import argh
        if __name__ == "__main__":
            argh.dispatch_commands([f])
        """
        (dispatch,) = [
            f for f in audit_source(textwrap.dedent(source)) if f.code == "dispatch"
        ]
        assert "python -m" in dispatch.message

    def test_a_dispatch_outside_a_guard_does_not_claim_the_guard(self):
        (dispatch,) = [
            f
            for f in audit_source("import argh\nargh.dispatch(p)")
            if f.code == "dispatch"
        ]
        assert "python -m" not in dispatch.message


class TestDiscardedExit:
    @pytest.mark.parametrize(
        "source",
        [
            "import cw\ncw.dispatch(f)",
            "import cw as c\nc.run(f)",
            "from cw import dispatch\ndispatch(f)",
            "import cw.cli\ncw.cli.dispatch(f)",
        ],
    )
    def test_a_bare_dispatch_statement_is_found(self, source):
        assert codes(source) == ["discarded-exit"]

    @pytest.mark.parametrize(
        "source",
        [
            "import cw\nraise SystemExit(cw.dispatch(f))",
            "import cw, sys\nsys.exit(cw.dispatch(f))",
            "import cw\ncode = cw.dispatch(f)",
            "import cw\ncw.dispatch(f, out=buf)",
            "import cw\ncw.dispatch(f, standalone=False)",
            "dispatch(f)",  # not cw's
            "import other\nother.dispatch(f)",
        ],
    )
    def test_used_captured_or_foreign_dispatch_is_not(self, source):
        assert codes(source) == []

    def test_test_files_may_drop_the_code(self, tmp_path):
        (tmp_path / "test_x.py").write_text("import cw\ncw.dispatch(f)\n")
        (tmp_path / "x.py").write_text("import cw\ncw.dispatch(f)\n")
        assert [f.path for f in audit(tmp_path)] == ["x.py"]


class TestDependencies:
    @pytest.mark.parametrize(
        "line",
        [
            'dependencies = ["argh"]',
            '    "argh>=0.26",',
            "    'argh[completion]==0.31.3',",
            '"argh ; python_version < \\"3.12\\""',
            "argh",
            "argh>=0.26  # old",
            "argh @ git+https://example.com/argh.git",
        ],
    )
    def test_argh_as_a_requirement(self, line):
        assert [f.code for f in audit_dependencies(line)] == ["dependency"]

    @pytest.mark.parametrize(
        "text",
        [
            'name = "argh"',
            'keywords = ["argh"]',
            'keywords = [\n    "argh",\n]',
            'description = "argh is a thing"',
            'dependencies = ["arghh", "argh-extra", "x-argh"]',
            "# argh>=1",
            '"argh>=1",  # cw-audit: ignore',
        ],
    )
    def test_things_that_are_not_a_requirement(self, text):
        assert audit_dependencies(text) == []

    def test_reports_the_line(self):
        text = '[project]\nname = "x"\ndependencies = [\n  "a",\n  "argh",\n]\n'
        assert [f.line for f in audit_dependencies(text)] == [5]


class TestTree:
    def make_tree(self, root):
        (root / "pkg").mkdir()
        (root / "pkg" / "git_ops.py").write_text(
            "import argh\nif __name__ == '__main__':\n    argh.dispatch_commands([f])\n"
        )
        (root / "pyproject.toml").write_text('dependencies = ["argh"]\n')
        (root / "requirements-dev.txt").write_text("pytest\nargh\n")
        (root / ".venv").mkdir()
        (root / ".venv" / "bad.py").write_text("import argh\n")

    def test_finds_all_three_kinds_and_skips_excluded_dirs(self, tmp_path):
        self.make_tree(tmp_path)
        found = {(f.path, f.line, f.code) for f in audit(tmp_path)}
        assert found == {
            ("pkg/git_ops.py", 1, "import"),
            ("pkg/git_ops.py", 3, "dispatch"),
            ("pyproject.toml", 1, "dependency"),
            ("requirements-dev.txt", 2, "dependency"),
        }

    def test_a_single_file_can_be_audited(self, tmp_path):
        self.make_tree(tmp_path)
        assert {f.code for f in audit(tmp_path / "pkg" / "git_ops.py")} == {
            "import",
            "dispatch",
        }

    def test_assert_no_argh_lists_what_it_found(self, tmp_path):
        self.make_tree(tmp_path)
        with pytest.raises(AssertionError, match=r"git_ops.py:1: import"):
            assert_no_argh(tmp_path)

    def test_a_clean_tree_passes(self, tmp_path):
        (tmp_path / "ok.py").write_text("import cw\nraise SystemExit(cw.dispatch(f))\n")
        assert_no_argh(tmp_path)
        assert format_findings(audit(tmp_path)) == "no residual argh found."

    def test_finding_formats_as_a_compiler_line(self):
        assert str(Finding("a.py", 3, "import", "m")) == "a.py:3: import: m"


class TestCommand:
    def run(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "cw", "audit", *map(str, argv)],
            capture_output=True,
            text=True,
        )

    def test_exit_1_and_a_report_when_argh_is_left(self, tmp_path):
        (tmp_path / "m.py").write_text("from argh import CommandError\n")
        result = self.run(tmp_path)
        assert result.returncode == 1
        assert "m.py:1: command-error" in result.stdout

    def test_exit_0_when_clean(self, tmp_path):
        (tmp_path / "m.py").write_text("import cw\n")
        result = self.run(tmp_path)
        assert (result.returncode, result.stdout) == (0, "no residual argh found.\n")

    def test_exclude_adds_a_directory_to_skip(self, tmp_path):
        (tmp_path / "legacy").mkdir()
        (tmp_path / "legacy" / "m.py").write_text("import argh\n")
        assert self.run(tmp_path).returncode == 1
        assert self.run(tmp_path, "--exclude", "legacy,other").returncode == 0


def test_cw_itself_ships_no_residual_argh():
    """cw's own package and metadata are the first consumer of the gate.

    (The *tests* import real argh on purpose -- they are the differential suite -- so the
    scope is the package, plus the metadata, where the dev-only pin carries a pragma.)
    """
    assert_no_argh(REPO / "cw")
    assert_no_argh(REPO / "pyproject.toml")
