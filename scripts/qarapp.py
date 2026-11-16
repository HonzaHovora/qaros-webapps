#!/usr/bin/env python3
"""The `.qarapp` command line of the QAROS adaptation kit (`qaros_adaptation.qarapp`): keygen,
key-id, digest, attach, sign, export, verify. The kit is found as scripts/kitpath.py says.

    python -I scripts/qarapp.py [--kit <qaros>/adaptation-kit] <command> ...
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kitpath  # noqa: E402


def main() -> int:
    kit, argv = kitpath.split_kit_argument(sys.argv[1:])
    try:
        kitpath.use(kit)
    except kitpath.KitNotFound as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    from qaros_adaptation import qarapp

    sys.argv = [sys.argv[0], *argv]
    return qarapp.main()


if __name__ == "__main__":
    sys.exit(main())
