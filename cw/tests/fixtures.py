"""The parity corpus: the fleet's hard cases reproduced as *shapes*, not as repos.

:func:`cw.testing.parity` is the definition of v1, and it must run in cw's own CI. As the
canonical spec first wrote it -- "for each of the seven hard-case repos ... rebuilds that
repo's command set through cw" -- it cannot, for reasons that are structural rather than
fixable: three of those repos ``import argh`` at module scope, one of them *depends on cw*,
and cw's whole selling point is that it installs nothing. A gate that needs seven fleet
packages checked out is a gate that is red on somebody else's commit.

So the corpus reproduces the seven repos' **shapes**. Each one is a small, self-contained
module of plain functions that exercises the same grammar the real repo does, recorded once
against real argh 0.31.3 and committed. Parity then needs stdlib plus cw, installs no fleet
package, pulls no argh, and runs on Windows. The seven real repos are gated separately, by
:func:`cw.testing.replay` in each repo's own CI, which is what a migration test is for.

Nothing here imports ``argh``: a shape carries an ``argh_build`` callable that *receives*
the ``argh`` module, so only the dev-only recorder (``misc/record_goldens.py``) ever needs
it installed. Nothing here is imported by ``cw`` either -- :func:`cw.testing.parity` imports
this module lazily, when it runs.

Eight shapes:

===============  ===================  =====================================================
shape            models               what it pins
===============  ===================  =====================================================
``theremin``     ``t/theremin``       ten overrides, ``nargs='?' const='list'``, the ``s``
                                      collision that makes ``--synth`` render long-first and
                                      leaves ``--scale`` with no short at all
``priv``         ``t/priv``           a mapping whose keys name the commands, a
                                      ``functools.partial`` with its bound keyword hidden,
                                      and a group whose name stays verbatim
``epythet``      ``i/epythet``        ``list[str]`` inference, and the CI-critical
                                      ``quickstart . --ignore`` -> ``[]``
``coact``        ``t/coact``          three ``nargs`` shapes and ``*args``
``xa``           ``t/xa``             non-identifier keys, two commands both called ``list``
                                      in different dicts, and a group
``wads_pack``    ``i/wads``           34 parameters, ``**configs``, and ``verbose=True``
                                      becoming ``store_false``
``lacing``       ``t/lacing``         a quoted annotation, PEP 563-blind under ``ARGH``
``contract``     the D2 contract      the egress and error rows, which no repo shape reaches
===============  ===================  =====================================================

The ``rows`` field of each shape names which rows of the argh compatibility contract
(canonical spec section 9) it pins, and ``tests/test_corpus_coverage.py`` fails if a row is
covered by nothing.
"""

import functools

__all__ = [
    "SHAPES",
    "Shape",
    "case_count",
    "cw_outcome",
    "shape_named",
    "use_command_error",
]


# =======================================================================================
# The shape record
# =======================================================================================


class Shape:
    """One hard case: what cw is given, how argh was asked the same question, and the argv.

    ``argh_build`` takes the ``argh`` and ``argparse`` modules and returns the parser argh
    builds. Taking them as arguments rather than importing them is what keeps this module
    argh-free, and therefore shippable inside ``cw``.
    """

    def __init__(
        self,
        name,
        *,
        prog,
        models,
        pins,
        rows,
        cases,
        cw_obj,
        argh_build,
        cw_kwargs=None,
        cw_call=None,
    ):
        self.name = name
        self.prog = prog
        self.models = models
        self.pins = pins
        self.rows = frozenset(rows)
        self.cases = tuple(tuple(case) for case in cases)
        self.cw_obj = cw_obj
        self.cw_kwargs = dict(cw_kwargs or {}, prog=prog)
        self.argh_build = argh_build
        #: ``(cw, argv, **kwargs) -> exit code``. The default is ``cw.dispatch``, the
        #: idiom every migration in the spec uses. A shape overrides it only when it needs
        #: a build-time keyword ``dispatch`` does not carry -- ``xa``'s ``group_kwargs``
        #: being the one case, which is why ``add_commands`` still exists.
        self.cw_call = cw_call or _dispatch_call

    def __repr__(self):
        return f"<Shape {self.name}: {len(self.cases)} cases, rows {sorted(self.rows)}>"


def _dispatch_call(cw, argv, **kwargs):
    """The default cw side of a shape: ``cw.dispatch``, exactly as a migration writes it."""
    obj = kwargs.pop("obj")
    return cw.dispatch(obj, list(argv), **kwargs)


def _xa_call(cw, argv, **kwargs):
    """xa's cw side: ``mk_parser`` + ``add_commands`` + ``run``, for one keyword.

    ``group_kwargs`` is a build-time fact about *one group*, so it has no place in
    ``dispatch``'s flat keyword space -- and ``add_commands`` is where argh put it too.
    This is the one shape that needs it, and having it means the parity gate asserts
    contract row 20 (a group's listing row reads ``title``, never ``help``) rather than
    quietly dropping the only case that exercises it.
    """
    obj = dict(kwargs.pop("obj"))
    group = obj.pop("archive")
    parser = cw.mk_parser(obj, **kwargs)
    cw.add_commands(
        parser, group, group_name="archive", group_kwargs=dict(XA_GROUP_KWARGS)
    )
    return cw.run(parser, list(argv))


