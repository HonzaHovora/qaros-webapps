#!/usr/bin/env python3
"""Keep the adaptations' copies of the shared libraries in step with shared/.

Each adaptation is packaged as it is, so a script it shares with others is a copy of a library in
shared/ (listed in shared/copies.json). This writes every copy from its library, with
__PAGE_REGION_WIDTH__ / __PAGE_REGION_HEIGHT__ replaced by the adaptation's PageRegion. With
--check nothing is written and the run fails when a copy differs.

A changed copy changes its adaptation: bump that adaptation's Version (scripts/check_versions.py).

    python -I scripts/sync_shared.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def expected_copy(library: Path, profile: dict) -> bytes:
    region = profile.get("PageRegion", {})
    text = library.read_text(encoding="utf-8")
    text = text.replace("__PAGE_REGION_WIDTH__", str(region["Width"]))
    text = text.replace("__PAGE_REGION_HEIGHT__", str(region["Height"]))
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail when a copy differs instead of writing it")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args()
    adaptations = args.root / "adaptations"
    shared = args.root / "shared"
    copies = json.loads((shared / "copies.json").read_text(encoding="utf-8"))["copies"]
    stale = []
    for copy, library in sorted(copies.items()):
        target = adaptations / copy
        profile = json.loads((adaptations / copy.split("/")[0] / "profile.json").read_text(encoding="utf-8"))
        wanted = expected_copy(shared / library, profile)
        if target.is_file() and target.read_bytes() == wanted:
            continue
        stale.append(copy)
        if not args.check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wanted)
            print(f"updated adaptations/{copy} from shared/{library}")
    if args.check and stale:
        for copy in stale:
            print(f"error: adaptations/{copy} differs from shared/{copies[copy]}", file=sys.stderr)
        print("run: python -I scripts/sync_shared.py, then bump each changed adaptation's Version", file=sys.stderr)
        return 1
    print(f"{len(copies)} shared library copies {'checked' if args.check else 'in step'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
