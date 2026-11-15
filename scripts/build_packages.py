#!/usr/bin/env python3
"""Build one `.qarapp` package per adaptation folder, optionally signed, and verify each.

A thin wrapper over the QAROS adaptation kit's packaging (`qaros_adaptation.packaging`, the same
steps as `qaros-adaptation package`). For every folder under adaptations/ (or the ones named with
--only) the kit

  1. checks the folder (`qaros-adaptation check`: profile, every `Library` in the kit, script order),
  2. copies it to a staging folder (the repository is never written), leaving out `test/`,
  3. writes the file manifest (`Files`) into the copy's profile.json,
  4. signs it when a key is given:
       --key-vault: digest -> `az keyvault key sign --algorithm ES256` -> attach (release builds),
       --private-key: a local PEM key (test runs only; never commit one),
  5. writes <out>/<id>-<version>.qarapp and reads it back as QAROS imports it (files, manifest,
     signature against --public-key); with --tool also with qar-adaptation-tool
     (`verify <package> <public.pem>`).

`Library` references stay references: QAROS resolves them from its own kit at load time.

The kit is found with --kit, the environment variable QAROS_ADAPTATION_KIT, or at
.qaros/adaptation-kit (where CI checks out Quaternar/qaros); see scripts/kitpath.py.

    python -I scripts/build_packages.py --out out [--kit <qaros>/adaptation-kit]
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

import kitpath  # noqa: E402

ROOT = kitpath.ROOT

kitpath.use_or_exit()

from qaros_adaptation import kit as kitlib  # noqa: E402
from qaros_adaptation import packaging, qarapp  # noqa: E402


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


def verify_with_tool(tool: Path, package: Path, public_key: Path, signer: str) -> str:
    completed = subprocess.run(
        [str(tool), "verify", str(package), str(public_key), signer], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise qarapp.PackageError(f"{tool.name} verify {package.name} failed: {(completed.stderr or completed.stdout).strip()}")
    return completed.stdout.strip()


def unpack(package: Path, folder: Path) -> None:
    """The package's adaptation folder, as QAROS stores it (for --keep-staging)."""
    prefix = qarapp.CONTENT_FOLDER + "/"
    for name, data in qarapp.read_zip(package.read_bytes()):
        if name.startswith(prefix):
            target = folder / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def build(args: argparse.Namespace) -> list[Path]:
    signing = packaging.signing_options(
        private_key=args.private_key,
        key_vault=args.key_vault,
        key_name=args.key_name,
        public_key=args.public_key,
        signer=args.signer,
    )
    public_der = None
    if args.public_key is not None:
        public_der = qarapp.public_key_der_from_pem(args.public_key.read_text(encoding="ascii"))
    elif signing is not None:
        public_der = signing.public_der
    trusted = [(args.signer, public_der)] if public_der is not None else None
    kit = kitlib.load_kit(kitpath.locate(args.kit))

    tool_key = args.public_key
    scratch = None
    if args.tool is not None and tool_key is None:
        # qar-adaptation-tool verify always takes a key; an unsigned package passes with any.
        scratch = Path(tempfile.mkdtemp(prefix="qarapp-verify-"))
        tool_key = scratch / "unused.pub.pem"
        tool_key.write_text(qarapp.public_key_pem(qarapp.keygen().public_der), encoding="ascii")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    staging = out / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    packages = []
    try:
        for folder in adaptation_folders(args.adaptations, args.only):
            result = packaging.build_package(folder, out, signing=signing, trusted=trusted, kit=kit)
            package = result.path
            state = f"signed by {result.verification.signer}" if result.verification.signed else "unsigned"
            line = f"{package.name}: ok, {state}"
            if args.tool is not None:
                line += f"; {args.tool.name}: {verify_with_tool(args.tool, package, tool_key, args.signer)}"
            print(line)
            if args.keep_staging:
                unpack(package, staging / folder.name)
            packages.append(package)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
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
    parser.add_argument("--keep-staging", action="store_true", help="also write each package's folder to <out>/staging/<name>")
    parser.add_argument("--kit", type=Path, help=f"QAROS adaptation kit folder (default: ${kitpath.ENVIRONMENT}, else {kitpath.DEFAULT_KIT})")
    args = parser.parse_args()
    if args.key_vault and args.private_key:
        parser.error("pass --key-vault or --private-key, not both")
    try:
        packages = build(args)
    except (packaging.BuildError, qarapp.PackageError, kitlib.KitError, kitpath.KitNotFound, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{len(packages)} packages in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
