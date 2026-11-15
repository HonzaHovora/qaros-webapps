"""Locate the QAROS adaptation kit and make its Python package (`qaros_adaptation`) importable.

The packaging code, the `.qarapp` format and the libraries the adaptations name live in the kit
(public repository Quaternar/qaros, folder `adaptation-kit`). The kit is found, first match wins:

  1. `--kit <dir>` on the command line of the script being run;
  2. the environment variable QAROS_ADAPTATION_KIT;
  3. `<repository>/.qaros/adaptation-kit`, where CI checks out Quaternar/qaros.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT = "QAROS_ADAPTATION_KIT"
DEFAULT_KIT = ROOT / ".qaros" / "adaptation-kit"


class KitNotFound(RuntimeError):
    """No adaptation kit at the given or default place."""


def split_kit_argument(argv: list[str]) -> tuple[str | None, list[str]]:
    """(the value of `--kit <dir>` or `--kit=<dir>` in `argv` or None, `argv` without it)."""
    for position, argument in enumerate(argv):
        if argument == "--kit" and position + 1 < len(argv):
            return argv[position + 1], argv[:position] + argv[position + 2 :]
        if argument.startswith("--kit="):
            return argument.split("=", 1)[1], argv[:position] + argv[position + 1 :]
    return None, list(argv)


def locate(kit: str | Path | None = None) -> Path:
    """The kit folder (holding `lib/` and `tools/qaros_adaptation/`)."""
    candidate = kit or os.environ.get(ENVIRONMENT) or DEFAULT_KIT
    folder = Path(candidate).resolve()
    if not (folder / "tools" / "qaros_adaptation" / "__init__.py").is_file():
        raise KitNotFound(
            f"no QAROS adaptation kit at {folder}: pass --kit <qaros>/adaptation-kit or set {ENVIRONMENT} "
            f"(a checkout of https://github.com/Quaternar/qaros)"
        )
    return folder


def use(kit: str | Path | None = None) -> Path:
    """Locates the kit (default: `--kit` in sys.argv, then the environment, then the CI checkout)
    and puts its tools folder on sys.path, so `import qaros_adaptation` loads the kit's package."""
    folder = locate(kit if kit is not None else split_kit_argument(sys.argv[1:])[0])
    tools = str(folder / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    return folder


def use_or_exit() -> Path:
    """`use()` for a script's import time: a missing kit ends the run with the error, not a traceback."""
    try:
        return use()
    except KitNotFound as missing:
        print(f"error: {missing}", file=sys.stderr)
        raise SystemExit(1) from None
