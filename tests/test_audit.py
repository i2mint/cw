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
        assert codes("def (:\n") == ["unparsable"]


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
        "text",
        [
            'dependencies = ["argh"]',
            'dependencies = [\n    "argh>=0.26",\n]',
            "dependencies = [\n    'argh[completion]==0.31.3',\n]",
            "dependencies = ['argh; python_version < \"3.12\"']",
            '[project.optional-dependencies]\ndev = ["argh"]',
            '[dependency-groups]\ndev = [\n  "argh",\n]',
            '[build-system]\nrequires = ["setuptools", "argh"]',
            '[tool.poetry.dependencies]\nargh = "^0.26"',
            '[tool.poetry.group.dev.dependencies]\nargh = {version = "^0.26"}',
            "[options]\ninstall_requires = argh",
            "[options]\ninstall_requires =\n    x\n    argh>=0.26",
            "[options.extras_require]\ncli = argh>=0.26",
            'setup(install_requires=["argh"])',
            "setup(\n    install_requires=[\n        'argh',\n    ],\n)",
        ],
    )
    def test_argh_as_a_requirement(self, text):
        assert [f.code for f in audit_dependencies(text)] == ["dependency"]

    @pytest.mark.parametrize(
        "line",
        [
            "argh",
            "argh>=0.26  # old",
            "argh @ git+https://example.com/argh.git",
            'argh; python_version < "3.12"',
            "-e git+https://example.com/x.git#egg=argh",
        ],
    )
    def test_argh_in_a_requirements_file(self, line):
        assert [f.code for f in audit_dependencies(line, always=True)] == ["dependency"]

    @pytest.mark.parametrize(
        "text",
        [
            'name = "argh"',
            '[project]\nkeywords = ["argh"]',
            'keywords = [\n    "argh",\n]',
            'description = "argh is a thing"',
            'dependencies = ["arghh", "argh-extra", "x-argh"]',
            "# argh>=1",
            'dependencies = ["argh>=1"]  # cw-audit: ignore',
            '[tool.ruff.lint.isort]\nknown-third-party = ["argh"]',
            '[[tool.mypy.overrides]]\nmodule = "argh"',
            '[tool.deptry.per_rule_ignores]\nDEP002 = ["argh"]',
            "setup(long_description='argh is a thing', name='argh')",
        ],
    )
    def test_things_that_are_not_a_requirement(self, text):
        assert audit_dependencies(text) == []
        assert audit_dependencies(text.replace("\n", "\n# ")) == []

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


