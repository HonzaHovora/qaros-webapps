#!/usr/bin/env python3
"""The checks CI runs, in one place; the workflows only check out and call this.

    ci.py kit-ref [--github-output FILE]
        The Quaternar/qaros ref holding the adaptation kit to check against: the tag
        v<minQarosVersion> (release.json) when it exists, else the default branch (an empty ref).
        Prints which, and with --github-output appends `ref=<ref>`.

    ci.py check [--kit DIR] [--no-versions]
        1. the tooling tests (scripts/tests),
        2. `qaros-adaptation check` and `test` on every adaptation, with the kit's own CLI,
        3. the version bumps against the previous release (scripts/check_versions.py).

The kit is found as scripts/kitpath.py says (--kit, $QAROS_ADAPTATION_KIT, .qaros/adaptation-kit).
Standard library only; needs git, and Node.js 20 or newer for `test`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kitpath  # noqa: E402

ROOT = kitpath.ROOT
KIT_REPOSITORY = "https://github.com/Quaternar/qaros"


def min_qaros_version(root: Path = ROOT) -> str:
    return json.loads((root / "release.json").read_text(encoding="utf-8"))["minQarosVersion"]


def kit_ref(repository: str = KIT_REPOSITORY, version: str | None = None) -> tuple[str, str]:
    """(ref, explanation): `v<version>` when that tag exists in `repository`, else "" (default branch)."""
    tag = f"v{version or min_qaros_version()}"
    listed = subprocess.run(
        ["git", "ls-remote", "--tags", repository, f"refs/tags/{tag}"], capture_output=True, text=True, check=False
    )
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-remote {repository} failed: {listed.stderr.strip()}")
    if listed.stdout.strip():
        return tag, f"adaptation kit: {repository} at tag {tag}"
    return "", f"adaptation kit: {repository} has no tag {tag} yet; using its default branch"


def run(step: str, command: list[str], kit: Path) -> bool:
    print(f"::group::{step}" if _github() else f"== {step}", flush=True)
    environment = dict(os.environ, **{kitpath.ENVIRONMENT: str(kit)})
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if _github():
        print("::endgroup::", flush=True)
    if completed.returncode != 0:
        print(f"FAILED: {step} (exit {completed.returncode})", file=sys.stderr, flush=True)
    return completed.returncode == 0


def _github() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def adaptation_folders(root: Path = ROOT) -> list[Path]:
    return sorted(path.parent for path in (root / "adaptations").glob("*/profile.json"))


def check(kit: Path, versions: bool) -> int:
    python = [sys.executable, "-I"]
    tool = [*python, str(kit / "tools" / "qaros-adaptation.py"), "--kit", str(kit)]
    results = [run("tooling tests", [*python, "-m", "unittest", "discover", "-s", "scripts/tests"], kit)]
    for folder in adaptation_folders():
        relative = folder.relative_to(ROOT).as_posix()
        results.append(run(f"qaros-adaptation check {relative}", [*tool, "check", relative], kit))
        results.append(run(f"qaros-adaptation test {relative}", [*tool, "test", relative], kit))
    if versions:
        results.append(run("version bumps", [*python, "scripts/check_versions.py", "--kit", str(kit)], kit))
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    ref = commands.add_parser("kit-ref", help="the Quaternar/qaros ref to check out")
    ref.add_argument("--github-output", type=Path, help="append ref=<ref> to this file")
    ref.add_argument("--repository", default=KIT_REPOSITORY)
    checks = commands.add_parser("check", help="tooling tests, kit check and test per adaptation, version bumps")
    checks.add_argument("--kit", type=Path, help="QAROS adaptation kit folder (see scripts/kitpath.py)")
    checks.add_argument("--no-versions", action="store_true", help="skip the version bump check")
    args = parser.parse_args()
    try:
        if args.command == "kit-ref":
            value, explanation = kit_ref(args.repository)
            print(explanation)
            if args.github_output is not None:
                with args.github_output.open("a", encoding="utf-8") as output:
                    output.write(f"ref={value}\n")
            return 0
        kit = kitpath.locate(args.kit)
        print(f"adaptation kit: {kit}")
        return check(kit, not args.no_versions)
    except (RuntimeError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