def declare(argh, func, decls):
    """Apply ``@argh.arg`` declarations to ``func``, idempotently.

    ``argh.arg`` mutates ``func`` in place -- it ``insert(0, ...)``s into a list it hangs
    off the function -- so building the same parser twice would double every declaration.
    Clearing first makes a rebuild mean what it says. ``reversed`` reproduces stacked
    decorators, where the outermost is applied last and therefore ends up first.

    Only the dev-only recorder calls this; it takes ``argh`` as an argument for the same
    reason the rest of this module does.
    """
    from argh.constants import ATTR_ARGS

    if hasattr(func, ATTR_ARGS):
        delattr(func, ATTR_ARGS)
    for flags, kwargs in reversed(decls):
        func = argh.arg(*flags, **kwargs)(func)
    return func


def config_from(decls):
    """The cw ``config`` leaf equivalent of a list of ``@argh.arg`` declarations.

    Written once, from one source, so the two spellings cannot drift. The difference
    between them is exactly one rule: ``@argh.arg`` must be given the long flag, because
    that is how argh guesses which parameter is meant; cw already knows the parameter, so
    its ``flags`` key carries only what the inference did *not* produce, and the
    append-merge does the rest.

    >>> config_from([(('-p', '--pipeline'), {'nargs': '?'}), (('--scale',), {})])
    {'pipeline': {'nargs': '?', 'flags': ['-p']}, 'scale': {}}
    """
    config = {}
    for flags, kwargs in decls:
        param = _param_name_of(flags)
        extra = [flag for flag in flags if flag != f"--{param.replace('_', '-')}"]
        config[param] = dict(kwargs, flags=extra) if extra else dict(kwargs)
    return config


def _param_name_of(flags):
    """``('-i', '--ignore') -> 'ignore'`` -- argh's ``naive_guess_func_arg_name``.

    >>> _param_name_of(('-i', '--ignore')), _param_name_of(('project',))
    ('ignore', 'project')
    """
    if len(flags) == 1:
        return flags[0].lstrip("-").replace("-", "_")
    for flag in flags:
        if flag.startswith("--"):
            return flag[2:].replace("-", "_")
    raise ValueError(f"cannot guess a parameter name from {flags}")


def _single_command(argh, argparse, func, *, prog, decls=()):
    """The parser argh builds for one command -- the ``set_default_command`` shape."""
    func = declare(argh, func, decls) if decls else func
    parser = argparse.ArgumentParser(
        prog=prog, formatter_class=argh.PARSER_FORMATTER, description=func.__doc__
    )
    argh.set_default_command(parser, func)
    return parser


def _subcommands(argh, argparse, funcs, *, prog, description=None, groups=(), decls=()):
    """The parser argh builds for a command set -- the ``add_commands`` shape."""
    for func, func_decls in decls:
        declare(argh, func, func_decls)
    parser = argparse.ArgumentParser(
        prog=prog, formatter_class=argh.PARSER_FORMATTER, description=description
    )
    argh.add_commands(parser, list(funcs))
    for group_name, group_funcs, group_kwargs in groups:
        argh.add_commands(
            parser, list(group_funcs), group_name=group_name, group_kwargs=group_kwargs
        )
    return parser


# =======================================================================================
# Shape 1 -- t/theremin. Ten overrides, five `nargs='?' const='list'`, the `s` collision.
# =======================================================================================

#: A bare flag means "list the options" -- theremin's real UX, and the reason five of its
#: ten declarations carry a `const`.
_LIST = dict(nargs="?", const="list")

#: The ten declarations, in theremin's own order. `flags` is the *declared* flag list argh
#: needs; `config_from` derives what cw's config says from the same data.
THEREMIN_DECLS = [
    (("-p", "--pipeline"), dict(_LIST, help="Audio pipeline name")),
    (("-v", "--video-features"), dict(_LIST, help="Video features function name")),
    (("-k", "--knobs"), dict(_LIST, help="Audio knobs function name")),
    # Declared long-first, which is what makes `--synth [SYNTH], -s [SYNTH]` render in that
    # order: the inferred `-s` was suppressed by the collision with `scale`, so the
    # declared `-s` is *appended* to the inferred `['--synth']` rather than leading it.
    (("--synth", "-s"), dict(_LIST, help="Synthesizer function name")),
    (("--log-video-features",), dict(help="Log hand features")),
    (("--log-knobs",), dict(help="Log audio features")),
    (("-r", "--record-to-file"), dict(help="Filename to save recording")),
    (("-n", "--no-recording"), dict(help="Disable recording")),
    (("-w", "--window-name"), dict(help="Window title")),
    # No short flag is declared and none is inferred: `scale` collides with `synth` on `s`,
    # and argh's collision pass suppresses the short for BOTH parameters.
    (("--scale",), dict(_LIST, help="Scale for snapping; 'none' disables")),
]


def theremin_cli(
    pipeline="theremin",
    video_features="many_video_features",
    knobs="theremin_knobs",
    synth="theremin_synth",
    log_video_features=False,
    log_knobs=False,
    record_to_file=None,
    no_recording=False,
    window_name="theremin",
    scale=None,
):
    """Run the theremin.

    Every parameter has a default, so every one becomes an option under
    BY_NAME_IF_HAS_DEFAULT -- which is the policy argh's dispatch entry points default to
    and the only one cw offers as ARGH.
    """
    return (
        f"pipeline={pipeline!r} video_features={video_features!r} knobs={knobs!r} "
        f"synth={synth!r} scale={scale!r} record_to_file={record_to_file!r} "
        f"window_name={window_name!r} "
        f"flags={log_video_features!r},{log_knobs!r},{no_recording!r}"
    )