class TestReviewRegressions:
    """Each of these was a way the gate said 'clean' (or crashed) with argh still present."""

    def test_real_subpackages_named_like_build_dirs_are_audited(self, tmp_path):
        for name in ("build", "dist", "env", "venv"):
            (tmp_path / "pkg" / name).mkdir(parents=True)
            (tmp_path / "pkg" / name / "m.py").write_text("import argh\n")
        assert len(audit(tmp_path)) == 4

    def test_top_level_build_dirs_and_virtualenvs_are_skipped(self, tmp_path):
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "m.py").write_text("import argh\n")
        (tmp_path / "somewhere" / "lib").mkdir(parents=True)
        (tmp_path / "somewhere" / "pyvenv.cfg").write_text("home = /usr\n")
        (tmp_path / "somewhere" / "lib" / "m.py").write_text("import argh\n")
        assert audit(tmp_path) == []

    def test_non_utf8_source_is_read_by_its_declared_encoding(self, tmp_path):
        source = "# -*- coding: latin-1 -*-\n# caf\xe9\nimport argh\n"
        (tmp_path / "m.py").write_bytes(source.encode("latin-1"))
        assert [(f.line, f.code) for f in audit(tmp_path)] == [(3, "import")]

    def test_an_undecodable_file_is_reported_not_skipped(self, tmp_path):
        (tmp_path / "m.py").write_bytes(b"\xff\xfe\x00bad = 1\n")
        assert {f.code for f in audit(tmp_path)} == {"unparsable"}

    def test_a_utf8_bom_is_not_a_syntax_error(self, tmp_path):
        (tmp_path / "m.py").write_bytes(b"\xef\xbb\xbfimport argh\n")
        (tmp_path / "requirements.txt").write_bytes(b"\xef\xbb\xbfargh\n")
        assert {(f.path, f.code) for f in audit(tmp_path)} == {
            ("m.py", "import"),
            ("requirements.txt", "dependency"),
        }

    def test_an_ancestor_named_tests_does_not_exempt_the_tree(self, tmp_path):
        root = tmp_path / "tests" / "myrepo"
        (root / "pkg").mkdir(parents=True)
        (root / "pkg" / "cli.py").write_text("import cw\ncw.dispatch({})\n")
        assert [f.code for f in audit(root)] == ["discarded-exit"]

    def test_a_tests_directory_inside_the_tree_still_exempts_tests(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "m.py").write_text("import cw\ncw.dispatch({})\n")
        assert audit(tmp_path) == []

    @pytest.mark.parametrize(
        "name",
        ["dev-requirements.txt", "requirements-dev.in", "requirements/base.txt"],
    )
    def test_requirements_files_by_any_usual_name(self, tmp_path, name):
        target = tmp_path / name
        target.parent.mkdir(exist_ok=True)
        target.write_text("pytest\nargh\n")
        assert [(f.path, f.line) for f in audit(tmp_path)] == [(name, 2)]

    @pytest.mark.parametrize(
        "source",
        [
            "from cw import cli\ncli.dispatch(f)",
            "import cw\ncw.dispatch(f, standalone=True)",
        ],
    )
    def test_more_ways_to_drop_the_exit_code(self, source):
        assert codes(source) == ["discarded-exit"]

    @pytest.mark.parametrize(
        "source, expected",
        [
            (
                "import argh.dispatching\nargh.dispatching.dispatch_commands([f])",
                {"import", "dispatch"},
            ),
            (
                "from argh import dispatching\ndispatching.dispatch_commands([f])",
                {"import", "dispatch"},
            ),
            (
                "from argh import exceptions\nraise exceptions.CommandError('x')",
                {"import", "command-error"},
            ),
            (
                "from argh import *\ndispatch_commands([f])\nraise CommandError('x')",
                {"import", "dispatch", "command-error"},
            ),
        ],
    )
    def test_argh_submodules_and_star_imports_are_tracked(self, source, expected):
        assert set(codes(source)) == expected

    def test_deep_nesting_is_a_finding_not_a_crash(self):
        source = "x = " + " + ".join(['"a"'] * 5000)
        assert codes(source) in (
            ["unparsable"],
            [],
        )  # depends on the interpreter's limit

    def test_a_nul_byte_is_a_finding_on_every_python(self):
        assert codes("x = 1\0\n") == ["unparsable"]

    def test_symlinked_directories_are_not_followed(self, tmp_path):
        (tmp_path / "m.py").write_text("import argh\n")
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
        assert len(audit(tmp_path)) == 1

    def test_a_missing_path_is_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no such file"):
            audit(tmp_path / "nope")

    def test_the_pragma_may_sit_on_any_line_of_a_multiline_import(self):
        source = "from argh import (  # cw-audit: ignore\n    arg,\n)\n"
        assert audit_source(source) == []
        assert audit_source("x = '# cw-audit: ignore'; import argh") != []

    def test_the_command_reports_a_missing_path_without_a_traceback(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "cw", "audit", str(tmp_path / "nope")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Traceback" not in result.stderr and "no such file" in result.stderr


class TestSecondReviewRegressions:
    """The rewrite of the dependency scan must not lose what the first version caught."""

    @pytest.mark.parametrize(
        "source",
        [
            'setup(name="x", install_requires=["argh"])',
            'setup(\n    name="x", install_requires=["argh"],\n)',
            'REQUIREMENTS = ["argh>=0.26"]\nsetup(install_requires=REQUIREMENTS)',
            'import setuptools\nsetuptools.setup(extras_require={"cli": ["argh"]})',
            'setup(**{"install_requires": ["argh"]})'.replace("**{", "x={"),
        ],
    )
    def test_setup_py_is_read_with_ast(self, tmp_path, source):
        (tmp_path / "setup.py").write_text(source + "\n")
        found = audit(tmp_path)
        # the last parametrization is not a dependency keyword: it must stay clean
        expected = [] if source.startswith("setup(x=") else ["dependency"]
        assert [f.code for f in found] == expected

    def test_setup_py_long_description_is_not_a_dependency(self, tmp_path):
        (tmp_path / "setup.py").write_text(
            "setup(name='argh', long_description='argh', install_requires=['x'])\n"
        )
        assert audit(tmp_path) == []

    @pytest.mark.parametrize(
        "text",
        [
            '[project]\ndependencies = ["requests[socks]>=2",\n    "argh>=0.26",\n]',
            "[options]\ninstall_requires = i2[resource]\n    argh",
            "[options]\ninstall_requires:\n    argh",
            "[options.extras_require]\ncli: argh>=0.26",
            "[options]\ninstall-requires = argh",
            '[project]\ndependencies = ["argh (>=0.26)"]',
            '[tool.hatch.envs.default]\nextra-dependencies = ["argh"]',
            '[tool.uv]\noverride-dependencies = ["argh==0.31"]',
            '[project]\noptional-dependencies.cli = ["argh"]',
            '[tool.poetry]\ndependencies.argh = "^0.26"',
            '[tool.poetry]\ndependencies = { argh = "^0.26", x = "1" }',
        ],
    )
    def test_more_dependency_spellings(self, text):
        assert [f.code for f in audit_dependencies(text)] == ["dependency"]

    def test_a_table_merely_containing_the_word_dependency_is_not_one(self):
        text = '[tool.dependency-check]\nignore = ["argh"]\n[tool.requirements-lint]\nx = ["argh"]'
        assert audit_dependencies(text) == []

    @pytest.mark.parametrize(
        "line",
        [
            "argh (>=0.26)",
            "argh==0.26 \\",
            "argh==0.26 --hash=sha256:abc",
            "git+https://example.com/x.git#egg=argh-0.26",
            "git+https://example.com/x.git#egg=argh&subdirectory=src",
        ],
    )
    def test_more_requirements_file_lines(self, line):
        assert [f.code for f in audit_dependencies(line, always=True)] == ["dependency"]

    def test_a_utf16_requirements_file_is_read(self, tmp_path):
        (tmp_path / "requirements.txt").write_bytes("pytest\nargh\n".encode("utf-16"))
        assert [f.code for f in audit(tmp_path)] == ["dependency"]

    def test_long_generated_chains_are_audited_not_rejected(self):
        source = "import argh\nx = " + " + ".join(["'a'"] * 1500) + "\n"
        assert codes(source) == ["import"]

    def test_the_recursion_limit_is_restored(self):
        before = sys.getrecursionlimit()
        audit_source("x = 1\n")
        assert sys.getrecursionlimit() == before

    def test_an_unreadable_directory_is_a_finding_not_a_crash(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "locked").mkdir()
        (tmp_path / "ok.py").write_text("import argh\n")
        real = Path.iterdir

        def iterdir(self):
            if self.name == "locked":
                raise PermissionError(13, "Permission denied")
            return real(self)

        monkeypatch.setattr(Path, "iterdir", iterdir)
        assert {(f.path, f.code) for f in audit(tmp_path)} == {
            ("ok.py", "import"),
            ("locked", "unparsable"),
        }

    def test_a_dangling_symlink_is_skipped(self, tmp_path):
        (tmp_path / "gone.py").symlink_to(tmp_path / "missing.py")
        assert audit(tmp_path) == []

    def test_command_error_through_an_attribute_chain(self):
        source = "import argh\nraise argh.exceptions.CommandError('x')"
        assert "command-error" in codes(source)
