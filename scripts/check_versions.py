#!/usr/bin/env python3
"""Refuse an adaptation that changed since the previous release without a version bump.

Compares every folder under adaptations/ in the working tree with the same folder at the previous
release tag (the highest `YYYY.MM.DD.N` tag, or --base):

  * new folder: its Version must parse (semver);
  * changed folder (any file differs, outside its `test/` folder): its Version must be greater than the released one;
  * unchanged folder: its Version must equal the released one;
  * the Id of a released folder must not change (a new Id is a new adaptation: add a folder);
  * no two folders share an Id, and no profile.json holds `Files` or `Signature` (the build writes
    them).

Prints what changed. With --github-output, appends `changed=true|false` (whether any adaptation was
added, changed or removed) and `previous-tag=<tag>` to that file, for the release workflow.

    python -I scripts/check_versions.py [--base <tag>] [--github-output "$GITHUB_OUTPUT"]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kitpath  # noqa: E402

kitpath.use_or_exit()

from qaros_adaptation import qarapp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RELEASE_TAG = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\.(\d+)$")


def git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed


def release_tags(root: Path) -> list[str]:
    """Release tags, oldest first."""
    tags = [tag for tag in git(root, "tag", "--list").stdout.split() if RELEASE_TAG.match(tag)]
    return sorted(tags, key=lambda tag: tuple(int(part) for part in RELEASE_TAG.match(tag).groups()))


def released_profiles(root: Path, tag: str) -> dict[str, dict]:
    """Folder name -> profile.json at `tag`."""
    listing = git(root, "ls-tree", "--name-only", f"{tag}:adaptations", check=False)
    if listing.returncode != 0:
        return {}
    profiles = {}
    for name in listing.stdout.split():
        shown = git(root, "show", f"{tag}:adaptations/{name}/profile.json", check=False)
        if shown.returncode == 0:
            profiles[name] = json.loads(shown.stdout)
    return profiles


def folder_changed(root: Path, tag: str, name: str) -> bool:
    """Any committed, staged, unstaged or untracked difference against `tag`, outside the folder's
    `test/` (authoring files, never packaged)."""
    path = f"adaptations/{name}"
    paths = ["--", path, f":(exclude){path}/test"]
    if git(root, "diff", "--quiet", tag, *paths, check=False).returncode != 0:
        return True
    return bool(git(root, "ls-files", "--others", "--exclude-standard", *paths).stdout.strip())


def check(root: Path, base: str | None) -> tuple[list[str], list[str], bool]:
    """(errors, report lines, whether anything changed)."""
    errors: list[str] = []
    report: list[str] = []
    adaptations = root / "adaptations"
    current = {
        path.name: path for path in sorted(adaptations.iterdir()) if (path / qarapp.PROFILE_NAME).is_file()
    }
    released = released_profiles(root, base) if base else {}
    ids: dict[str, str] = {}
    changed_any = False
    for name, folder in current.items():
        try:
            profile = qarapp.read_profile(folder)
            qarapp.validate_id(profile.get("Id", ""))
            version = qarapp.Version.parse(profile.get("Version", ""))
        except qarapp.PackageError as error:
            errors.append(f"{name}: {error}")
            continue
        for key in ("Files", "Signature"):
            if key in profile:
                errors.append(f"{name}: profile.json holds '{key}'; remove it (the build writes it)")
        if profile["Id"] in ids:
            errors.append(f"{name}: Id {profile['Id']} is also used by {ids[profile['Id']]}")
        ids[profile["Id"]] = name
        old = released.get(name)
        if old is None:
            changed_any = True
            report.append(f"{name}: new, {version}")
            continue
        if old.get("Id") != profile["Id"]:
            errors.append(f"{name}: Id changed from {old.get('Id')} to {profile['Id']}; add a new folder instead")
        try:
            old_version = qarapp.Version.parse(old.get("Version", ""))
        except qarapp.PackageError:
            old_version = None
        if folder_changed(root, base, name):
            changed_any = True
            if old_version is not None and not version > old_version:
                errors.append(f"{name}: changed since {base} but Version {version} is not greater than {old_version}; bump it")
            else:
                report.append(f"{name}: changed, {old_version} -> {version}")
        elif old_version is not None and version != old_version:
            errors.append(f"{name}: unchanged since {base} but Version {old_version} became {version}")
        else:
            report.append(f"{name}: unchanged, {version}")
    for name in sorted(set(released) - set(current)):
        changed_any = True
        report.append(f"{name}: removed")
    return errors, report, changed_any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="release tag to compare with (default: the highest YYYY.MM.DD.N tag)")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--kit", type=Path, help="QAROS adaptation kit folder (see scripts/kitpath.py)")
    parser.add_argument("--github-output", type=Path, help="append changed=/previous-tag= to this file")
    args = parser.parse_args()
    try:
        base = args.base
        if base is None:
            tags = release_tags(args.root)
            base = tags[-1] if tags else None
        elif git(args.root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).returncode != 0:
            raise RuntimeError(f"{base} is not a tag or commit of this repository")
        errors, report, changed = check(args.root, base)
    except (RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"compared with {base}" if base else "no previous release: every adaptation is new")
    for line in report:
        print(f"  {line}")
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"changed={'true' if changed else 'false'}\n")
            output.write(f"previous-tag={base or ''}\n")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("versions ok" + ("" if changed else "; no adaptation changed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
