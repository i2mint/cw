"""Record a CLI's behaviour before a migration and assert it after.

This file is **standalone** (D4). Its module-level imports are ``argparse``, ``difflib``,
``json``, ``os``, ``re``, ``shlex``, ``subprocess`` and ``sys`` -- stdlib, all of it, and no
``cw`` anywhere. That is not tidiness; it is the whole point. The fleet has 22 repos whose
CLI is being deleted and 35 that are argparse-only and will never depend on ``cw``, and all
of them want the same thing: *proof that the command line did not change*. Copy this one
file into such a repo and it works.

Three entry points, in the order you meet them:

``characterize(prog, cases)``
    Run a **real console script** as a subprocess against a list of ``argv`` vectors and
    record what a shell would see. Do this **before** you touch anything.

``replay(golden)`` / ``assert_replay(golden)``
    Run it again and diff. Do this **after**.

``parity()``
    cw's own gate: replay the committed argh-recorded goldens for the seven hard-case
    shapes through cw. This one -- and only this one -- imports ``cw``, lazily, inside the
    function, so the standalone guarantee above survives.

The golden format: one format, three tiers
------------------------------------------

===== =========================================================== =================
tier  content                                                     treatment
===== =========================================================== =================
1     ``argv``, ``returncode``, full ``stdout``, full ``stderr``   **asserted**
2     the normalised ``usage:`` line                               **asserted**
3     the full ``--help`` body                                     snapshot only
===== =========================================================== =================

Tier 3 is never asserted because ``--help`` wraps to ``COLUMNS`` and a big CLI's help is
hundreds of lines; asserting it would produce false failures forever. It is diffed
advisorily by :func:`diff_help`. Tier 2 does most of the work tier 3 looks like it would:
argparse's ``usage:`` line names **every** option a parser has, so a lost flag, a lost short
flag or a changed ``nargs`` all show up there, whitespace-collapsed and width-independent.

Windows (ADR: option A, "normalise")
------------------------------------

Recorded text is stored newline-normalised (``\\r\\n`` and ``\\r`` both become ``\\n``) and
every comparison normalises both sides, so a golden recorded on a Mac asserts cleanly on a
Windows runner. The subprocess environment pins ``COLUMNS``, ``PYTHONUTF8``,
``PYTHONIOENCODING``, ``PYTHONHASHSEED`` and ``TERM`` so the bytes are reproducible rather
than merely comparable. :func:`read_cases` reads a JSON-list form as well as a ``shlex``
line, because ``shlex`` is POSIX-only and a Windows user must never need it. And
:func:`parity` spawns no subprocess at all -- it runs in-process against shipped fixtures --
so the ``.exe`` console-script shim and the cp1252 console never enter the picture.

    >>> normalise_text('a\\r\\nb\\r\\n')
    'a\\nb\\n'
    >>> normalise_usage('usage: prog [-h]\\n            [--wrapped]\\n\\nSome description.')
    'usage: prog [-h] [--wrapped]'
"""

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys

__all__ = [
    "GOLDEN_VERSION",
    "RECORDING_ENV",
    "assert_replay",
    "capture",
    "characterize",
    "compare_case",
    "diff_help",
    "load_golden",
    "main",
    "normalise_text",
    "normalise_usage",
    "parity",
    "pinned_env",
    "read_cases",
    "replay",
]

#: Bumped when the golden JSON schema changes incompatibly. A golden that does not carry
#: this key is not a golden, and saying so beats a :class:`KeyError` three frames later.
GOLDEN_VERSION = 1

#: Terminal width pinned during recording. ``argparse`` wraps help and usage text to
#: ``shutil.get_terminal_size()``, which reads ``COLUMNS`` first -- so pinning it is what
#: makes recorded text reproducible on a machine with a different terminal.
DFLT_COLUMNS = "100"

#: The environment pinned around every recorded and replayed run. Everything here exists to
#: remove a source of variation between two machines, not to make the CLI behave specially.
RECORDING_ENV = {
    "COLUMNS": DFLT_COLUMNS,
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONHASHSEED": "0",
    "TERM": "dumb",
    "NO_COLOR": "1",
}

