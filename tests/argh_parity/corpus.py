"""One entry per argh behaviour cw promises to reproduce.

Every function here exists to pin down a specific row of the D2 compatibility contract, and
its docstring says which. Cases are declared once and consumed twice -- by the action-table
diff and by the `--help` diff -- so adding a case costs one function and one `Case(...)`.

Overrides are expressed twice per case, once for each library, and the two spellings are
asserted to be equivalent:

* argh reads `@argh.arg(...)`, which writes `func.argh_args`;
* cw reads `func._cw['params']` (tier 3) or a `config` mapping (tier 4). `_cw` is written
  as a plain attribute on purpose -- that is the documented contract, and it is what lets a
  repo declare CLI details without importing cw at all.
"""

import dataclasses
from typing import Any, Callable, Dict, List, Literal, Optional

import argh
from argh.assembling import NameMappingPolicy

from cw.convention import ARGH, MODERN, Convention

BY_NAME_IF_HAS_DEFAULT = NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT
BY_NAME_IF_KWONLY = NameMappingPolicy.BY_NAME_IF_KWONLY


@dataclasses.dataclass(frozen=True)
class Case:
    """One function, plus everything both libraries need to build its parser."""

    id: str
    func: Callable
    policy: NameMappingPolicy = BY_NAME_IF_HAS_DEFAULT
    convention: Convention = ARGH
    config: Optional[Dict[str, Any]] = None


def declare(*flags: str, **kwargs):
    """Declare one argument for both libraries at once: `@argh.arg` and `func._cw`.

    The two must agree, since the point of the corpus is that they produce identical
    parsers. Writing them from one call is what keeps them agreeing.
    """

    def decorate(func):
        func = argh.arg(*flags, **kwargs)(func)
        param = _param_name_of(flags)
        params = dict(getattr(func, "_cw", {}).get("params", {}))
        # Innermost decorator runs first but reads last, matching argh's insert(0, ...).
        params = {param: dict(kwargs, flags=list(flags)), **params}
        func._cw = {"params": params}
        return func

    return decorate


def _param_name_of(flags):
    """`('-i', '--ignore') -> 'ignore'`, argh's `naive_guess_func_arg_name`."""
    if len(flags) == 1:
        return flags[0].lstrip("-").replace("-", "_")
    for flag in flags:
        if flag.startswith("--"):
            return flag[2:].replace("-", "_")
    raise ValueError(f"cannot guess a parameter name from {flags}")


# ======================================================================================
# The functions. One per behaviour, docstrings naming the contract row.


def two_positionals(alpha, beta):
    """Row 3, negative: no default means a positional, under either policy."""


def defaults_become_options(alpha, beta=1, gamma="x"):
    """Row 3: a defaulted POSITIONAL_OR_KEYWORD becomes an option."""


def keyword_only(alpha, *, beta=1, gamma):
    """Rows 3 + policy: kwonly with and without a default."""


def bool_true_is_store_false(*, verbose: bool = True):
    """Row 6, the footgun: `verbose=True` gives you a flag that turns it OFF."""


def bool_false_is_store_true(*, verbose: bool = False):
    """Row 6: `verbose=False` gives you `--verbose`."""


def bool_untyped(*, verbose=False, quiet=True):
    """Row 6 without annotations: the default value alone decides the action."""


def short_flag_collisions(*, mango=1, node=2, snip=3, semantic=4, hybrid=5):
    """Row 4: `s` collides so neither snip nor semantic gets one; `h` goes to --help."""


def short_flag_h_alone(*, host="localhost"):
    """Row 4: `h` is lost to --help even with nothing to collide with."""


def list_default(*, scorer=()):
    """Row 7: a tuple default implies `nargs='*'`."""


def list_default_list(*, tags=[]):
    """Row 7: so does a list default."""


def typed_defaults(*, count=3, ratio=0.5, name="x", nothing=None):
    """Row 8: a non-None default implies `type=type(default)`; None implies nothing."""


