#!/usr/bin/env python3
"""Build one `.qarapp` package per adaptation folder, optionally signed, and verify each.

For every folder under adaptations/ (or the ones named with --only) this

  1. copies the folder to <out>/staging/<name> (the repository is never written),
  2. writes the file manifest (`Files`) into the copy's profile.json,
  3. signs it when a key is given:
       --key-vault: digest -> `az keyvault key sign --algorithm ES256` -> attach (release builds),
       --private-key: a local PEM key (test runs only; never commit one),
  4. writes <out>/<id>-<version>.qarapp,
  5. reads the package back and verifies it (files, manifest, signature against --public-key),
     and with --tool also with qar-adaptation-tool (`verify <package> <public.pem>`).

Standard library only:

    python -I scripts/build_packages.py --out out
    python -I scripts/build_packages.py --out out --public-key release.pub.pem \\
        --key-vault <vault> --key-name qaros-release
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qarapp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def adaptation_folders(adaptations: Path, only: list[str]) -> list[Path]:
    folders = sorted(path for path in adaptations.iterdir() if (path / qarapp.PROFILE_NAME).is_file())
    if only:
        missing = sorted(set(only) - {folder.name for folder in folders})
        if missing:
            raise qarapp.PackageError(f"no adaptation folder named {', '.join(missing)}")
        folders = [folder for folder in folders if folder.name in only]
    if not folders:
        raise qarapp.PackageError(f"no adaptation folder in {adaptations}")
    return folders


def check_source(folder: Path) -> dict:
    """The repository holds unsigned adaptations without a manifest: both are written at build time."""
    profile = qarapp.read_profile(folder)
    for key in ("Files", "Signature"):
        if key in profile:
            raise qarapp.PackageError(f"{folder.name}/profile.json holds '{key}'; remove it (the build writes it)")
    qarapp.check_profile(profile, {entry["Path"] for entry in qarapp.file_manifest(folder)})
    return profile


def verify_with_tool(tool: Path, package: Path, public_key: Path, signer: str) -> str:
    completed = subprocess.run(
        [str(tool), "verify", str(package), str(public_key), signer], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise qarapp.PackageError(f"{tool.name} verify {package.name} failed: {(completed.stderr or completed.stdout).strip()}")
    return completed.stdout.strip()


def build(args: argparse.Namespace) -> list[Path]:
    public_der = None
    if args.public_key is not None:
        public_der = qarapp.public_key_der_from_pem(args.public_key.read_text(encoding="ascii"))
    signer = None
    if args.key_vault:
        if public_der is None:
            raise qarapp.PackageError("--key-vault needs --public-key (the key's public half, PEM)")
        signer = qarapp.KeyVaultKey(args.key_vault, args.key_name).sign
    elif args.private_key is not None:
        key = qarapp.SigningKey.load(args.private_key)
        if public_der is None:
            public_der = key.public_der
        elif public_der != key.public_der:
            raise qarapp.PackageError("--private-key does not belong to --public-key")
        signer = key.sign
    trusted = [(args.signer, public_der)] if public_der is not None else None

    tool_key = args.public_key
    scratch = None
    if args.tool is not None and tool_key is None:
        # qar-adaptation-tool verify always takes a key; an unsigned package passes with any.
        scratch = Path(tempfile.mkdtemp(prefix="qarapp-verify-"))
        tool_key = scratch / "unused.pub.pem"
        tool_key.write_text(qarapp.public_key_pem(qarapp.keygen().public_der), encoding="ascii")

    out = args.out.resolve()
    staging = out / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    packages = []
    try:
        for folder in adaptation_folders(args.adaptations, args.only):
            profile = check_source(folder)
            copy = staging / folder.name
            shutil.copytree(folder, copy)
            if signer is not None:
                qarapp.sign_folder(copy, args.signer, signer, public_der)
            else:
                qarapp.write_manifest(copy)
            package = out / qarapp.package_file_name(profile["Id"], profile["Version"])
            qarapp.export_package(copy, package)
            result = qarapp.read_package(package, trusted).verification
            if signer is not None and not result.signed:
                raise qarapp.PackageError(f"{package.name} is not signed")
            state = f"signed by {result.signer}" if result.signed else "unsigned"
            line = f"{package.name}: ok, {state}"
            if args.tool is not None:
                line += f"; {args.tool.name}: {verify_with_tool(args.tool, package, tool_key, args.signer)}"
            print(line)
            packages.append(package)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        if not args.keep_staging and staging.exists():
            shutil.rmtree(staging)
    return packages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="output folder for the packages")
    parser.add_argument("--adaptations", type=Path, default=ROOT / "adaptations", help="folder holding the adaptation folders")
    parser.add_argument("--only", nargs="*", default=[], metavar="NAME", help="build only these adaptation folders")
    parser.add_argument("--public-key", type=Path, help="public half of the signing key (PEM); packages are verified against it")
    parser.add_argument("--key-vault", help="Azure Key Vault holding the signing key")
    parser.add_argument("--key-name", default="qaros-release", help="key name in --key-vault (default: qaros-release)")
    parser.add_argument("--private-key", type=Path, help="local PEM private key instead of Key Vault (test runs only)")
    parser.add_argument("--signer", default=qarapp.DEFAULT_SIGNER, help="signer name (default: Quaternar)")
    parser.add_argument("--tool", type=Path, help="qar-adaptation-tool executable: also verify every package with it")
    parser.add_argument("--keep-staging", action="store_true", help="keep <out>/staging (the signed folders)")
    args = parser.parse_args()
    if args.key_vault and args.private_key:
        parser.error("pass --key-vault or --private-key, not both")
    try:
        packages = build(args)
    except (qarapp.PackageError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{len(packages)} packages in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
