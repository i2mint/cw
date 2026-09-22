# cw.testing

Record a CLI’s behaviour before a migration and assert it after.

This file is **standalone** (D4). Its module-level imports are `argparse`,
`contextlib`, `difflib`, `json`, `os`, `re`, `shlex`, `subprocess` and
`sys` – stdlib, all of it, and no `cw` anywhere. That is not tidiness; it is the whole point. The fleet has 22 repos whose
CLI is being deleted and 35 that are argparse-only and will never depend on `cw`, and all
of them want the same thing: *proof that the command line did not change*. Copy this one
file into such a repo and it works.

Three entry points, in the order you meet them:

`characterize(prog, cases)`
: Run a **real console script** as a subprocess against a list of `argv` vectors and
  record what a shell would see. Do this **before** you touch anything.

`replay(golden)` / `assert_replay(golden)`
: Run it again and diff. Do this **after**.

`parity()`
: cw’s own gate: replay the committed argh-recorded goldens for the seven hard-case
  shapes through cw. This one – and only this one – imports `cw`, lazily, inside the
  function, so the standalone guarantee above survives.

## The golden format: one format, three tiers

|   tier | content                                            | treatment     |
|--------|----------------------------------------------------|---------------|
|      1 | `argv`, `returncode`, full `stdout`, full `stderr` | **asserted**  |
|      2 | the normalised `usage:` line                       | **asserted**  |
|      3 | the full `--help` body                             | snapshot only |

Tier 3’s body is not asserted by default because `--help` wraps to `COLUMNS` and
because CPython itself rewrites it between versions (3.13 renders `-i, --ignore VALUE`
where 3.12 rendered `-i VALUE, --ignore VALUE`), so a committed golden replayed across a
matrix would fail for reasons nobody caused. Tier 2 does most of the work tier 3 looks like
it would: argparse’s `usage:` line names **every** option a parser has, so a lost flag, a
lost short flag or a changed `nargs` all show up there, whitespace-collapsed and
width-independent.

