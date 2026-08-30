"""``import cw`` must stay stdlib-only.

This is a regression guard, not a benchmark. cw is offered to repos that ship their CLI as
an optional extra precisely to keep the base install thin, so a module-scope third-party
import anywhere under ``cw/`` is a defect even when the dependency happens to be installed.
The check runs in a subprocess because the test session itself has already imported plenty.
"""

import subprocess
import sys
import textwrap

#: Distributions cw must not pull at import time. ``i2`` is an optional extra used by
#: ``resource_inputs`` alone; ``argh`` is the LGPL package cw exists to replace.
FORBIDDEN_AT_IMPORT = ("i2", "argh", "dol", "meshed", "argcomplete")


def _modules_after_importing_cw():
    """Top-level module names present in a fresh interpreter after ``import cw``."""
    source = textwrap.dedent(
        """
        import sys
        import cw
        print('\\n'.join(sorted({name.split('.')[0] for name in sys.modules})))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, check=True
    )
    return set(completed.stdout.split())


def test_import_cw_pulls_no_third_party():
    pulled = _modules_after_importing_cw() & set(FORBIDDEN_AT_IMPORT)
    assert not pulled, (
        f"`import cw` pulled {sorted(pulled)}. Move that import into the body of the one "
        f"function that needs it -- see cw.resolution._i2_wrapper for the pattern."
    )


def test_no_module_scope_third_party_import_in_cw():
    """The mechanical version of the check above, so a new module cannot sneak one in."""
    import pathlib

    import cw

    package_dir = pathlib.Path(cw.__file__).parent
    offenders = {}
    for module_path in sorted(package_dir.glob("*.py")):
        for lineno, line in enumerate(module_path.read_text().splitlines(), start=1):
            if not line.startswith(("import ", "from ")):
                continue  # indented -> inside a function or class; that is the allowed form
            root = line.split()[1].split(".")[0]
            if root in FORBIDDEN_AT_IMPORT:
                offenders[f"{module_path.name}:{lineno}"] = line.strip()
    assert not offenders, f"module-scope third-party imports: {offenders}"