def var_positional(*agents):
    """Row 10: `*args` becomes a trailing positional with `nargs='*'`."""


def var_positional_and_more(alpha, *rest, **configs):
    """Rows 10 + 11 together: `*rest` appears, `**configs` does not."""


def var_keyword_only(alpha, *, beta=1, **configs):
    """Row 11: `**kwargs` contributes no CLI arguments at all."""


def hyphenated_positional(project_dir, *, dry_run=False):
    """Spec 9.3: the one permitted divergence, and it must stay invisible."""


def hint_bare_list(project_dir, *, ignore: list = None):
    """epythet's shape. A bare `list` annotation implies `nargs='*'`, so a flag with
    zero values arrives as `[]` -- which every fleet docs job depends on."""


def hint_list_of_str(project_dir, *, ignore: List[str] = None):
    """`list[str]` implies both `nargs='*'` and `type=str`."""


def hint_non_list_containers(*, a: tuple = None, b: dict = None, c: set = None):
    """The negative of row 7: only `list` is in argh's if-chain. A `tuple` ANNOTATION
    infers nothing, even though a `tuple` DEFAULT infers `nargs='*'`."""


def hint_literal(*, fmt: Literal["json", "yaml"] = "json"):
    """`Literal` implies `choices` and a type taken from the first member."""


def hint_optional_int(*, retries: Optional[int] = None):
    """`Optional[int]` implies `type=int` and `required=False`."""


def hint_optional_positional(retries: Optional[int] = None):
    """`Optional[int]`'s `required=False` is re-read as an optional positional."""


def hint_string_annotation(path: str, *, to_version: "int | None" = None):
    """Row 13: annotations are read raw, so a quoted one infers nothing at all."""


def hint_int(*, n: int = 3):
    """The plain case: an `int` annotation coerces."""


@declare("--ignore", nargs="*")
def declared_disables_hints(project_dir, *, ignore: List[str] = None):
    """Row 12: one override switches hint inference off for the WHOLE function, so
    `ignore` keeps its `nargs` but loses `type=str`, and `project_dir` is untouched."""


@declare("--level", choices=[1, 2, 3])
def declared_choices(*, level=None):
    """Row 9: `type` comes from `choices[0]` when nothing else supplied one."""


@declare("--synth", "-s", nargs="?", const="list")
@declare("--scale", nargs="?", const="list", default=None)
def theremin_shape(synth="sine", scale=None, seconds=3):
    """Rows 4 + 5 together, and issue #16's named acceptance case.

    `synth`, `scale` and `seconds` all start with `s`, so inference gives none of them a
    short flag. `@arg('--synth', '-s')` then APPENDS `-s` after the inferred `--synth`,
    which is why the help column reads `--synth [SYNTH], -s [SYNTH]` -- long first. No
    code anywhere asks for that ordering; it falls out of the collision rule meeting the
    append-merge rule.
    """


@declare("--xs", nargs="+")
def declared_nargs_loses_to_default(*, xs=[]):
    """A quirk, not a feature: argh's default-value guesser runs AFTER the merge and
    overwrites a declared `nargs='+'` with the `'*'` it guessed from the list default.
    """


@declare("agents", nargs=None, help="who to page")
def declared_falsy_nargs(*agents):
    """ADR-0003: `if other.nargs:` -- a falsy override never unsets an inferred `nargs`,
    so `*agents` keeps its `'*'`. A plain `dict.update` merge would silently drop it."""


@declare("project", nargs="?", default=".", help="Project root")
def declared_optional_positional(project: str):
    """coact's shape: a declared positional stays positional and gains `nargs='?'`."""


@declare("--extra-thing", help="goes into **kwargs")
def declared_extra_into_kwargs(alpha, **kwargs):
    """argh's rule: an override naming no parameter is legal iff `**kwargs` exists."""