**What tier 2 cannot see, and what to do about it.** A change of *formatter* – which is
exactly what swapping one dispatcher for another can do – moves the help column and the
description block and touches neither the `usage:` line nor any exit code. So
[`replay()`](#cw.testing.replay) compares the tier-3 body anyway, through `normalise_help()`, and reports
a case whose body moved as the non-fatal status `help-differs` rather than calling it
`identical`. `replay(..., strict_help=True)` (`--strict-help` on the command line)
makes it fatal, which is the right setting for a migration that promised `--help` would
not move; [`diff_help()`](#cw.testing.diff_help) prints the unnormalised difference for a human to read.

## Windows (ADR: option A, “normalise”)

Recorded text is stored newline-normalised (`\r\n` and `\r` both become `\n`) and
every comparison normalises both sides, so a golden recorded on a Mac asserts cleanly on a
Windows runner. The subprocess environment pins `COLUMNS`, `PYTHONUTF8`,
`PYTHONIOENCODING`, `PYTHONHASHSEED` and `TERM`, and `stdin` is pinned closed, so
the bytes are reproducible rather than merely comparable. [`read_cases()`](#cw.testing.read_cases) reads a JSON-list form as well as a `shlex`
line, because `shlex` is POSIX-only and a Windows user must never need it. The `.exe`
a console script is installed as on Windows is scrubbed out of recorded text by
[`scrub_exe_suffix()`](#cw.testing.scrub_exe_suffix), because `argparse` takes its `prog` from
`basename(sys.argv[0])` and would otherwise report `usage: opsward.EXE` on the runner
and `usage: opsward` everywhere else. What *cannot* be scrubbed automatically – because
only the caller knows what belongs in its place – is an absolute path under the recording
user’s home directory, which `argparse` renders into `--help` whenever a default was
computed from `$HOME`; [`characterize()`](#cw.testing.characterize) warns about it at record time instead, via
[`local_path_hits()`](#cw.testing.local_path_hits), since a golden is meant to be committed.

And [`parity()`](#cw.testing.parity) spawns no subprocess at all –
it runs in-process against shipped fixtures – so the console-script shim and the cp1252
console never enter the picture there either.

```pycon
>>> normalise_text('a\r\nb\r\n')
'a\nb\n'
>>> normalise_usage('usage: prog [-h]\n            [--wrapped]\n\nSome description.')
'usage: prog [-h] [--wrapped]'
```

### Module Attributes

| [`GOLDEN_VERSION`](#cw.testing.GOLDEN_VERSION)   | Bumped when the golden JSON schema changes incompatibly.       |
|-------------------------------------------------------------------|----------------------------------------------------------------|
| [`RECORDING_ENV`](#cw.testing.RECORDING_ENV)    | The environment pinned around every recorded and replayed run. |

### Functions

| [`assert_replay`](#cw.testing.assert_replay)(golden, \*\*kwargs)                | [`replay()`](#cw.testing.replay), raising [`AssertionError`](https://docs.python.org/3/builtins/exceptions.html#AssertionError) with a readable diff on any failure.   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`capture`](#cw.testing.capture)(call)                                    | Run `call()` with file descriptors 1 and 2 captured; report what a shell would see.                                                                                                             |
| [`characterize`](#cw.testing.characterize)(prog, cases, \*[, out_path, ...])   | Record a real console script's behaviour against `cases`, as a golden.                                                                                                                          |
| [`compare_case`](#cw.testing.compare_case)(recorded, fresh, \*[, strict_help]) | The empty string if `fresh` matches `recorded`, else a readable diff.                                                                                                                           |
| [`diff_help`](#cw.testing.diff_help)(golden, \*[, prog, timeout, env, cwd]) | The advisory tier-3 diff: how every `--help` body changed.                                                                                                                                      |
| [`load_golden`](#cw.testing.load_golden)(golden)                              | A golden, from a dict or the path of one, validated enough to fail usefully.                                                                                                                    |
| [`local_path_hits`](#cw.testing.local_path_hits)(text, \*[, home])                | Which markers of the recording machine's filesystem does `text` carry?                                                                                                                          |
| [`main`](#cw.testing.main)([argv])                                     | `python -m cw.testing`.                                                                                                                                                                         |
| [`normalise_text`](#cw.testing.normalise_text)(text)                             | Newline-normalise `text` so a Mac recording asserts on a Windows runner.                                                                                                                        |
| [`normalise_usage`](#cw.testing.normalise_usage)(text)                            | The `usage:` block of `text`, whitespace-collapsed and width-independent.                                                                                                                       |
| [`parity`](#cw.testing.parity)([goldens_dir, out, verbose])              | Replay the committed argh-recorded goldens through cw.                                                                                                                                          |
| [`pinned_env`](#cw.testing.pinned_env)([env])                                | Context manager applying [`RECORDING_ENV`](#cw.testing.RECORDING_ENV) to the **current** process.                                                                             |
| [`read_cases`](#cw.testing.read_cases)(path)                                 | The `argv` vectors in a cases file, one per line.                                                                                                                                               |
| [`replay`](#cw.testing.replay)(golden, \*[, prog, env, cwd, ...])        | Re-run a golden's cases and report, per case, whether the behaviour survived.                                                                                                                   |
| [`scrub_addresses`](#cw.testing.scrub_addresses)(text)                            | Replace object-repr memory addresses with a placeholder.                                                                                                                                        |
| [`scrub_exe_suffix`](#cw.testing.scrub_exe_suffix)(text, program)                  | Strip Windows' `.exe` off the program name a CLI prints about itself.                                                                                                                           |

### cw.testing.GOLDEN_VERSION *= 1*

Bumped when the golden JSON schema changes incompatibly. A golden that does not carry
this key is not a golden, and saying so beats a [`KeyError`](https://docs.python.org/3/builtins/exceptions.html#KeyError) three frames later.

### cw.testing.RECORDING_ENV *= {'COLUMNS': '100', 'NO_COLOR': '1', 'PYTHONHASHSEED': '0', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'TERM': 'dumb'}*

The environment pinned around every recorded and replayed run. Everything here exists to
remove a source of variation between two machines, not to make the CLI behave specially.

### cw.testing.assert_replay(golden, \*\*kwargs)

[`replay()`](#cw.testing.replay), raising [`AssertionError`](https://docs.python.org/3/builtins/exceptions.html#AssertionError) with a readable diff on any failure.

`expected-diff` cases are reported in the message when something *else* failed, so a
reader can see what was intended alongside what was not, but they never cause a raise.
An `unexpected-match` does: it means the migration note is wrong.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### cw.testing.capture(call)

Run `call()` with file descriptors 1 and 2 captured; report what a shell would see.

Capture is at the **file-descriptor** level, and `sys.stdout` / `sys.stderr` are
then re-pointed at those same descriptors. Both halves are load-bearing, for opposite
reasons:

* the descriptor half, because argh binds `output_file=sys.stdout` at import
  (`dispatching.py:77`) and writes through that original object forever after – a
  `redirect_stdout` around it captures nothing at all; and
* the `sys` half, because a *caller* may already have rebound `sys.stdout` to
  something that is not descriptor 1. pytest does exactly this, and without the second
  half every command’s output would land in pytest’s buffer and the recording would
  come back empty.

Using one mechanism for both sides of a diff is what makes the diff mean something, so
it has to be the mechanism that works in every process either side might run in.

`call` takes no arguments and returns an exit code, or raises [`SystemExit`](https://docs.python.org/3/builtins/exceptions.html#SystemExit). An
exception that escapes is reported as `returncode` 1 with its `Type: message` line
on stderr – what the interpreter shows, minus a traceback whose file paths would differ
on every machine.

The example writes to the descriptor rather than through `print` for a reason worth
knowing: `doctest` rebinds `sys.stdout` to collect a doctest’s own output, so a
`print` here would be intercepted by `doctest` and never reach the descriptor at
all. Real CLIs write to `sys.stdout`, which *is* the descriptor – which is why this
mechanism works where it matters and looks awkward only here.

```pycon
>>> capture(lambda: os.write(1, b'hi\n') and 0)
{'returncode': 0, 'stdout': 'hi\n', 'stderr': ''}
>>> capture(lambda: sys.exit('bye'))
{'returncode': 1, 'stdout': '', 'stderr': 'bye\n'}
>>> capture(lambda: 1 // 0)['stderr']
'ZeroDivisionError: integer division or modulo by zero\n'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### cw.testing.characterize(prog, cases, , out_path=None, env=None, cwd=None, timeout=30, note=None, warn_on_local_paths=True)

Record a real console script’s behaviour against `cases`, as a golden.

* **Parameters:**
  * **prog** – The command, as a list (`['python', '-m', 'priv']`) or a POSIX string.
    The list form is the cross-platform one.
  * **cases** – `argv` vectors – a list of lists, a list of `shlex` strings, or the
    path of a cases file readable by [`read_cases()`](#cw.testing.read_cases).
  * **out_path** – Where to write the golden JSON. `None` returns it without writing.
  * **env** – Extra environment for the subprocess, over [`RECORDING_ENV`](#cw.testing.RECORDING_ENV).
  * **cwd** – Working directory for the subprocess.
  * **timeout** – Seconds one case may take.
  * **note** – Free text stored in the golden – the commit you recorded at, say.
  * **warn_on_local_paths** – Warn when a recorded body carries a path from this machine
    (see [`local_path_hits()`](#cw.testing.local_path_hits)). Nothing is rewritten either way – the warning
    exists because the golden is about to be committed and this is the last moment
    anybody looks at it.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The golden, as a plain dict. JSON-serialisable, with sorted keys when written, so
  re-recording an unchanged CLI produces a byte-identical file.

Do this **before** the migration, and commit the result. That is the entire method:
everything else in this module compares against what you recorded here.

### cw.testing.compare_case(recorded, fresh, , strict_help=False)

The empty string if `fresh` matches `recorded`, else a readable diff.

Which fields are compared is the tier rule and nothing else: tier 1 asserts the
return code and both streams in full, tier 3 asserts the return code and the normalised
`usage:` line and leaves the `--help` body to [`diff_help()`](#cw.testing.diff_help).

`strict_help=True` adds the `--help` body to a tier-3 case, compared through
`normalise_help()` so that the terminal width cannot decide the verdict. Use it when
the *rendering* is part of what the migration promised not to change – swapping argh’s
formatter for argparse’s stock one is invisible to the tier-3 fields, because it moves
only the help column and the description block.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> a = {'tier': 1, 'returncode': 0, 'stdout': 'hi\n', 'stderr': '', 'usage': ''}
>>> compare_case(a, dict(a))
''
>>> print(compare_case(a, dict(a, stdout='ho\n')))
stdout:
  - hi
  + ho
```

A golden recorded under one CPython replays under another: only argparse’s own
version-dependent rendering is forgiven, and it is forgiven on both sides (see
`canonical_argparse_text()`).

```pycon
>>> quoted = "err: invalid choice: 'q' (choose from 'a', 'b')"
>>> bare = "err: invalid choice: 'q' (choose from a, b)"
>>> compare_case({'tier': 3, 'returncode': 2, 'usage': quoted},
...              {'tier': 3, 'returncode': 2, 'usage': bare})
''
```

### cw.testing.diff_help(golden, , prog=None, timeout=30, env=None, cwd=None)

The advisory tier-3 diff: how every `--help` body changed. Never asserted.

`--help` output is the right thing for a human to review after a migration and the
wrong thing for a machine to assert: it wraps to `COLUMNS` and it changes for reasons
nobody minds. This returns it as text for a review queue, and returns `''` when
nothing moved.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### cw.testing.load_golden(golden)

A golden, from a dict or the path of one, validated enough to fail usefully.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> load_golden({'cw_golden': 1, 'cases': []})['cases']
[]
>>> load_golden({'cases': []})
Traceback (most recent call last):
  ...
ValueError: not a cw golden (no 'cw_golden' key): a dict
```

### cw.testing.local_path_hits(text, , home='~')

Which markers of the recording machine’s filesystem does `text` carry?

The third field with [`scrub_addresses()`](#cw.testing.scrub_addresses)’s problem. `argparse` renders parameter
defaults into `--help`, defaults are routinely computed from `$HOME`, and a golden
is documented to be **committed** – so a recorded body routinely carries an absolute
path under the recording user’s home directory, into a public repo. Unlike an address
it cannot simply be scrubbed: what to put in its place is the caller’s decision, not
this module’s. So this reports, and [`characterize()`](#cw.testing.characterize) warns.

* **Parameters:**
  * **text** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A recorded `stdout` or `stderr` body.
  * **home** – The home directory to look for, `~` expanded. Defaults to the running
    user’s; pass `None` to look only for the generic `HOME_ROOTS`.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)
* **Returns:**
  The offending substrings, most specific first, without duplicates. Empty when the
  text is clean – so it reads as a predicate too.

```pycon
>>> local_path_hits('usage: x [-h]', home=None)
[]
>>> local_path_hits('  --rootdir ROOTDIR   (default: /home/ada/.config/x)', home=None)
['/home/']
>>> local_path_hits(r'default: C:\Users\ada\AppData', home=None)
['C:\\Users']
>>> local_path_hits('default: /opt/ada/.config/x', home='/opt/ada')
['/opt/ada']
```

### cw.testing.main(argv=None)

`python -m cw.testing`. Returns an exit code; the module raises it as SystemExit.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### cw.testing.normalise_text(text)

Newline-normalise `text` so a Mac recording asserts on a Windows runner.

This is the whole of the Windows decision (option A) as it applies to tier 1.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> normalise_text('one\r\ntwo\rthree\n')
'one\ntwo\nthree\n'
>>> normalise_text(None) is None
True
```

### cw.testing.normalise_usage(text)

The `usage:` block of `text`, whitespace-collapsed and width-independent.

`argparse` wraps the usage block to the terminal width, so the same parser prints it
over two lines at `COLUMNS=100` and five at `COLUMNS=50`. Collapsing every run of
whitespace to one space makes the two equal while keeping what actually matters: which
options exist, in which order, with which metavars.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> normalise_usage('usage: prog [-h] [-v]\n\npositional arguments:\n  x')
'usage: prog [-h] [-v]'
>>> normalise_usage('usage: prog\n       [--a]\n       [--b] x')
'usage: prog [--a] [--b] x'
```

Text with no usage block at all – a command that just printed its result – normalises
to the empty string rather than raising, because “this case shows no usage line” is a
fact worth asserting too:

```pycon
>>> normalise_usage('hello world\n')
''
```

### cw.testing.parity(goldens_dir=None, , out=None, verbose=False)

Replay the committed argh-recorded goldens through cw. Exit code, not an exception.

This is the definition of v1: it prints `N shapes / M cases: identical` and returns
`0`. What it asserts, per case, with **every seam on its default**
(`convention=cw.ARGH`, `decode=cw.argh_decode`, `egress=cw.argh_egress`): exit
code, stdout, stderr, and the normalised `usage:` line, byte-identical to what argh
0.31.3 produced. The `--help` bodies are recorded and not asserted (tier 3).

It is deliberately **self-contained**. The goldens were recorded from real argh against
the seven hard-case *shapes* in `cw.tests.fixtures`, not against the seven fleet
repos – so this needs stdlib plus cw, installs no fleet package, pulls no argh, and
runs on Windows. The seven real repos are gated separately, by [`replay()`](#cw.testing.replay) in each
repo’s own CI, which is what a migration test is for.

* **Parameters:**
  * **goldens_dir** – Where the goldens are. `None` is the copy shipped inside `cw`.
  * **out** – Where the report goes. `None` is [`sys.stdout`](https://docs.python.org/3/library/sys.html#sys.stdout), resolved now.
  * **verbose** – Also print a line per shape that passed.
* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)
* **Returns:**
  `0` when every case is identical, `1` otherwise.

### cw.testing.pinned_env(env=None)

Context manager applying [`RECORDING_ENV`](#cw.testing.RECORDING_ENV) to the **current** process.

[`characterize()`](#cw.testing.characterize) hands the pins to a subprocess, where they belong. [`parity()`](#cw.testing.parity)
runs in-process and needs the same pins applied here instead – `COLUMNS` above all,
since that is what `argparse` wraps to.

* **Parameters:**
  **env** – Extra pins, applied over [`RECORDING_ENV`](#cw.testing.RECORDING_ENV).
* **Yields:**
  The mapping that was applied, which is what `as` gives you.

```pycon
>>> with pinned_env():
...     os.environ['COLUMNS']
'100'
>>> with pinned_env({'COLUMNS': '80'}) as pins:
...     (os.environ['COLUMNS'], pins['COLUMNS'])
('80', '80')
```

The name is lowercase because it reads as a statement rather than as a type, and it is
a function rather than a class because there is no object here worth having – the
house rule is functional over OOP, and `contextlib` is where the state machine goes.
Restoration is in a `finally`, so an exception inside the block does not leak the
pins into the rest of the process:

```pycon
>>> before = os.environ.get('COLUMNS')
>>> try:
...     with pinned_env():
...         raise RuntimeError('boom')
... except RuntimeError:
...     pass
>>> os.environ.get('COLUMNS') == before
True
```

### cw.testing.read_cases(path)

The `argv` vectors in a cases file, one per line.

Each line is either a JSON list – `["a", "b c"]` – or a POSIX `shlex` line.
Blank lines and `#` comments are skipped, and a line of `[]` (or nothing but
whitespace before a comment) is *not* a way to spell the empty argv: use `[]`
explicitly.

Both spellings exist for one reason: `shlex` is POSIX-only, so a Windows user writing
a corpus must have a form that never reaches it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### cw.testing.replay(golden, , prog=None, env=None, cwd=None, expect_diff=(), timeout=30, strict_help=False)

Re-run a golden’s cases and report, per case, whether the behaviour survived.

* **Parameters:**
  * **golden** – A golden dict, or the path of one.
  * **prog** – The command to run now. `None` reuses the golden’s own `prog`, which is
    what you want after an in-place migration and not what you want when the entry
    point moved.
  * **env** – As [`characterize()`](#cw.testing.characterize).
  * **cwd** – As [`characterize()`](#cw.testing.characterize).
  * **timeout** – As [`characterize()`](#cw.testing.characterize).
  * **expect_diff** – `argv` vectors whose behaviour you **intend** to have changed. They
    are reported as `expected-diff`, never as a failure – and an `expect_diff`
    entry that turns out identical is reported as `unexpected-match`, because a
    migration note claiming a break that did not happen is also wrong.
  * **strict_help** – Also assert each tier-3 case’s `--help` **body**, through
    `normalise_help()`. Off by default, because a wider `--help` is usually
    not what a migration promised; on, because a *formatter* change is not visible
    in any of the fields tier 3 asserts. When it is off, a body that moved is still
    reported – as the non-fatal status `help-differs` – so that a migration is
    never told “identical” about output that visibly changed.
* **Returns:**
  `argv`, `status` and `diff`.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

Statuses are `identical`, `differs`, `help-differs`, `expected-diff` and
`unexpected-match`. [`assert_replay()`](#cw.testing.assert_replay) is the version that raises, and it raises
on `differs` and `unexpected-match` only.

### cw.testing.scrub_addresses(text)

Replace object-repr memory addresses with a placeholder.

The one **content** normalisation in this module, and it exists because a golden that
records `<list_iterator object at 0x1017642e0>` asserts the heap layout of the machine
that recorded it. It is applied at record time as well as at replay time, so the
committed golden shows what is actually being asserted rather than hiding it in the
comparator.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> scrub_addresses('<map object at 0x104f2b910>')
'<map object at 0xADDR>'
```

### cw.testing.scrub_exe_suffix(text, program)

Strip Windows’ `.exe` off the program name a CLI prints about itself.

`argparse` derives `prog` from `os.path.basename(sys.argv[0])`, and on Windows a
console script is installed as `opsward.exe`. So the *same* CLI, at the same commit,
reports `usage: opsward ...` on a Mac and `usage: opsward.EXE ...` on a Windows
runner – and every case that prints a usage line or an error prefix differs. That is a
fact about packaging, not about the command line, and this module promises that “a
golden recorded on a Mac asserts cleanly on a Windows runner”.

Only the *program’s own* stem is rewritten, so a CLI that talks about some other
`.exe` is left alone. The match is case-insensitive because the shim’s extension is
reported as `.EXE` on some Windows configurations and `.exe` on others – which
would otherwise make two Windows runners disagree with each other.

`program` is the **whole command**, not just its first word, because the console
script is not always the first word: a caller may pass `['python', 'toy.exe']` as
readily as `['opsward.exe']`, and `argparse` names whichever of them landed in
`sys.argv[0]`. Every part is considered; a part that is not the program yields a stem
that appears nowhere in the text, so considering it costs nothing.

Both path separators are handled, and the replacement is a function rather than a
template string, because a Windows path reaches this on a POSIX host – through a
golden’s recorded `prog` – where `os.path.basename` does not split on a backslash
and `re.sub` would read the remaining `\p` as a bad escape.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> scrub_exe_suffix('usage: opsward.EXE [-h]', r'C:\Scripts\opsward.exe')
'usage: opsward [-h]'
>>> scrub_exe_suffix('usage: toy.EXE [-h]', ['/usr/bin/python', '/tmp/toy.exe'])
'usage: toy [-h]'
>>> scrub_exe_suffix('usage: opsward [-h]', '/usr/local/bin/opsward')
'usage: opsward [-h]'
>>> scrub_exe_suffix('run setup.exe first', '/usr/local/bin/opsward')
'run setup.exe first'
```