#: Environment variables actively *removed* before a recorded run: they make argcomplete or
#: a pager take over, which is not the behaviour anybody wants to pin.
UNSET_ENV = ("_ARGCOMPLETE", "COMP_LINE", "COMP_POINT", "PAGER", "LINES")

#: An ``argv`` containing one of these asks for a ``--help`` body, which is tier 3.
HELP_FLAGS = ("-h", "--help")

#: What a tier-1 case asserts, and what a tier-3 case asserts. The difference is the whole
#: of the three-tier rule; there is no other place in this file where a tier is consulted.
TIER1_FIELDS = ("returncode", "stdout", "stderr", "usage")
TIER3_FIELDS = ("returncode", "usage")

#: Seconds a single recorded case may take before it is reported as a failure.
DFLT_TIMEOUT = 30

#: Where :func:`parity` looks when it is not told. Ships inside the package, so the gate
#: runs from an installed ``cw`` and not only from a checkout.
DFLT_GOLDENS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tests", "goldens"
)


# ---------------------------------------------------------------------------------------
# Normalisation -- the two functions every comparison goes through
# ---------------------------------------------------------------------------------------

#: The ``usage:`` block: from a line starting ``usage:`` up to the first blank line.
_USAGE = re.compile(r"^usage:.*?(?=\n[ \t]*\n|\Z)", re.MULTILINE | re.DOTALL)


def normalise_text(text: str) -> str:
    """Newline-normalise ``text`` so a Mac recording asserts on a Windows runner.

    This is the whole of the Windows decision (option A) as it applies to tier 1. It is
    deliberately the *only* normalisation applied to recorded output -- anything else would
    be forgiving a real difference.

    >>> normalise_text('one\\r\\ntwo\\rthree\\n')
    'one\\ntwo\\nthree\\n'
    >>> normalise_text(None) is None
    True
    """
    if text is None:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalise_usage(text: str) -> str:
    """The ``usage:`` block of ``text``, whitespace-collapsed and width-independent.

    ``argparse`` wraps the usage block to the terminal width, so the same parser prints it
    over two lines at ``COLUMNS=100`` and five at ``COLUMNS=50``. Collapsing every run of
    whitespace to one space makes the two equal while keeping what actually matters: which
    options exist, in which order, with which metavars.

    >>> normalise_usage('usage: prog [-h] [-v]\\n\\npositional arguments:\\n  x')
    'usage: prog [-h] [-v]'
    >>> normalise_usage('usage: prog\\n       [--a]\\n       [--b] x')
    'usage: prog [--a] [--b] x'

    Text with no usage block at all -- a command that just printed its result -- normalises
    to the empty string rather than raising, because "this case shows no usage line" is a
    fact worth asserting too:

    >>> normalise_usage('hello world\\n')
    ''
    """
    match = _USAGE.search(normalise_text(text) or "")
    return " ".join(match.group(0).split()) if match else ""


#: A CPython object repr's memory address: ``<list_iterator object at 0x1017642e0>``.
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,16}")


def scrub_addresses(text: str) -> str:
    """Replace object-repr memory addresses with a placeholder.

    The one **content** normalisation in this module, and it exists because a golden that
    records ``<list_iterator object at 0x1017642e0>`` asserts the heap layout of the machine
    that recorded it. It is applied at record time as well as at replay time, so the
    committed golden shows what is actually being asserted rather than hiding it in the
    comparator.

    >>> scrub_addresses('<map object at 0x104f2b910>')
    '<map object at 0xADDR>'
    """
    return _ADDRESS.sub("0xADDR", text) if text else text


def _usage_of(stdout: str, stderr: str) -> str:
    """The normalised ``usage:`` line, from wherever the CLI put it.

    ``--help`` writes it to stdout and a usage error writes it to stderr, and a golden
    should not have to know which happened.
    """
    return normalise_usage(stdout) or normalise_usage(stderr)


# ---------------------------------------------------------------------------------------
# Cases -- the argv vectors, in either of two spellings
# ---------------------------------------------------------------------------------------