def hyphenated_positional_with_literal(project_dir: Literal["src", "dist"]):
    """The case a `metavar`-based dest repair renders WRONG, in `usage:` and in `--help`.

    argparse reads a positional's registered name twice -- as the displayed name and as the
    name in `error: argument ...` -- and `metavar` wins only the second. So a hyphenated
    positional carrying `choices` printed `project-dir` where argh printed `{src,dist}`,
    with an identical error message, which is why no error-level test could see it. Both
    corpora had `choices` on OPTIONS only, and every `Literal` positional had a one-word
    name; this case is both at once.
    """


@declare("project_dir", choices=["src", "dist"])
def hyphenated_positional_with_declared_choices(project_dir):
    """The same shape reached through the decorator, with no annotation involved."""


def many_parameters(
    pkg_dir=".",
    project_name="",
    description="",
    author="",
    author_email="",
    url="",
    license_="mit",
    keywords=(),
    root_url="",
    version="0.0.1",
    long_description="",
    display_name="",
    verbose=False,
    dry_run=False,
    overwrite=False,
    include_tests=True,
    include_docs=True,
    include_ci=True,
    python_requires=">=3.8",
    install_requires=(),
    extras_require=(),
    classifiers=(),
    entry_points=(),
    package_data=(),
    exclude=(),
    manifest="",
    readme="",
    changelog="",
    gitignore="",
    workflow="",
    branch="master",
    remote="origin",
    token="",
    quiet=False,
):
    """`wads pack populate_pkg_dir`'s shape: 34 parameters, and collision suppression at
    scale. Only the parameters whose first character is unique keep a short flag, which
    makes the flag set a property of the whole signature rather than of any one
    parameter."""


CASES = [
    Case("two_positionals", two_positionals),
    Case("defaults_become_options", defaults_become_options),
    Case("keyword_only", keyword_only),
    Case("bool_true_is_store_false", bool_true_is_store_false),
    Case("bool_false_is_store_true", bool_false_is_store_true),
    Case("bool_untyped", bool_untyped),
    Case("short_flag_collisions", short_flag_collisions),
    Case("short_flag_h_alone", short_flag_h_alone),
    Case("list_default", list_default),
    Case("list_default_list", list_default_list),
    Case("typed_defaults", typed_defaults),
    Case("var_positional", var_positional),
    Case("var_positional_and_more", var_positional_and_more),
    Case("var_keyword_only", var_keyword_only),
    Case("hyphenated_positional", hyphenated_positional),
    Case("hint_bare_list", hint_bare_list),
    Case("hint_list_of_str", hint_list_of_str),
    Case("hint_non_list_containers", hint_non_list_containers),
    Case("hint_literal", hint_literal),
    Case("hint_optional_int", hint_optional_int),
    Case("hint_optional_positional", hint_optional_positional),
    Case("hint_string_annotation", hint_string_annotation),
    Case("hint_int", hint_int),
    Case("declared_disables_hints", declared_disables_hints),
    Case("declared_choices", declared_choices),
    Case("theremin_shape", theremin_shape),
    Case("declared_nargs_loses_to_default", declared_nargs_loses_to_default),
    Case("declared_falsy_nargs", declared_falsy_nargs),
    Case("declared_optional_positional", declared_optional_positional),
    Case("declared_extra_into_kwargs", declared_extra_into_kwargs),
    Case("hyphenated_positional_with_literal", hyphenated_positional_with_literal),
    Case(
        "hyphenated_positional_with_declared_choices",
        hyphenated_positional_with_declared_choices,
    ),
    Case("many_parameters", many_parameters),
]

#: The same corpus under argh's other name-mapping policy. `cw.BY_NAME_IF_KWONLY` must
#: track it just as exactly, or `convention=cw.MODERN` is not a supported thing to say.
KWONLY_CASES = [
    dataclasses.replace(
        case,
        id=f"{case.id}[kwonly]",
        policy=BY_NAME_IF_KWONLY,
        convention=dataclasses.replace(ARGH, naming=MODERN.naming),
    )
    for case in CASES
]
