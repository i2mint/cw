"""Build the same function's parser twice -- once with argh, once with cw -- and diff.

This is the falsifiable half of D2. `cw.grammar` claims to reproduce argh 0.31.3's
signature inference; the only way to know is to ask argh, so `argh` is a **test-only**
dependency (the `dev` extra) and nothing under `cw/` imports it.

Two comparisons run on every corpus case:

* the **action table** -- every field of every `argparse.Action` the two parsers built,
  in order;
* the rendered **`--help`** text, byte for byte, at a pinned terminal width.

**Nothing is forgiven.** Every field is compared as it is -- `dest`, `metavar`, `type`,
`nargs`, `const`, `choices`, `default`, `required`, `help` and the action class.

This file used to forgive one divergence, the one spec section 9.3 permitted and asserted
was invisible: argh registers a hyphenated positional as `add_argument('project-dir')`,
giving a `dest` no Python call can use, and cw registered
`add_argument('project_dir', metavar='project-dir')` instead. It was not invisible. argparse
reads that one string twice -- as the displayed name AND as the name in `error: argument
...` -- and a `metavar` wins only the second, so a hyphenated positional carrying `choices`
printed `project-dir` where argh printed `{a,b}`. cw now registers the hyphenated name and
renames the `dest` back on the way into the call, so there is no divergence left to forgive
and this docstring is the only trace of it.
"""

import argparse
import os
from typing import Any, Dict, List, Optional

import argh
from argh.assembling import NameMappingPolicy

import cw
from cw.convention import ARGH
from cw.grammar import specs_for_function

#: argparse wraps help text to the terminal width; pin it so goldens are reproducible.
HELP_COLUMNS = "100"

#: Every ``argparse.Action`` field the diff looks at. ``dest`` and ``metavar`` are in the
#: list on purpose: they are where cw's one former divergence used to hide.
ACTION_FIELDS = (
    "dest",
    "option_strings",
    "nargs",
    "type",
    "default",
    "required",
    "action_class",
    "const",
    "help",
    "choices",
    "metavar",
)


def argh_parser(func, *, policy=NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT, prog="prog"):
    """The parser argh 0.31.3 builds for ``func``."""
    parser = argparse.ArgumentParser(
        prog=prog, formatter_class=argh.PARSER_FORMATTER, description=func.__doc__
    )
    argh.set_default_command(parser, func, name_mapping_policy=policy)
    return parser


def cw_parser(func, *, convention=ARGH, config=None, prog="prog"):
    """The parser ``cw.grammar``'s specs describe for ``func``.

    ``cw.cli`` will do exactly this and a little more (subcommands, the ingress stash);
    it does not exist yet, and the grammar is testable without it.
    """
    parser = argparse.ArgumentParser(
        prog=prog, formatter_class=cw.ArghHelpFormatter, description=func.__doc__
    )
    for spec in specs_for_function(func, convention=convention, config=config):
        args, kwargs = spec.add_argument_args()
        parser.add_argument(*args, **kwargs)
    return parser


def normalise_action(action: argparse.Action) -> Dict[str, Any]:
    """One action as a comparable dict. Nothing is collapsed; see the module docstring."""
    row = {
        "dest": action.dest,
        "option_strings": tuple(action.option_strings),
        "nargs": action.nargs,
        "type": getattr(action.type, "__name__", action.type),
        "default": action.default,
        "required": action.required,
        "action_class": type(action).__name__,
        "const": action.const,
        "help": action.help,
        "choices": action.choices,
        "metavar": action.metavar,
    }
    return row


def action_table(parser: argparse.ArgumentParser) -> List[Dict[str, Any]]:
    """Every action of ``parser``, normalised, in declaration order."""
    return [normalise_action(action) for action in parser._actions]


def render_help(parser: argparse.ArgumentParser) -> str:
    """``parser.format_help()`` at a pinned width."""
    before = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = HELP_COLUMNS
    try:
        return parser.format_help()
    finally:
        if before is None:
            del os.environ["COLUMNS"]
        else:
            os.environ["COLUMNS"] = before


def diff_tables(
    left: List[Dict[str, Any]],
    right: List[Dict[str, Any]],
    *,
    ignore: Optional[set] = None,
) -> List[str]:
    """Human-readable differences between two action tables, empty when identical."""
    ignore = ignore or set()
    problems = []
    if len(left) != len(right):
        problems.append(
            f"different number of arguments: argh has {len(left)}, cw has {len(right)}\n"
            f"    argh: {[row['dest'] for row in left]}\n"
            f"    cw  : {[row['dest'] for row in right]}"
        )
        return problems
    for a, b in zip(left, right):
        for field in ACTION_FIELDS:
            if field in ignore:
                continue
            if a[field] != b[field]:
                problems.append(
                    f"{a['dest']}.{field}: argh={a[field]!r} cw={b[field]!r}"
                )
    return problems


def build_both(case):
    """Build both parsers, or report that both refused.

    A signature-and-override combination argh rejects (`@arg('--synth')` on a parameter
    the policy makes positional) must be rejected by cw too. "Both refuse" is as much a
    parity claim as "both produce this table", so it gets the same treatment rather than
    being excluded from the corpus.
    """
    left = _attempt(lambda: argh_parser(case.func, policy=case.policy))
    right = _attempt(
        lambda: cw_parser(case.func, convention=case.convention, config=case.config)
    )
    return left, right


def _attempt(build):
    try:
        return build(), None
    except Exception as exc:  # noqa: BLE001 - the exception IS the result here
        return None, exc