THEREMIN = Shape(
    "theremin",
    prog="theremin",
    models="t/theremin",
    pins=(
        "Ten @argh.arg overrides on a single command. The parameters `synth` and `scale` "
        "both start with `s`, so NEITHER gets an inferred short flag; the declared "
        "['--synth', '-s'] then appends `-s` for synth only. `--scale` ends with no short "
        "at all. That falls out of the append-merge rule and is not special-cased."
    ),
    rows=(3, 4, 5, 8),
    cw_obj=theremin_cli,
    cw_kwargs={"config": config_from(THEREMIN_DECLS)},
    argh_build=lambda argh, argparse: _single_command(
        argh, argparse, theremin_cli, prog="theremin", decls=THEREMIN_DECLS
    ),
    cases=[
        [],
        ["--help"],
        # `-p` with a value, and `-p` bare -- the const='list' sentinel.
        ["-p", "flute"],
        ["-p"],
        ["--pipeline"],
        ["--pipeline", "flute"],
        # The whole point of the shape: `-s` reaches synth, long-first rendering and all.
        ["-s", "saw"],
        ["-s"],
        ["--synth", "saw"],
        # ... and `scale` has no short, so `-c`/`-a` are usage errors, not scale.
        ["--scale"],
        ["--scale", "minor"],
        ["-a", "minor"],
        # `-l` would be log_video_features' or log_knobs' short if the collision pass did
        # not suppress both. It is a usage error, and that is the assertion.
        ["-l"],
        ["--log-knobs", "--log-video-features"],
        ["-v", "hands"],
        ["-k", "smooth"],
        ["-r", "out.wav", "-n"],
        ["-w", "Theremin"],
        ["--nope"],
    ],
)


# =======================================================================================
# Shape 2 -- t/priv. A mapping of keys to callables, a partial, and a verbatim group.
# =======================================================================================


def parse_pth_paths(path="."):
    """Parse a .pth file into the package paths it names."""
    return f"parse_pth_paths({path!r})"


def align(*, repair=False):
    """Report ecosystem drift, and optionally act on it."""
    return f"align(repair={repair!r})"


def render_pth(out="my_packages.pth"):
    """Render the manifest from its committed source of truth."""
    return f"render_pth({out!r})"


def packages_from_config(pkg_dir=".", config_type="pyproject.toml"):
    """List the packages a directory of projects declares."""
    return f"packages_from_config({pkg_dir!r}, {config_type!r})"


#: priv's real shape: a `functools.partial` in `__all__` that pre-binds `config_type`. argh
#: crashes on a partial outright, and priv's live workaround copies `__name__` off the base
#: function -- which is why `priv packages-from-all-setup-cfgs` does not exist today and
#: `-c/--config-type` is still exposed. cw takes the partial and the mapping key names it.
packages_from_all_setup_cfgs = functools.partial(
    packages_from_config, config_type="setup.cfg"
)


def packages_from_all_setup_cfgs_for_argh(pkg_dir="."):
    """List the packages a directory of projects declares."""
    return packages_from_all_setup_cfgs(pkg_dir)


# argh cannot be handed a partial, so the golden is recorded against the wrapper a repo has
# to hand-write today. The parity claim is that cw's partial + cw.HIDE produces the same
# command line as argh's hand-written wrapper -- which is the whole reason HIDE exists.
packages_from_all_setup_cfgs_for_argh.__name__ = "packages_from_all_setup_cfgs"


def git_branch_report(*, stale_days=30):
    """Report branch drift across the fleet."""
    return f"git_branch_report(stale_days={stale_days!r})"


def git_land(branch, *, squash=True):
    """Land a branch: review, PR, CI gate, squash-merge."""
    return f"git_land({branch!r}, squash={squash!r})"


PRIV_TOP = [parse_pth_paths, align, render_pth, packages_from_all_setup_cfgs_for_argh]
PRIV_GIT_OPS = [git_branch_report, git_land]