def _as_argv(case) -> list:
    """One case as a list of strings, from either spelling.

    A JSON list is the cross-platform form; a ``shlex`` line is the convenient one.

    >>> _as_argv('quickstart . --ignore')
    ['quickstart', '.', '--ignore']
    >>> _as_argv('["quickstart", ".", "--ignore"]')
    ['quickstart', '.', '--ignore']
    >>> _as_argv(['already', 'split'])
    ['already', 'split']
    """
    if not isinstance(case, str):
        return [str(part) for part in case]
    stripped = case.strip()
    if stripped.startswith("["):
        return [str(part) for part in json.loads(stripped)]
    return shlex.split(stripped)


def read_cases(path) -> list:
    """The ``argv`` vectors in a cases file, one per line.

    Each line is either a JSON list -- ``["a", "b c"]`` -- or a POSIX ``shlex`` line.
    Blank lines and ``#`` comments are skipped, and a line of ``[]`` (or nothing but
    whitespace before a comment) is *not* a way to spell the empty argv: use ``[]``
    explicitly.

    Both spellings exist for one reason: ``shlex`` is POSIX-only, so a Windows user writing
    a corpus must have a form that never reaches it.
    """
    with open(path, "r", encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    return [
        _as_argv(line)
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _tier_of(argv, *, help_flags=HELP_FLAGS) -> int:
    """``3`` if ``argv`` asks for a help body, else ``1``.

    >>> _tier_of(['spawn', '-x']), _tier_of(['spawn', '--help'])
    (1, 3)
    """
    return 3 if any(flag in argv for flag in help_flags) else 1


# ---------------------------------------------------------------------------------------
# Running a case -- in a subprocess (characterize/replay) or in-process (parity)
# ---------------------------------------------------------------------------------------


def _env_for(env=None) -> dict:
    """``os.environ`` with the recording pins applied and the disruptors removed."""
    resolved = dict(os.environ)
    resolved.update(RECORDING_ENV)
    resolved.update(env or {})
    for name in UNSET_ENV:
        resolved.pop(name, None)
    return resolved


class pinned_env:
    """Context manager applying :data:`RECORDING_ENV` to the **current** process.

    :func:`characterize` hands the pins to a subprocess, where they belong. :func:`parity`
    runs in-process and needs the same pins applied here instead -- ``COLUMNS`` above all,
    since that is what ``argparse`` wraps to.

    >>> with pinned_env():
    ...     os.environ['COLUMNS']
    '100'
    """

    def __init__(self, env=None):
        self.env = dict(RECORDING_ENV, **(env or {}))
        self._saved = {}

    def __enter__(self):
        for name in list(self.env) + list(UNSET_ENV):
            self._saved[name] = os.environ.get(name)
        os.environ.update(self.env)
        for name in UNSET_ENV:
            os.environ.pop(name, None)
        return self

    def __exit__(self, *exc_info):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return False


def _exit_status(exc: SystemExit) -> tuple:
    """``(returncode, extra_stderr)`` -- the exit the interpreter would give ``exc``.

    ``SystemExit(None)`` is 0, ``SystemExit(int)`` is that int, and ``SystemExit(str)``
    prints the string to stderr and exits 1. Reproducing all three is what lets an
    in-process run be compared against a subprocess recording.

    >>> _exit_status(SystemExit()), _exit_status(SystemExit(3)), _exit_status(SystemExit('bye'))
    ((0, ''), (3, ''), (1, 'bye\\n'))
    """
    code = exc.code
    if code is None:
        return 0, ""
    if isinstance(code, int):
        return code, ""
    return 1, f"{code}\n"


def capture(call) -> dict:
    """Run ``call()`` with file descriptors 1 and 2 captured; report what a shell would see.

    Capture is at the **file-descriptor** level, and ``sys.stdout`` / ``sys.stderr`` are
    then re-pointed at those same descriptors. Both halves are load-bearing, for opposite
    reasons:

    * the descriptor half, because argh binds ``output_file=sys.stdout`` at import
      (``dispatching.py:77``) and writes through that original object forever after -- a
      ``redirect_stdout`` around it captures nothing at all; and
    * the ``sys`` half, because a *caller* may already have rebound ``sys.stdout`` to
      something that is not descriptor 1. pytest does exactly this, and without the second
      half every command's output would land in pytest's buffer and the recording would
      come back empty.

    Using one mechanism for both sides of a diff is what makes the diff mean something, so
    it has to be the mechanism that works in every process either side might run in.

    ``call`` takes no arguments and returns an exit code, or raises :class:`SystemExit`. An
    exception that escapes is reported as ``returncode`` 1 with its ``Type: message`` line
    on stderr -- what the interpreter shows, minus a traceback whose file paths would differ
    on every machine.

    The example writes to the descriptor rather than through ``print`` for a reason worth
    knowing: ``doctest`` rebinds ``sys.stdout`` to collect a doctest's own output, so a
    ``print`` here would be intercepted by ``doctest`` and never reach the descriptor at
    all. Real CLIs write to ``sys.stdout``, which *is* the descriptor -- which is why this
    mechanism works where it matters and looks awkward only here.

    >>> capture(lambda: os.write(1, b'hi\\n') and 0)
    {'returncode': 0, 'stdout': 'hi\\n', 'stderr': ''}
    >>> capture(lambda: sys.exit('bye'))
    {'returncode': 1, 'stdout': '', 'stderr': 'bye\\n'}
    >>> capture(lambda: 1 // 0)['stderr']
    'ZeroDivisionError: integer division or modulo by zero\\n'
    """
    import tempfile  # local: only this function needs it, and D4 counts module imports

    saved_streams = (sys.stdout, sys.stderr)
    _flush(sys.stdout, sys.stderr)
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        saved_fds = (os.dup(1), os.dup(2))
        trailer = ""
        try:
            os.dup2(out_file.fileno(), 1)
            os.dup2(err_file.fileno(), 2)
            sys.stdout = _stream_on_fd(1)
            sys.stderr = _stream_on_fd(2)
            try:
                returncode = call() or 0
            except SystemExit as exc:
                returncode, trailer = _exit_status(exc)
            except BaseException as exc:  # noqa: BLE001 - a crash IS the recorded fact
                trailer = f"{type(exc).__name__}: {exc}\n"
                returncode = 1
        finally:
            # Flush the streams we installed AND the ones we displaced, in that order.
            # The displaced ones matter and are easy to forget: argh writes through the
            # `sys.stdout` object it captured at import, which is block-buffered whenever
            # descriptor 1 is a pipe or a redirect rather than a terminal. Skip this flush
            # and its buffer drains *after* the descriptor is restored -- so recording
            # through a pipe silently produces empty goldens, and only through a terminal
            # produces real ones. That is a difference no reviewer would ever suspect.
            _flush(sys.stdout, sys.stderr, *saved_streams)
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout, sys.stderr = saved_streams
            for saved, fd in zip(saved_fds, (1, 2)):
                os.dup2(saved, fd)
                os.close(saved)
        out_file.seek(0)
        err_file.seek(0)
        stdout = out_file.read().decode("utf-8", "replace")
        stderr = err_file.read().decode("utf-8", "replace") + trailer
    return {
        "returncode": returncode,
        "stdout": normalise_text(stdout),
        "stderr": normalise_text(stderr),
    }


def _stream_on_fd(fd: int):
    """A text stream writing to ``fd``, which does not own it.

    ``closefd=False`` matters: :func:`capture` closes these to flush them, and closing the
    descriptor with them would take the process's real stdout down with it.
    """
    return open(fd, "w", encoding="utf-8", errors="replace", closefd=False)


def _flush(*streams) -> None:
    """Flush what can be flushed. A stream already closed by the command is not an error."""
    for stream in streams:
        try:
            stream.flush()
        except (ValueError, OSError):  # already closed, or not a real stream
            pass


def _as_command(prog) -> list:
    """``prog`` as a command list, from either spelling.

    A list is the cross-platform form and is taken as-is. A string is ``shlex``-split,
    which is POSIX-only -- hence the list form, and hence this docstring.

    >>> _as_command('python -m cw')
    ['python', '-m', 'cw']
    >>> _as_command(['python', '-m', 'cw'])
    ['python', '-m', 'cw']
    """
    return shlex.split(prog) if isinstance(prog, str) else [str(part) for part in prog]


def _run_subprocess(command, argv, *, env, cwd, timeout) -> dict:
    """One case, run as a real subprocess. The heart of the standalone half."""
    try:
        done = subprocess.run(
            command + list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": f"cw.testing: timed out after {timeout}s\n",
        }
    return {
        "returncode": done.returncode,
        "stdout": normalise_text(done.stdout),
        "stderr": normalise_text(done.stderr),
    }


def _record(run_one, argv, *, help_flags=HELP_FLAGS) -> dict:
    """A full case record -- the three tiers -- from a ``(argv) -> outcome`` callable."""
    outcome = run_one(argv)
    case = {"argv": list(argv), "tier": _tier_of(argv, help_flags=help_flags)}
    case.update(outcome)
    for stream in ("stdout", "stderr"):
        case[stream] = scrub_addresses(case[stream])
    case["usage"] = _usage_of(case["stdout"], case["stderr"])
    return case


# ---------------------------------------------------------------------------------------
# characterize -- record what a real console script does today
# ---------------------------------------------------------------------------------------


def characterize(
    prog,
    cases,
    *,
    out_path=None,
    env=None,
    cwd=None,
    timeout=DFLT_TIMEOUT,
    note=None,
) -> dict:
    """Record a real console script's behaviour against ``cases``, as a golden.

    Args:
        prog: The command, as a list (``['python', '-m', 'priv']``) or a POSIX string.
            The list form is the cross-platform one.
        cases: ``argv`` vectors -- a list of lists, a list of ``shlex`` strings, or the
            path of a cases file readable by :func:`read_cases`.
        out_path: Where to write the golden JSON. ``None`` returns it without writing.
        env: Extra environment for the subprocess, over :data:`RECORDING_ENV`.
        cwd: Working directory for the subprocess.
        timeout: Seconds one case may take.
        note: Free text stored in the golden -- the commit you recorded at, say.

    Returns:
        The golden, as a plain dict. JSON-serialisable, with sorted keys when written, so
        re-recording an unchanged CLI produces a byte-identical file.

    Do this **before** the migration, and commit the result. That is the entire method:
    everything else in this module compares against what you recorded here.
    """
    command = _as_command(prog)
    if isinstance(cases, (str, bytes, os.PathLike)):
        cases = read_cases(cases)
    resolved = _env_for(env)

    def run_one(argv):
        return _run_subprocess(command, argv, env=resolved, cwd=cwd, timeout=timeout)

    golden = {
        "cw_golden": GOLDEN_VERSION,
        "prog": command,
        "env": dict(RECORDING_ENV, **(env or {})),
        "newlines": "lf",
        "recorded_with": _provenance(),
        "note": note,
        "cases": [_record(run_one, _as_argv(case)) for case in cases],
    }
    if out_path is not None:
        write_golden(golden, out_path)
    return golden


def _provenance() -> dict:
    """Who recorded this golden and with what -- so a stale one can be spotted."""
    import platform  # local: provenance is the only caller, and D4 counts module imports

    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "implementation": platform.python_implementation(),
    }


def write_golden(golden: dict, path) -> None:
    """Write ``golden`` to ``path``: sorted keys, two-space indent, trailing newline.

    Stability is the requirement, not prettiness. Re-recording an unchanged CLI must
    produce a file ``git diff`` calls empty, or nobody will ever re-record.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(golden, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def load_golden(golden) -> dict:
    """A golden, from a dict or the path of one, validated enough to fail usefully.

    >>> load_golden({'cw_golden': 1, 'cases': []})['cases']
    []
    >>> load_golden({'cases': []})
    Traceback (most recent call last):
      ...
    ValueError: not a cw golden (no 'cw_golden' key): a dict
    """
    if isinstance(golden, (str, bytes, os.PathLike)):
        with open(golden, "r", encoding="utf-8") as stream:
            loaded = json.load(stream)
        where = str(golden)
    else:
        loaded, where = golden, "a dict"
    if not isinstance(loaded, dict) or "cw_golden" not in loaded:
        raise ValueError(f"not a cw golden (no 'cw_golden' key): {where}")
    if loaded["cw_golden"] != GOLDEN_VERSION:
        raise ValueError(
            f"golden {where} is format version {loaded['cw_golden']}, "
            f"but this cw.testing reads version {GOLDEN_VERSION}. Re-record it."
        )
    return loaded


# ---------------------------------------------------------------------------------------
# compare -- the one place a difference is decided
# ---------------------------------------------------------------------------------------


def compare_case(recorded: dict, fresh: dict) -> str:
    """The empty string if ``fresh`` matches ``recorded``, else a readable diff.

    Which fields are compared is the tier rule and nothing else: tier 1 asserts the
    return code and both streams in full, tier 3 asserts the return code and the normalised
    ``usage:`` line and leaves the ``--help`` body to :func:`diff_help`.

    >>> a = {'tier': 1, 'returncode': 0, 'stdout': 'hi\\n', 'stderr': '', 'usage': ''}
    >>> compare_case(a, dict(a))
    ''
    >>> print(compare_case(a, dict(a, stdout='ho\\n')))
    stdout:
      - hi
      + ho
    """
    fields = TIER1_FIELDS if recorded.get("tier", 1) == 1 else TIER3_FIELDS
    chunks = []
    for field in fields:
        want, got = recorded.get(field), fresh.get(field)
        if field == "returncode":
            if want != got:
                chunks.append(f"returncode:\n  - {want!r}\n  + {got!r}")
            continue
        want, got = normalise_text(want), normalise_text(got)
        if want != got:
            chunks.append(f"{field}:\n" + _text_diff(want, got))
    return "\n".join(chunks)


def _text_diff(want, got) -> str:
    """A unified-ish diff of two blobs, indented so it reads under a field name."""
    lines = difflib.ndiff(
        (want or "").splitlines(keepends=False), (got or "").splitlines(keepends=False)
    )
    return "\n".join(f"  {line}" for line in lines if not line.startswith("? "))


# ---------------------------------------------------------------------------------------
# replay -- assert the console script still does what it did
# ---------------------------------------------------------------------------------------


def _expected(expect_diff) -> set:
    """``expect_diff`` as a set of argv tuples, from any of the spellings a caller uses."""
    return {tuple(_as_argv(case)) for case in (expect_diff or ())}


def replay(
    golden,
    *,
    prog=None,
    env=None,
    cwd=None,
    expect_diff=(),
    timeout=DFLT_TIMEOUT,
) -> list:
    """Re-run a golden's cases and report, per case, whether the behaviour survived.

    Args:
        golden: A golden dict, or the path of one.
        prog: The command to run now. ``None`` reuses the golden's own ``prog``, which is
            what you want after an in-place migration and not what you want when the entry
            point moved.
        env, cwd, timeout: As :func:`characterize`.
        expect_diff: ``argv`` vectors whose behaviour you **intend** to have changed. They
            are reported as ``expected-diff``, never as a failure -- and an ``expect_diff``
            entry that turns out identical is reported as ``unexpected-match``, because a
            migration note claiming a break that did not happen is also wrong.

    Returns:
        One dict per case: ``argv``, ``status`` and ``diff``.

    Statuses are ``identical``, ``differs``, ``expected-diff`` and ``unexpected-match``.
    :func:`assert_replay` is the version that raises.
    """
    golden = load_golden(golden)
    command = _as_command(prog if prog is not None else golden["prog"])
    resolved = _env_for(dict(golden.get("env") or {}, **(env or {})))
    intended = _expected(expect_diff)
    results = []
    for recorded in golden["cases"]:
        argv = list(recorded["argv"])
        fresh = _record(
            lambda a: _run_subprocess(
                command, a, env=resolved, cwd=cwd, timeout=timeout
            ),
            argv,
        )
        results.append(_verdict(recorded, fresh, intended))
    return results


def _verdict(recorded: dict, fresh: dict, intended: set) -> dict:
    """One case's outcome, with ``expect_diff`` applied in both directions."""
    argv = list(recorded["argv"])
    diff = compare_case(recorded, fresh)
    if tuple(argv) in intended:
        status = "expected-diff" if diff else "unexpected-match"
    else:
        status = "differs" if diff else "identical"
    return {"argv": argv, "status": status, "diff": diff}


def assert_replay(golden, **kwargs) -> None:
    """:func:`replay`, raising :class:`AssertionError` with a readable diff on any failure.

    ``expected-diff`` cases are reported in the message when something *else* failed, so a
    reader can see what was intended alongside what was not, but they never cause a raise.
    An ``unexpected-match`` does: it means the migration note is wrong.
    """
    results = replay(golden, **kwargs)
    bad = [r for r in results if r["status"] in ("differs", "unexpected-match")]
    if not bad:
        return
    report = "\n\n".join(_report_line(r) for r in bad)
    raise AssertionError(
        f"{len(bad)} of {len(results)} cases changed behaviour:\n\n{report}"
    )


def _report_line(result: dict) -> str:
    """One failing case, formatted for a human reading a test failure."""
    argv = " ".join(shlex.quote(part) for part in result["argv"]) or "(no arguments)"
    if result["status"] == "unexpected-match":
        return f"$ {argv}\n  expect_diff listed this case, but it is unchanged."
    return f"$ {argv}\n{result['diff']}"


def diff_help(golden, *, prog=None, timeout=DFLT_TIMEOUT, env=None, cwd=None) -> str:
    """The advisory tier-3 diff: how every ``--help`` body changed. Never asserted.

    ``--help`` output is the right thing for a human to review after a migration and the
    wrong thing for a machine to assert: it wraps to ``COLUMNS`` and it changes for reasons
    nobody minds. This returns it as text for a review queue, and returns ``''`` when
    nothing moved.
    """
    golden = load_golden(golden)
    command = _as_command(prog if prog is not None else golden["prog"])
    resolved = _env_for(dict(golden.get("env") or {}, **(env or {})))
    chunks = []
    for recorded in (c for c in golden["cases"] if c.get("tier") == 3):
        argv = list(recorded["argv"])
        fresh = _run_subprocess(command, argv, env=resolved, cwd=cwd, timeout=timeout)
        diff = "\n".join(
            difflib.unified_diff(
                (recorded["stdout"] or "").splitlines(),
                (normalise_text(fresh["stdout"]) or "").splitlines(),
                fromfile="recorded",
                tofile="now",
                lineterm="",
            )
        )
        if diff:
            chunks.append(f"$ {' '.join(argv)}\n{diff}")
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------------------
# parity -- cw's own gate. The ONLY function here that imports cw, and it does it lazily.
# ---------------------------------------------------------------------------------------


def parity(goldens_dir=None, *, out=None, verbose=False) -> int:
    """Replay the committed argh-recorded goldens through cw. Exit code, not an exception.

    This is the definition of v1: it prints ``N shapes / M cases: identical`` and returns
    ``0``. What it asserts, per case, with **every seam on its default**
    (``convention=cw.ARGH``, ``decode=cw.argh_decode``, ``egress=cw.argh_egress``): exit
    code, stdout, stderr, and the normalised ``usage:`` line, byte-identical to what argh
    0.31.3 produced. The ``--help`` bodies are recorded and not asserted (tier 3).

    It is deliberately **self-contained**. The goldens were recorded from real argh against
    the seven hard-case *shapes* in :mod:`cw.tests.fixtures`, not against the seven fleet
    repos -- so this needs stdlib plus cw, installs no fleet package, pulls no argh, and
    runs on Windows. The seven real repos are gated separately, by :func:`replay` in each
    repo's own CI, which is what a migration test is for.

    Args:
        goldens_dir: Where the goldens are. ``None`` is the copy shipped inside ``cw``.
        out: Where the report goes. ``None`` is :data:`sys.stdout`, resolved now.
        verbose: Also print a line per shape that passed.

    Returns:
        ``0`` when every case is identical, ``1`` otherwise.
    """
    out = sys.stdout if out is None else out
    goldens_dir = DFLT_GOLDENS_DIR if goldens_dir is None else goldens_dir
    paths = sorted(
        os.path.join(goldens_dir, name)
        for name in os.listdir(goldens_dir)
        if name.endswith(".json")
    )
    if not paths:
        out.write(f"no goldens in {goldens_dir}\n")
        return 1

    from cw.tests import fixtures  # lazy on purpose: D4 keeps this file cw-free

    shapes, cases, failures = 0, 0, []
    with pinned_env():
        for path in paths:
            golden = load_golden(path)
            shape = fixtures.shape_named(golden["shape"])
            shapes += 1
            for recorded in golden["cases"]:
                cases += 1
                fresh = _record(
                    lambda a: fixtures.cw_outcome(shape, a), recorded["argv"]
                )
                verdict = _verdict(recorded, fresh, set())
                if verdict["status"] == "differs":
                    failures.append((shape.name, verdict))
            if verbose:
                out.write(f"  {shape.name}: {len(golden['cases'])} cases\n")

    for name, verdict in failures:
        out.write(f"\n[{name}] {_report_line(verdict)}\n")
    verdict_word = "identical" if not failures else f"{len(failures)} DIFFER"
    out.write(f"{shapes} shapes / {cases} cases: {verdict_word}\n")
    return 1 if failures else 0


# ---------------------------------------------------------------------------------------
# python -m cw.testing
# ---------------------------------------------------------------------------------------


def _cli() -> argparse.ArgumentParser:
    """``python -m cw.testing``'s parser, hand-built with argparse.

    Hand-built rather than built with :func:`cw.dispatch`, which would be the nicer dogfood,
    because this module must not import ``cw`` (D4) -- and a CLI that quietly broke the one
    property the module exists for would be an expensive joke.
    """
    parser = argparse.ArgumentParser(
        prog="python -m cw.testing", description=__doc__.split("\n\n")[0]
    )
    subs = parser.add_subparsers(dest="command", metavar="command")

    gate = subs.add_parser("parity", help="run cw's committed-golden parity gate")
    gate.add_argument("goldens_dir", nargs="?", default=None)
    gate.add_argument("-v", "--verbose", action="store_true")

    record = subs.add_parser("characterize", help="record a console script's behaviour")
    record.add_argument("prog", help="the command, e.g. 'python -m priv'")
    record.add_argument("--cases", required=True, help="a cases file")
    record.add_argument("-o", "--out-path", required=True)
    record.add_argument("--note", default=None)

    again = subs.add_parser("replay", help="re-run a golden and diff")
    again.add_argument("golden")
    again.add_argument("--prog", default=None)
    again.add_argument("--expect-diff", action="append", default=[])

    advisory = subs.add_parser("diff-help", help="the advisory tier-3 --help diff")
    advisory.add_argument("golden")
    advisory.add_argument("--prog", default=None)
    return parser


def main(argv=None) -> int:
    """``python -m cw.testing``. Returns an exit code; the module raises it as SystemExit."""
    parser = _cli()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.command is None:
        parser.print_usage()
        return 0
    if args.command == "parity":
        return parity(args.goldens_dir, verbose=args.verbose)
    if args.command == "characterize":
        golden = characterize(
            args.prog, read_cases(args.cases), out_path=args.out_path, note=args.note
        )
        print(f"recorded {len(golden['cases'])} cases to {args.out_path}")
        return 0
    if args.command == "diff-help":
        print(diff_help(args.golden, prog=args.prog) or "no --help changes")
        return 0
    results = replay(args.golden, prog=args.prog, expect_diff=args.expect_diff)
    bad = [r for r in results if r["status"] in ("differs", "unexpected-match")]
    for result in bad:
        print(_report_line(result))
    print(f"{len(results) - len(bad)}/{len(results)} identical")
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
