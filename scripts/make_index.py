#!/usr/bin/env python3
"""Write, sign and verify `webapps-index.json`, the list of adaptations a release publishes.

The index (schemas/webapps-index.schema.json) names, per adaptation, its id, version, release
asset, SHA-256, package formatVersion and the oldest QAROS that installs it (minQarosVersion, from
release.json). QAROS fetches it from the fixed address

    https://github.com/Quaternar/qaros-webapps/releases/latest/download/webapps-index.json

Its `signature` block is an ECDSA P-256 / SHA-256 signature by the QAROS release key over

    SHA-256("QAROS-WEBAPPS-INDEX-SIGNATURE-V1" NUL canonical(index without "signature"))

(canonical: sorted keys, no whitespace, UTF-8), the same construction as an adaptation's signature.

    make_index.py build --packages out --release 2026.11.14.1 --out out/webapps-index.json \\
        [--public-key release.pub.pem (--key-vault <vault> [--key-name qaros-release] | --private-key test.pem)]
    make_index.py digest out/webapps-index.json                 base64 digest for `az keyvault key sign`
    make_index.py attach out/webapps-index.json --public-key release.pub.pem --signature-file index.sig
    make_index.py verify out/webapps-index.json [--public-key release.pub.pem] [--packages out] [--require-signature]

`attach` takes a detached signature (base64 or base64url, raw r||s as Key Vault answers it, or DER)
made elsewhere over the `digest` output. Standard library plus the QAROS adaptation kit's
`qaros_adaptation.qarapp`; `--kit <dir>` anywhere on the command line picks the kit (see
scripts/kitpath.py).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kitpath  # noqa: E402

kitpath.use_or_exit()

from qaros_adaptation import qarapp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX_FORMAT_VERSION = 1
INDEX_NAME = "webapps-index.json"
INDEX_DOMAIN_TAG = b"QAROS-WEBAPPS-INDEX-SIGNATURE-V1"
RELEASE_TAG = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")


class IndexFailure(RuntimeError):
    """The index is invalid or does not verify."""


def index_digest(index: dict) -> bytes:
    body = {key: value for key, value in index.items() if key != "signature"}
    return hashlib.sha256(INDEX_DOMAIN_TAG + b"\0" + qarapp.canonical_json(body)).digest()


def write_index(path: Path, index: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(qarapp.pretty_json(index) + b"\n")


def read_index(path: Path) -> dict:
    return qarapp.parse_json_object(path.read_bytes(), str(path))


def signature_block(signer: str, public_der: bytes, value_der: bytes) -> dict:
    return {
        "algorithm": qarapp.SIGNATURE_ALGORITHM,
        "keyId": qarapp.key_id(public_der),
        "publicKey": base64.b64encode(public_der).decode("ascii"),
        "signer": signer,
        "value": base64.b64encode(value_der).decode("ascii"),
    }


def attach(index: dict, signer: str, public_der: bytes, value_der: bytes) -> dict:
    index = {key: value for key, value in index.items() if key != "signature"}
    if not qarapp.verify_signature_value(public_der, index_digest(index), value_der):
        raise IndexFailure("the signature does not match the index digest (did the index change?)")
    index["signature"] = signature_block(signer, public_der, value_der)
    return index


def load_config(path: Path) -> dict:
    """release.json. A per-adaptation minQarosVersion may only raise the global one: every package
    needs at least the QAROS whose adaptation kit provides the libraries it names."""
    config = json.loads(path.read_text(encoding="utf-8"))
    minimum = qarapp.Version.parse(config["minQarosVersion"])
    for name, override in config.get("adaptations", {}).items():
        if "minQarosVersion" in override and qarapp.Version.parse(override["minQarosVersion"]) < minimum:
            raise IndexFailure(
                f"release.json: {name} minQarosVersion {override['minQarosVersion']} is below {config['minQarosVersion']}"
            )
    return config


def build_index(packages_dir: Path, release: str, config: dict, trusted) -> dict:
    if not RELEASE_TAG.match(release):
        raise IndexFailure(f"release '{release}' is not a YYYY.MM.DD.N tag")
    repository = config["repository"]
    overrides = config.get("adaptations", {})
    entries = []
    for package in sorted(packages_dir.glob(f"*{qarapp.EXTENSION}")):
        contents = qarapp.read_package(package, trusted)
        profile = contents.profile
        expected = qarapp.package_file_name(profile["Id"], profile["Version"])
        if package.name != expected:
            raise IndexFailure(f"{package.name} should be named {expected}")
        minimum = overrides.get(profile.get("Name", ""), {}).get("minQarosVersion", config["minQarosVersion"])
        qarapp.Version.parse(minimum)
        data = package.read_bytes()
        entries.append(
            {
                "id": profile["Id"],
                "name": profile.get("Name", ""),
                "displayName": profile.get("DisplayName", ""),
                "version": profile["Version"],
                "asset": package.name,
                "url": f"https://github.com/{repository}/releases/download/{release}/{package.name}",
                "release": release,
                "sha256": qarapp.sha256_hex(data),
                "size": len(data),
                "formatVersion": contents.format_version,
                "minQarosVersion": minimum,
                "signed": contents.verification.signed,
            }
        )
    if not entries:
        raise IndexFailure(f"no {qarapp.EXTENSION} package in {packages_dir}")
    ids = [entry["id"] for entry in entries]
    duplicates = sorted({adaptation_id for adaptation_id in ids if ids.count(adaptation_id) > 1})
    if duplicates:
        raise IndexFailure(f"more than one package for {', '.join(duplicates)}")
    entries.sort(key=lambda entry: entry["id"])
    return {
        "indexFormatVersion": INDEX_FORMAT_VERSION,
        "repository": repository,
        "release": release,
        "adaptations": entries,
    }


def verify_index(index: dict, trusted, packages_dir: Path | None, require_signature: bool) -> str:
    if index.get("indexFormatVersion") != INDEX_FORMAT_VERSION:
        raise IndexFailure(f"indexFormatVersion {index.get('indexFormatVersion')} is not {INDEX_FORMAT_VERSION}")
    if not RELEASE_TAG.match(str(index.get("release", ""))):
        raise IndexFailure("the index has no YYYY.MM.DD.N release")
    entries = index.get("adaptations")
    if not isinstance(entries, list) or not entries:
        raise IndexFailure("the index lists no adaptation")
    for entry in entries:
        qarapp.validate_id(entry.get("id", ""))
        qarapp.Version.parse(entry.get("version", ""))
        qarapp.Version.parse(entry.get("minQarosVersion", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise IndexFailure(f"{entry.get('id')}: sha256 is not 64 lower-case hex digits")
        if packages_dir is not None:
            data = (packages_dir / entry["asset"]).read_bytes()
            if qarapp.sha256_hex(data) != entry["sha256"] or len(data) != entry.get("size"):
                raise IndexFailure(f"{entry['asset']}: SHA-256 or size does not match the index")
            contents = qarapp.read_package(packages_dir / entry["asset"], trusted)
            if (contents.profile["Id"], contents.profile["Version"]) != (entry["id"], entry["version"]):
                raise IndexFailure(f"{entry['asset']}: holds {contents.profile['Id']} {contents.profile['Version']}")
            if require_signature and not contents.verification.signed:
                raise IndexFailure(f"{entry['asset']} is not signed")
    block = index.get("signature")
    if block is None:
        if require_signature:
            raise IndexFailure("the index is not signed")
        return f"ok {len(entries)} adaptations, release {index['release']}, unsigned"
    if block.get("algorithm") != qarapp.SIGNATURE_ALGORITHM:
        raise IndexFailure(f"unsupported signature algorithm '{block.get('algorithm')}'")
    public_der = base64.b64decode(block.get("publicKey", ""), validate=True)
    if qarapp.key_id(public_der) != block.get("keyId"):
        raise IndexFailure("the signature's key id does not match its public key")
    if trusted is not None:
        names = [name for name, der in trusted if der == public_der]
        if not names or names[0] != block.get("signer"):
            raise IndexFailure(f"signed by '{block.get('signer')}' with key {block.get('keyId')}, which is not trusted")
    value = base64.b64decode(block.get("value", ""), validate=True)
    if not qarapp.verify_signature_value(public_der, index_digest(index), value):
        raise IndexFailure("the index signature does not verify: the index was changed")
    state = f"signed by {block.get('signer')}" if trusted is not None else f"signature valid, claims signer '{block.get('signer')}' (no trusted key given)"
    return f"ok {len(entries)} adaptations, release {index['release']}, {state}"


def _public_der(path: Path | None) -> bytes | None:
    return qarapp.public_key_der_from_pem(path.read_text(encoding="ascii")) if path is not None else None


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="write the index for the packages of a release")
    build.add_argument("--packages", type=Path, required=True, help="folder holding the release's .qarapp packages")
    build.add_argument("--release", required=True, help="release tag, YYYY.MM.DD.N")
    build.add_argument("--out", type=Path, required=True, help=f"index file to write ({INDEX_NAME})")
    build.add_argument("--config", type=Path, default=ROOT / "release.json", help="repository and minQarosVersion (release.json)")
    build.add_argument("--public-key", type=Path, help="public half of the signing key (PEM): packages and index are verified against it")
    build.add_argument("--key-vault", help="Azure Key Vault holding the signing key: sign the index")
    build.add_argument("--key-name", default="qaros-release", help="key name in --key-vault (default: qaros-release)")
    build.add_argument("--private-key", type=Path, help="local PEM private key instead of Key Vault (test runs only)")
    build.add_argument("--signer", default=qarapp.DEFAULT_SIGNER)

    digest = commands.add_parser("digest", help="print the base64 digest a key vault signs")
    digest.add_argument("index", type=Path)

    attach_ = commands.add_parser("attach", help="attach a detached signature made over the digest")
    attach_.add_argument("index", type=Path)
    attach_.add_argument("--public-key", type=Path, required=True)
    attach_.add_argument("--signature-file", type=Path, required=True, help="base64 signature (raw r||s or DER)")
    attach_.add_argument("--signer", default=qarapp.DEFAULT_SIGNER)

    verify = commands.add_parser("verify", help="check the index (and the packages it names)")
    verify.add_argument("index", type=Path)
    verify.add_argument("--public-key", type=Path, help="trusted public key (PEM)")
    verify.add_argument("--signer", default=qarapp.DEFAULT_SIGNER)
    verify.add_argument("--packages", type=Path, help="also check every named package in this folder")
    verify.add_argument("--require-signature", action="store_true", help="refuse an unsigned index or package")
    args = parser.parse_args(argv)

    if args.command == "build":
        if args.key_vault and args.private_key:
            parser.error("pass --key-vault or --private-key, not both")
        public_der = _public_der(args.public_key)
        sign = None
        if args.key_vault:
            if public_der is None:
                parser.error("--key-vault needs --public-key")
            sign = qarapp.KeyVaultKey(args.key_vault, args.key_name).sign
        elif args.private_key is not None:
            key = qarapp.SigningKey.load(args.private_key)
            if public_der is not None and public_der != key.public_der:
                raise IndexFailure("--private-key does not belong to --public-key")
            public_der = key.public_der
            sign = key.sign
        trusted = [(args.signer, public_der)] if public_der is not None else None
        index = build_index(args.packages, args.release, load_config(args.config), trusted)
        if sign is not None:
            index = attach(index, args.signer, public_der, sign(index_digest(index)))
        write_index(args.out, index)
        print(verify_index(index, trusted, args.packages, sign is not None))
    elif args.command == "digest":
        print(base64.b64encode(index_digest(read_index(args.index))).decode("ascii"))
    elif args.command == "attach":
        public_der = _public_der(args.public_key)
        value = qarapp.raw_signature_to_der(qarapp.decode_base64(args.signature_file.read_text(encoding="ascii")))
        index = attach(read_index(args.index), args.signer, public_der, value)
        write_index(args.index, index)
        print(verify_index(index, [(args.signer, public_der)], None, True))
    elif args.command == "verify":
        public_der = _public_der(args.public_key)
        trusted = [(args.signer, public_der)] if public_der is not None else None
        print(verify_index(read_index(args.index), trusted, args.packages, args.require_signature))
    return 0


def main() -> int:
    try:
        return _main(kitpath.split_kit_argument(sys.argv[1:])[1])
    except (IndexFailure, qarapp.PackageError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