PRIV = Shape(
    "priv",
    prog="priv",
    models="t/priv",
    pins=(
        "A mapping whose keys name the commands, hyphenated ("
        "`parse_pth_paths` -> `parse-pth-paths`); a group whose name stays VERBATIM "
        "(`git_ops`, which is in priv's own README and is emitted as a user-facing "
        "suggestion); and a functools.partial whose bound keyword is hidden with cw.HIDE "
        "rather than re-exposed as a flag."
    ),
    rows=(1, 2, 11),
    cw_obj={
        "parse_pth_paths": parse_pth_paths,
        "align": align,
        "render_pth": render_pth,
        # The mapping KEY is the command name, which is what finally gives the partial the
        # right one. Hyphenation still applies to the key, so this is `packages-from-...`.
        "packages_from_all_setup_cfgs": packages_from_all_setup_cfgs,
        "git_ops": {"git_branch_report": git_branch_report, "git_land": git_land},
    },
    cw_kwargs={
        # Don't re-expose the keyword the partial already bound.
        "config": {"packages-from-all-setup-cfgs": {"config_type": "HIDE"}},
        "description": "Private fleet tooling.",
    },
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        PRIV_TOP,
        prog="priv",
        description="Private fleet tooling.",
        groups=[("git_ops", PRIV_GIT_OPS, None)],
    ),
    cases=[
        [],
        ["--help"],
        ["parse-pth-paths"],
        # A defaulted POSITIONAL_OR_KEYWORD is an OPTION, so the bare word is rejected...
        ["parse-pth-paths", "/somewhere"],
        # ... and this is how you actually pass it.
        ["parse-pth-paths", "--path", "/somewhere"],
        # Hyphenation is not optional: the underscore spelling must NOT be a command.
        ["parse_pth_paths"],
        ["align"],
        ["align", "--repair"],
        ["render-pth"],
        ["render-pth", "--out", "x.pth"],
        ["packages-from-all-setup-cfgs"],
        ["packages-from-all-setup-cfgs", "--pkg-dir", "/p"],
        # The bound keyword is gone from the command line, in both spellings.
        ["packages-from-all-setup-cfgs", "--config-type", "setup.cfg"],
        # Group names stay verbatim -- `git_ops`, not `git-ops`.
        ["git_ops"],
        ["git-ops"],
        ["git_ops", "--help"],
        ["git_ops", "git-branch-report"],
        ["git_ops", "git-branch-report", "--stale-days", "7"],
        ["git_ops", "git-land", "build-v1"],
        ["git_ops", "git-land", "build-v1", "--squash"],
        ["nope"],
    ],
)


# =======================================================================================
# Shape 3 -- i/epythet. `list[str]` inference, and the case every fleet docs job runs.
# =======================================================================================


def quickstart(project_dir, *, ignore: list = None, depth: int = None):
    """Create a docsrc directory for a project.

    The annotation is a real `list` object, not a string, because this module has no
    `from __future__ import annotations` -- which is exactly the condition under which
    argh's hint guesser fires and the `@argh.arg('--ignore', nargs='*')` decorator can be
    deleted outright.
    """
    return f"quickstart({project_dir!r}, ignore={ignore!r}, depth={depth!r})"


def make_docsrc(project_dir, *, verbose=False):
    """Generate the docsrc for a project."""
    return f"make_docsrc({project_dir!r}, verbose={verbose!r})"


def check_pages(
    project_dir, *, ignore: list = None, depth: int = None, timeout: int = 30
):
    """Check that a project's GitHub Pages site is live.

    Row 12, and the pair that makes it observable: this function is identical to
    `quickstart` in the two ways that matter, except that it carries one `@argh.arg`. That
    one declaration turns hint inference OFF for the WHOLE function, so:

    * `--depth 2` arrives here as the STRING `'2'`, where `quickstart` gets the int `2`
      (`depth`'s type comes only from its annotation -- its default is None, so the
      default-value guesser has nothing to say about it); and
    * `ignore` would lose its `nargs='*'` too, which is why the declaration has to put it
      back explicitly.

    `timeout` is coerced either way: its default is `30`, and the default-value guesser
    runs regardless of whether hints do.
    """
    return (
        f"check_pages({project_dir!r}, ignore={ignore!r}, depth={depth!r}, "
        f"timeout={timeout!r})"
    )


EPYTHET_DECLS = [(("--ignore",), dict(nargs="*"))]

EPYTHET = Shape(
    "epythet",
    prog="epythet",
    models="i/epythet",
    pins=(
        "A `list` annotation infers nargs='*', so epythet's decorator can be deleted. The "
        "CI-critical case is `quickstart . --ignore` with ZERO values -- the literal line "
        "in publish-github-pages/action.yml, running in every fleet repo's docs job -- "
        "which must still parse to `ignore=[]`. Also row 12: the @argh.arg on "
        "`check_pages` turns hint inference off for that whole function, so `timeout` "
        "arrives as a string."
    ),
    rows=(1, 12, 13),
    cw_obj=[quickstart, make_docsrc, check_pages],
    cw_kwargs={
        "config": {"check-pages": config_from(EPYTHET_DECLS)},
        "description": "Setup and generate Sphinx docs effortlessly",
    },
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        [quickstart, make_docsrc, check_pages],
        prog="epythet",
        description="Setup and generate Sphinx docs effortlessly",
        decls=[(check_pages, EPYTHET_DECLS)],
    ),
    cases=[
        [],
        ["--help"],
        ["quickstart", "--help"],
        ["quickstart", "."],
        # The three lines the whole shape exists for.
        ["quickstart", ".", "--ignore"],
        ["quickstart", ".", "--ignore", "a", "b"],
        ["quickstart", ".", "-i", "a"],
        # No @argh.arg on quickstart, so hints fire: `depth` arrives as the int 2.
        ["quickstart", ".", "--depth", "2"],
        ["make-docsrc", ".", "--verbose"],
        # One @argh.arg on check_pages, so hints do NOT fire: `depth` arrives as '2'.
        ["check-pages", ".", "--depth", "2"],
        # ... but `timeout` is coerced anyway, from its default, not its annotation.
        ["check-pages", ".", "--timeout", "5"],
        ["check-pages", ".", "--ignore"],
        ["check-pages", ".", "--ignore", "x"],
        ["quickstart"],
    ],
)


# =======================================================================================
# Shape 4 -- t/coact. Three nargs shapes and *args.
# =======================================================================================


def inventory(project):
    """List what a project already has."""
    return f"inventory({project!r})"


