"""Run the same command set through argh and through cw, and diff what a user sees.

`test_parity.py` diffs the parser argh and cw *build* for one function. This module diffs
what happens when you actually run one: exit code, stdout and stderr, byte for byte, over
subcommands, groups, every egress shape and every error shape.

The parity surface is deliberately observable behaviour and nothing else -- never the
`Namespace`, never the action table -- because cw registers a hyphenated positional as
`add_argument('project_dir', metavar='project-dir')` where argh registers
`add_argument('project-dir')`. That difference is invisible to a user and permitted; a
different flag or a different line of output is not.

argh is a test-only dependency. Nothing under `cw/` imports it.
"""

import os

import argh
import pytest

import cw

from tests.capture import capture

os.environ.setdefault("COLUMNS", "100")


# --------------------------------------------------------------------------- commands


def alpha(x=1):
    """Alpha does a thing."""
    return x


def beta_go(y="z"):
    """Beta."""
    return y


def gamma():
    return "g"


def echo(word, *, loud=False):
    """Echo a word."""
    return word.upper() if loud else word


def r_none():
    return None


def r_zero():
    return 0


def r_false():
    return False


def r_empty():
    return ""


def r_list():
    return [1, 2]


def r_tuple():
    return (1, 2)


def r_dict():
    return {"a": 1, "b": 2}


def r_gen():
    yield "a"
    yield "b"


def r_set():
    return {1}


def r_str():
    return "hello"


def r_int():
    return 42


def r_nested():
    return [[1, 2], {"k": "v"}]


def _cmderr(error_class):
    def command():
        raise error_class("boom")

    return command


def _cmderr7(error_class):
    def command():
        raise error_class("boom", code=7)

    return command


def _sysexit_str(error_class):
    def command():
        raise SystemExit("bye")

    return command


def _sysexit_int(error_class):
    def command():
        raise SystemExit(3)

    return command


def _gen_then_err(error_class):
    def command():
        yield "line-1"
        yield "line-2"
        raise error_class("after streaming")

    return command


#: argh and cw must agree on these one-command results. `map` is excluded on purpose: it
#: is the one shape where `cw.MODERN` deliberately differs, and it has its own test.
RESULT_FUNCS = [
    r_none,
    r_zero,
    r_false,
    r_empty,
    r_list,
    r_tuple,
    r_dict,
    r_gen,
    r_set,
    r_str,
    r_int,
    r_nested,
]

#: Each builds the same command twice, once against each library's `CommandError`, since
#: neither library catches the other's.
ERROR_BUILDERS = [_cmderr, _cmderr7, _sysexit_str, _sysexit_int, _gen_then_err]


# ---------------------------------------------------------------------------- running


#: Defined in `tests/capture.py` so that importing it does not drag in argh.
_capture = capture


def run_argh(build, argv):
    """Build an argh parser with `build(parser)` and dispatch `argv` through it."""

    def call(out, err):
        parser = argh.ArghParser(prog="x")
        build(parser)
        argh.dispatch(parser, list(argv), output_file=out, errors_file=err)
        return 0

    return _capture(call)


def run_cw(obj, argv, **kwargs):
    """Dispatch `argv` against `obj` through cw, capturing everything."""
    return _capture(
        lambda out, err: cw.dispatch(
            obj, list(argv), out=out, err=err, prog="x", **kwargs
        )
    )


def as_process_would(outcome):
    """Normalise the one in-process difference into what the shell would actually see.

    argh lets a `SystemExit` out of `dispatch`, so a `SystemExit('bye')` reaches the
    interpreter, which prints `bye` to stderr and exits 1. cw's `dispatch` returns an
    integer, so it does that printing itself and returns 1. Same two observables, produced
    one stack frame apart -- and this function is the only place the difference is
    forgiven.
    """
    code, out, err = outcome
    if isinstance(code, str):
        return 1, out, err + f"{code}\n"
    return outcome


def assert_same(left, right, label=""):
    """Exit code, stdout and stderr identical, with a readable message when not."""
    for name, a, b in zip(("exit", "stdout", "stderr"), left, right):
        assert a == b, f"{label}{name}: argh={a!r} cw={b!r}"


# ------------------------------------------------------------------------------ tests


@pytest.mark.parametrize("func", RESULT_FUNCS, ids=lambda f: f.__name__)
def test_egress_matches_argh(func):
    """Every result shape prints the way argh prints it (spec section 9 rows 16-18)."""
    assert_same(
        run_argh(lambda p: p.set_default_command(func), []),
        run_cw(func, []),
        label=f"{func.__name__} ",
    )


@pytest.mark.parametrize("builder", ERROR_BUILDERS, ids=lambda b: b.__name__)
def test_errors_match_argh(builder):
    """CommandError, SystemExit and lazy streaming behave identically (row 19)."""
    assert_same(
        as_process_would(
            run_argh(lambda p: p.set_default_command(builder(argh.CommandError)), [])
        ),
        as_process_would(run_cw(builder(cw.CommandError), [])),
        label=f"{builder.__name__} ",
    )


def test_unexpected_exception_keeps_its_traceback():
    """An unexpected failure is a bug, and a bug deserves a traceback -- in both."""

    def boom():
        raise ValueError("unexpected")

    with pytest.raises(ValueError):
        run_argh(lambda p: p.set_default_command(boom), [])
    with pytest.raises(ValueError):
        run_cw(boom, [])