def scaffold(agents):
    """Wire agent files into a project."""
    return f"scaffold({agents!r})"


def publish(source):
    """Publish tool refs, a skill directory, or both."""
    return f"publish({source!r})"


def estimate(*agents: str):
    """Estimate the cost of running some agents.

    Row 10: VAR_POSITIONAL becomes a positional with nargs='*' and needs no declaration at
    all. The ingress re-expands it, so the function really does receive three arguments.
    """
    return f"estimate{agents!r}"


def emit(*, tags=[]):
    """Emit a report.

    Row 7: a `list` DEFAULT infers nargs='*' with no annotation involved. (A `tuple`
    default does too; a `tuple` ANNOTATION infers nothing, which is why row 7 says
    "default".)
    """
    return f"emit(tags={tags!r})"


def back(step, *, mode="undo"):
    """Step a project back.

    Row 9: `choices` makes argh take `type` from `choices[0]`, so `--depth 2` arrives as an
    int here and the choices are checked against the coerced value.
    """
    return f"back({step!r}, mode={mode!r})"


COACT_DECLS = {
    "inventory": [(("project",), dict(nargs="?", default="."))],
    "scaffold": [(("agents",), dict(nargs="+"))],
    "publish": [(("source",), dict(nargs="+"))],
    "back": [(("--mode",), dict(choices=["undo", "redo"]))],
    # A DECLARED nargs of None is falsy, and argh's merge takes `nargs` only when it is
    # truthy -- so this declaration does NOT unset the inferred `nargs='*'`. There is no
    # spelling that does (ADR-0003's third open question is answered "there isn't one"),
    # and an implementation that merged with plain assignment would break `estimate a b c`.
    "estimate": [(("agents",), dict(nargs=None, help="Agent names"))],
}

COACT = Shape(
    "coact",
    prog="coact",
    models="t/coact",
    pins=(
        "The three nargs shapes coact declares -- nargs='?' with a default, and two "
        "nargs='+' -- plus a VAR_POSITIONAL that needs no declaration, a list DEFAULT that "
        "infers nargs='*' with no annotation, and a `choices` that supplies `type`."
    ),
    rows=(1, 7, 9, 10),
    cw_obj=[inventory, scaffold, publish, estimate, emit, back],
    cw_kwargs={
        "config": {name: config_from(d) for name, d in COACT_DECLS.items()},
        "description": "Agent project scaffolding.",
    },
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        [inventory, scaffold, publish, estimate, emit, back],
        prog="coact",
        description="Agent project scaffolding.",
        decls=[
            (inventory, COACT_DECLS["inventory"]),
            (scaffold, COACT_DECLS["scaffold"]),
            (publish, COACT_DECLS["publish"]),
            (back, COACT_DECLS["back"]),
            (estimate, COACT_DECLS["estimate"]),
        ],
    ),
    cases=[
        [],
        ["--help"],
        ["inventory"],
        ["inventory", "."],
        ["inventory", "/elsewhere"],
        ["inventory", "a", "b"],
        ["scaffold"],
        ["scaffold", "one.md"],
        ["scaffold", "one.md", "two.md"],
        ["publish", "mod:func", "skills/"],
        ["estimate"],
        ["estimate", "a"],
        ["estimate", "a", "b", "c"],
        ["emit"],
        ["emit", "--tags"],
        ["emit", "--tags", "x", "y"],
        ["back", "1"],
        ["back", "1", "--mode", "redo"],
        ["back", "1", "--mode", "sideways"],
    ],
)


# =======================================================================================
# Shape 5 -- t/xa. Keys name the commands; two of them are called `list`.
# =======================================================================================


def list_cmd(*, running=False):
    """List sessions."""
    return f"list_cmd(running={running!r})"


def spawn_cmd(name, *, detach=False, host="local"):
    """Spawn a session.

    Row 4's other half: `host` starts with `h`, and `-h` already belongs to `--help`. argh
    strips it, so `host` gets no short flag even though no other parameter collides with it.
    An implementation that forgot would not merely add a flag -- argparse would refuse to
    build the parser at all ("conflicting option string: -h"), so this is asserted by every
    case in the shape at once.
    """
    return f"spawn_cmd({name!r}, detach={detach!r}, host={host!r})"


def gen_secret_cmd(*, length=32):
    """Generate a shared secret."""
    return f"gen_secret_cmd(length={length!r})"


def archive_list_cmd(*, pattern="*"):
    """List archived sessions."""
    return f"archive_list_cmd(pattern={pattern!r})"


def archive_log_cmd(session):
    """Show an archived session's log."""
    return f"archive_log_cmd({session!r})"


#: xa's live workaround: thirteen `__name__` mutations, because argh reads `__name__` and
#: has no way to be told a command's name. Two of them assign the SAME string (`list`) to
#: different functions, which is exactly why a mapping is the right shape.
def _mutated(func, name):
    """Give ``func`` the name xa assigns it today. Recorded so cw's keys can be diffed."""
    func.__name__ = name
    return func


#: `group_kwargs={'help': ...}` -- what xa passes today. Per spec section 9.1 argh reads
#: `title` for the listing row, so this string displays NOTHING. cw reproduces that: it
#: passes group_kwargs whole to add_subparsers and `help=group_kwargs.get('title')` to
#: add_parser, even when that is None (omitting it makes the group row vanish entirely).
XA_GROUP_KWARGS = {"help": "Postmortem archive (list, log, forensics)."}

XA = Shape(
    "xa",
    prog="xa",
    models="t/xa",
    pins=(
        "A mapping key names the command verbatim-then-hyphenated, so the non-identifier "
        "key 'gen-secret' works and needs no __name__ mutation. Two commands are both "
        "called `list` in different dicts, which a list of functions cannot express. And "
        "the group's `group_kwargs={'help': ...}` displays nothing -- argh reads `title` "
        "for that row -- so translating it would be an improvement, and therefore a break."
    ),
    # Row 20 is exercised here but NOT claimed: whether the listing row reads `title` or
    # `help` shows only in a --help body, which the golden format keeps at tier 3. It is
    # asserted by tests/argh_parity/test_cli_parity.py instead. Row 4 is claimed because
    # `host` proves `-h` is stripped, and that IS observable at tier 1.
    rows=(1, 4),
    cw_obj={
        "list": list_cmd,
        "spawn": spawn_cmd,
        "gen-secret": gen_secret_cmd,
        "archive": {"list": archive_list_cmd, "log": archive_log_cmd},
    },
    cw_kwargs={"description": "Session multiplexer."},
    cw_call=lambda cw, argv, **kwargs: _xa_call(cw, argv, **kwargs),
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        [
            _mutated(list_cmd, "list"),
            _mutated(spawn_cmd, "spawn"),
            _mutated(gen_secret_cmd, "gen-secret"),
        ],
        prog="xa",
        description="Session multiplexer.",
        groups=[
            (
                "archive",
                [_mutated(archive_list_cmd, "list"), _mutated(archive_log_cmd, "log")],
                XA_GROUP_KWARGS,
            )
        ],
    ),
    cases=[
        [],
        ["--help"],
        ["list"],
        ["list", "--running"],
        ["spawn", "s1"],
        ["spawn", "s1", "--detach"],
        # `-h` is --help's, not host's, even though nothing else starts with `h`.
        ["spawn", "s1", "-h"],
        ["spawn", "s1", "--host", "remote"],
        # A non-identifier key is a fine command name and needs no __name__ mutation.
        ["gen-secret"],
        ["gen-secret", "--length", "8"],
        ["gen_secret"],
        ["archive"],
        ["archive", "--help"],
        # The second `list` -- a different function, same word, different dict.
        ["archive", "list"],
        ["archive", "list", "--pattern", "x*"],
        ["archive", "log", "s1"],
        ["archive", "nope"],
    ],
)


# =======================================================================================
# Shape 6 -- i/wads pack. 34 parameters, `**configs`, and the store_false footgun.
# =======================================================================================


def populate_pkg_dir(
    pkg_dir,
    *,
    version=None,
    description=None,
    root_url=None,
    author=None,
    author_email=None,
    license="mit",
    keywords=None,
    url=None,
    project_urls=None,
    classifiers=None,
    python_requires=None,
    install_requires=None,
    extras_require=None,
    entry_points=None,
    package_data=None,
    include_package_data=False,
    zip_safe=False,
    long_description=None,
    long_description_content_type=None,
    platforms=None,
    provides=None,
    obsoletes=None,
    download_url=None,
    maintainer=None,
    maintainer_email=None,
    docsrc=None,
    display_name=None,
    dry_run=False,
    overwrite=False,
    verbose=True,
    **configs,
):
    """Populate a package directory from a template.

    Thirty-four parameters, which is what makes the short-flag collision pass observable as
    data rather than as a heuristic: with this many first characters almost everything
    collides and almost nothing gets a short flag. `verbose: bool = True` becomes
    `store_false`, so `--verbose` turns verbosity OFF -- the footgun D2 preserves on
    purpose. And `**configs` contributes no command-line arguments at all.
    """
    return (
        f"populate_pkg_dir({pkg_dir!r}) verbose={verbose!r} license={license!r} "
        f"version={version!r} dry_run={dry_run!r} configs={configs!r}"
    )


def go(pkg_dir, *, version=None, verbose=True):
    """Package and publish, in one step."""
    return f"go({pkg_dir!r}, version={version!r}, verbose={verbose!r})"


WADS_PACK = Shape(
    "wads_pack",
    prog="pack",
    models="i/wads",
    pins=(
        "Collision suppression at scale: 34 parameters, so almost no short flag survives. "
        "`verbose: bool = True` -> store_false, so `--verbose` turns verbosity OFF. "
        "`**configs` contributes no CLI arguments, and the leftovers argparse never "
        "produced are collected on ingress anyway."
    ),
    rows=(1, 3, 4, 6, 8, 11),
    cw_obj=[populate_pkg_dir, go],
    cw_kwargs={"description": "Utils to package and publish."},
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        [populate_pkg_dir, go],
        prog="pack",
        description="Utils to package and publish.",
    ),
    cases=[
        [],
        ["--help"],
        ["populate-pkg-dir", "--help"],
        ["populate-pkg-dir", "/p"],
        # The footgun, asserted rather than fixed: this turns verbosity OFF.
        ["populate-pkg-dir", "/p", "--verbose"],
        ["go", "/p", "--verbose"],
        ["go", "/p"],
        ["go", "/p", "--version", "0.0.1"],
        # `d` is shared by description/docsrc/display_name/download_url/dry_run, `v` by
        # version/verbose. Almost nothing keeps a short flag, and `-d`/`-v` are errors.
        ["populate-pkg-dir", "/p", "-d", "x"],
        ["populate-pkg-dir", "/p", "-v"],
        # `l` is shared by license/long_description/long_description_content_type, so even
        # `--license` -- which looks like it should own `-l` -- has no short flag.
        ["populate-pkg-dir", "/p", "-l", "apache"],
        ["populate-pkg-dir", "/p", "--license", "apache"],
        # Exactly five first characters are unique across the 33 options, so exactly five
        # short flags survive: -r -k -u -c -z. The collision pass is data, not a heuristic.
        ["populate-pkg-dir", "/p", "-k", "cli"],
        ["populate-pkg-dir", "/p", "-z"],
        ["populate-pkg-dir", "/p", "-c", "Topic"],
        # `**configs` produces no flags, so this is a usage error, not a config key.
        ["populate-pkg-dir", "/p", "--anything-at-all", "1"],
        ["populate-pkg-dir", "/p", "--dry-run", "--overwrite"],
    ],
)