FLAT_ARGVS = [
    [],
    ["--help"],
    ["alpha"],
    ["alpha", "--help"],
    ["alpha", "-x", "5"],
    ["beta-go"],
    ["gamma"],
    ["gamma", "--help"],
    ["nope"],
    ["alpha", "--nope"],
]


@pytest.mark.parametrize("argv", FLAT_ARGVS, ids=lambda a: " ".join(a) or "(none)")
def test_flat_subcommands_match_argh(argv):
    """A list of functions produces the same subcommands, help and errors."""
    functions = [alpha, beta_go, gamma]
    assert_same(
        run_argh(lambda p: p.add_commands(functions), argv),
        run_cw(functions, argv),
        label=f"{argv} ",
    )


GROUP_KWARGS = [
    None,
    {"help": "HELPTEXT", "title": "TITLETEXT"},
    {"help": "Postmortem archive (list, log, forensics)."},
    {"title": "Only a title."},
]

GROUP_ARGVS = [[], ["--help"], ["grp", "--help"], ["grp", "alpha", "-x", "2"]]


@pytest.mark.parametrize(
    "group_kwargs", GROUP_KWARGS, ids=lambda k: str(sorted(k or {}))
)
@pytest.mark.parametrize("argv", GROUP_ARGVS, ids=lambda a: " ".join(a) or "(none)")
def test_group_matches_argh(group_kwargs, argv):
    """`group_kwargs` reaches both `add_parser(help=title)` and `add_subparsers(**it)`.

    The trap this pins: the parent's listing row reads `title`, not `help`, so a group
    whose only `group_kwargs` is `help` shows a blank row there -- and still shows that
    help *inside* the group. Translating `help` onto the parent row would add a line argh
    never shows; dropping it would delete one argh does show.
    """

    def build_argh(parser):
        parser.add_commands(
            [alpha, beta_go], group_name="grp", group_kwargs=group_kwargs
        )

    def build_cw(out, err):
        parser = cw.mk_parser({}, prog="x")
        cw.add_commands(
            parser, [alpha, beta_go], group_name="grp", group_kwargs=group_kwargs
        )
        return cw.run(parser, list(argv), out=out, err=err)

    assert_same(run_argh(build_argh, argv), _capture(build_cw), label=f"{argv} ")


def test_underscore_group_name_is_verbatim():
    """`priv git_ops` stays `git_ops` under ARGH -- the string is in priv's own README."""
    argv = ["--help"]
    assert_same(
        run_argh(lambda p: p.add_commands([alpha], group_name="git_ops"), argv),
        _capture(
            lambda out, err: cw.dispatch(
                {"git_ops": [alpha]}, list(argv), out=out, err=err, prog="x"
            )
        ),
    )


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--help"],
        ["list"],
        ["gen-secret"],
        ["archive", "--help"],
        ["archive", "list"],
    ],
)
def test_mapping_named_commands_match_name_mutation(argv):
    """cw's `{name: func}` form equals what `t/xa` does today by mutating `__name__`.

    argh rejects a Mapping outright, so the thing to compare against is the workaround it
    forces: thirteen `__name__` assignments in `xa/cli.py`, two of which write the same
    string onto different functions. The Mapping form is why those two can coexist.
    """

    def list_cmd():
        """List sessions."""
        return "top-list"

    def archive_list_cmd():
        """List archived sessions."""
        return "archive-list"

    def gen_secret_cmd():
        """Make a secret."""
        return "secret"

    def build_argh(parser):
        list_cmd.__name__ = "list"
        gen_secret_cmd.__name__ = "gen-secret"
        archive_list_cmd.__name__ = "list"
        parser.add_commands([list_cmd, gen_secret_cmd])
        parser.add_commands([archive_list_cmd], group_name="archive")

    commands = {
        "list": list_cmd,
        "gen-secret": gen_secret_cmd,
        "archive": {"list": archive_list_cmd},
    }
    assert_same(run_argh(build_argh, argv), run_cw(commands, argv), label=f"{argv} ")


@pytest.mark.parametrize(
    "argv", [["echo", "hi"], ["echo", "hi", "--loud"], ["echo"], ["echo", "--help"]]
)
def test_ingress_delivers_what_argh_delivers(argv):
    """The arguments `f` actually receives -- the parity surface, not the Namespace."""
    assert_same(
        run_argh(lambda p: p.add_commands([echo]), argv),
        run_cw([echo], argv),
        label=f"{argv} ",
    )


def test_map_is_where_modern_deliberately_differs():
    """`argh_egress` is a type whitelist; `iterable_egress` is the Iterable protocol."""

    def counted():
        return map(str, range(2))

    argh_code, argh_out, _ = run_argh(lambda p: p.set_default_command(counted), [])
    cw_code, cw_out, _ = run_cw(counted, [])
    assert (cw_code, cw_out.startswith("<map object")) == (argh_code, True)

    _, modern_out, _ = run_cw(counted, [], convention=cw.MODERN)
    assert modern_out == "0\n1\n"


def test_a_parameter_named_function_works_where_argh_crashes():
    """argh's own `DEST_FUNCTION` is `'function'`, so this parameter name kills it.

    An accident, not grammar: there is no observable argh behaviour to preserve, only a
    `KeyError`. cw reserves `'_cw'` instead, so the name is free.
    """

    def fn_param(function="x"):
        return f"function={function!r}"

    with pytest.raises(KeyError):
        run_argh(lambda p: p.set_default_command(fn_param), [])
    assert run_cw(fn_param, ["--function", "z"]) == (0, "function='z'\n", "")