# =======================================================================================
# Shape 7 -- t/lacing. A quoted annotation, invisible to argh.
# =======================================================================================


def migrate(path: str, *, to_version: "int | None" = None):
    """Upgrade PATH to the current store schema, in place.

    Row 13: argh reads `__annotations__` raw, so this annotation is the STRING
    `'int | None'`, which is not in its if-chain. The guesser returns nothing, the default
    is None so the default-value path yields nothing either, and `to_version` arrives as a
    `str`. That is why lacing's own body says "argh delivers option values as strings;
    coerce here" -- and why the coercion may not be deleted until MODERN is opted into.
    """
    return f"migrate({path!r}, to_version={to_version!r})"


def convert(source, target, *, fmt: str = "annot"):
    """Convert an annotation file between formats."""
    return f"convert({source!r}, {target!r}, fmt={fmt!r})"


def list_formats():
    """List the annotation formats lacing understands."""
    return ["annot", "csv", "json"]


LACING = Shape(
    "lacing",
    prog="lacing",
    models="t/lacing",
    pins=(
        "A quoted annotation -- `to_version: 'int | None'` -- is read raw and matches "
        "nothing, so the value arrives as a str and `repr` shows the quotes. This is live "
        "in ~32 fleet files. Under cw.MODERN it would resolve to int; under cw.ARGH, which "
        "is the default and what parity asserts, it must NOT."
    ),
    rows=(1, 13, 16),
    cw_obj=[migrate, convert, list_formats],
    cw_kwargs={"description": "Annotation store tooling."},
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        [migrate, convert, list_formats],
        prog="lacing",
        description="Annotation store tooling.",
    ),
    cases=[
        [],
        ["--help"],
        ["migrate", "a.annot"],
        # The assertion: `'3'`, with quotes. An int would mean cw resolved the hint.
        ["migrate", "a.annot", "--to-version", "3"],
        ["migrate", "a.annot", "-t", "3"],
        ["convert", "a.annot", "b.csv"],
        ["convert", "a.annot", "b.csv", "--fmt", "csv"],
        # A list return iterates, one line each -- row 16, the egress whitelist.
        ["list-formats"],
        ["migrate"],
    ],
)


# =======================================================================================
# Shape 8 -- the contract rows no repo shape reaches: egress and errors.
# =======================================================================================


def returns_none():
    """Row 17: None prints NOTHING -- not 'None', not a blank line."""
    return None


def returns_zero():
    """Row 17: 0 DOES print, which is why the check cannot be `if result:`."""
    return 0


def returns_false():
    """Row 17: False DOES print."""
    return False


def returns_empty_string():
    """Row 17: '' DOES print -- as a blank line."""
    return ""


def returns_list():
    """Row 16: a list iterates, one line per item."""
    return ["alpha", "beta"]


def returns_tuple():
    """Row 16: a tuple iterates too."""
    return ("alpha", "beta")


def returns_dict():
    """Row 16: a dict is NOT iterated. It prints its repr, on one line."""
    return {"a": 1, "b": 2}


def returns_set():
    """Row 16: a set is not in the whitelist either, so it prints its repr.

    Set repr ordering is stable here only because the set has one element -- which is the
    point: the corpus may not depend on hash ordering.
    """
    return {"only"}


def returns_generator():
    """Row 16: a generator IS in the whitelist, and iterates."""
    return (str(n) for n in range(3))


def returns_iterator():
    """Row 16, the trap: `iter([...])` is a `list_iterator`, NOT a GeneratorType.

    The whitelist is three concrete types, so this prints a repr, not two lines. Any fleet
    command returning `map(...)`, `filter(...)` or a comprehension-fed iterator is printing
    a repr today.
    """
    return iter(["alpha", "beta"])


def streams_then_fails():
    """Row 18: a generator streams LAZILY, so what it yielded lands before the error."""

    def gen():
        yield "first"
        yield "second"
        raise RuntimeError("halfway")

    return gen()


#: Which library's ``CommandError`` the contract shape raises. Row 19 is about what a
#: framework does with *its own* expected-failure exception, so comparing cw's handling of
#: ``cw.CommandError`` against argh's handling of ``cw.CommandError`` would compare nothing:
#: argh does not recognise it and reports it as a crash. Both sides install their own.
_COMMAND_ERROR = []


def use_command_error(cls) -> None:
    """Install the ``CommandError`` class the contract shape raises.

    :func:`cw_outcome` installs :class:`cw.CommandError`; the dev-only recorder installs
    ``argh.CommandError``. Neither side gets a default, because a default here would be a
    silent way to record the wrong thing.
    """
    _COMMAND_ERROR[:] = [cls]


def _command_error(message, code=None):
    """Raise the installed ``CommandError``, with a code when one is asked for."""
    if not _COMMAND_ERROR:
        raise RuntimeError(
            "no CommandError class installed: call fixtures.use_command_error(cls) first. "
            "cw.tests.fixtures.cw_outcome does this for you."
        )
    cls = _COMMAND_ERROR[0]
    raise cls(message) if code is None else cls(message, code=code)


def raises_command_error():
    """Row 19: `CommandError` is one line on stderr and a non-zero exit, no traceback."""
    _command_error("no such pipeline")


def raises_command_error_coded():
    """Row 19: and it carries its own exit code, which is NOT 1."""
    _command_error("gone", code=7)


def raises_system_exit_code():
    """Row 19: a SystemExit keeps its exit code."""
    raise SystemExit(3)


def raises_system_exit_message():
    """Row 19: a SystemExit with a string prints it and exits 1."""
    raise SystemExit("bye")


CONTRACT_COMMANDS = [
    returns_none,
    returns_zero,
    returns_false,
    returns_empty_string,
    returns_list,
    returns_tuple,
    returns_dict,
    returns_set,
    returns_generator,
    returns_iterator,
    streams_then_fails,
    raises_command_error,
    raises_command_error_coded,
    raises_system_exit_code,
    raises_system_exit_message,
]

CONTRACT = Shape(
    "contract",
    prog="contract",
    models="the D2 contract itself",
    pins=(
        "The egress and error rows, which every repo shape has in it but none exercises "
        "on purpose: the three-concrete-type whitelist (a dict prints on ONE line and a "
        "plain iterator prints a repr), None printing nothing while 0/False/'' print, "
        "lazy generator streaming, and CommandError's one-line stderr and exit code."
    ),
    rows=(16, 17, 18, 19),
    cw_obj=CONTRACT_COMMANDS,
    cw_kwargs={"description": "The D2 contract rows, one command each."},
    argh_build=lambda argh, argparse: _subcommands(
        argh,
        argparse,
        CONTRACT_COMMANDS,
        prog="contract",
        description="The D2 contract rows, one command each.",
    ),
    cases=[
        [],
        ["--help"],
        ["returns-none"],
        ["returns-zero"],
        ["returns-false"],
        ["returns-empty-string"],
        ["returns-list"],
        ["returns-tuple"],
        ["returns-dict"],
        ["returns-set"],
        ["returns-generator"],
        ["returns-iterator"],
        ["streams-then-fails"],
        ["raises-command-error"],
        ["raises-command-error-coded"],
        ["raises-system-exit-code"],
        ["raises-system-exit-message"],
    ],
)


# =======================================================================================
# The registry, and the one function parity calls
# =======================================================================================

#: Every shape, by name. :func:`cw.testing.parity` looks a golden's ``shape`` up here.
SHAPES = {
    shape.name: shape
    for shape in (
        CONTRACT,
        COACT,
        EPYTHET,
        LACING,
        PRIV,
        THEREMIN,
        WADS_PACK,
        XA,
    )
}


def shape_named(name) -> Shape:
    """The shape called ``name``, or an error that names the real ones.

    >>> shape_named('theremin').models
    't/theremin'
    >>> shape_named('nope')
    Traceback (most recent call last):
      ...
    KeyError: "no fixture shape named 'nope'. There are: contract, coact, epythet, lacing, priv, theremin, wads_pack, xa"
    """
    try:
        return SHAPES[name]
    except KeyError:
        raise KeyError(
            f"no fixture shape named {name!r}. There are: {', '.join(SHAPES)}"
        ) from None


def case_count() -> int:
    """How many argv vectors the corpus holds, counted rather than asserted.

    >>> case_count() > 100
    True
    """
    return sum(len(shape.cases) for shape in SHAPES.values())


def _resolved_config(shape):
    """``shape.cw_kwargs['config']`` with the ``'HIDE'`` placeholder made real.

    The shapes are plain data and must not import ``cw`` at module scope -- that is what
    lets this file ship inside the package without making ``import cw`` circular. So a
    config leaf that means :data:`cw.HIDE` is written as the string ``'HIDE'`` and resolved
    here, where ``cw`` is already imported.
    """
    from cw.base import HIDE

    config = shape.cw_kwargs.get("config")
    if not config:
        return config
    return {
        key: {
            param: (HIDE if value == "HIDE" else value) for param, value in leaf.items()
        }
        for key, leaf in config.items()
    }


def cw_outcome(shape, argv) -> dict:
    """Run one case through cw, with every seam on its default, and report the outcome.

    This is the cw half of the parity gate. The argh half lives in the dev-only recorder,
    and the two share :func:`cw.testing.capture` so the comparison is between two runs of
    the same measuring instrument.
    """
    import cw
    from cw.testing import capture

    use_command_error(cw.CommandError)
    kwargs = dict(shape.cw_kwargs, obj=shape.cw_obj)
    if "config" in kwargs:
        kwargs["config"] = _resolved_config(shape)
    return capture(lambda: shape.cw_call(cw, list(argv), **kwargs))
