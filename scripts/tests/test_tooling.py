"""Tests of the package, version and index tooling. Run: python -I -m unittest discover -s scripts/tests"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import check_versions  # noqa: E402
import make_index  # noqa: E402
import qarapp  # noqa: E402

KEY = qarapp.SigningKey(0x1F2E3D4C5B6A79881F2E3D4C5B6A79881F2E3D4C5B6A79881F2E3D4C5B6A7988)
OTHER_KEY = qarapp.SigningKey(0x0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF)
TRUSTED = [("Quaternar", KEY.public_der)]


def raw_key_vault_signature(digest: bytes) -> str:
    """What `az keyvault key sign --algorithm ES256` answers: base64url raw r||s, no padding."""
    r, s = qarapp.signature_from_der(KEY.sign(digest))
    return base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode().rstrip("=")


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="qaros-webapps-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def adaptation(self, name: str = "foxglove") -> Path:
        """A copy of a repository adaptation, with a served panel added so panel paths are covered."""
        folder = self.dir / name
        shutil.copytree(ROOT / "adaptations" / name, folder)
        (folder / "panels/controls").mkdir(parents=True)
        (folder / "panels/controls/index.html").write_text("<!doctype html>\n", encoding="utf-8")
        return folder


class PackageTests(Scratch):
    def test_signed_package_round_trip_and_is_deterministic(self) -> None:
        folder = self.adaptation()
        qarapp.sign_folder(folder, "Quaternar", KEY.sign, KEY.public_der)
        first = self.dir / "a.qarapp"
        second = self.dir / "b.qarapp"
        qarapp.export_package(folder, first)
        qarapp.export_package(folder, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        contents = qarapp.read_package(first, TRUSTED)
        self.assertTrue(contents.verification.signed)
        self.assertEqual(contents.profile["Id"], "com.quaternar.foxglove")
        self.assertIn("panels/controls/index.html", contents.files)

    def test_key_vault_raw_signature_attaches(self) -> None:
        folder = self.adaptation("foxglove")
        _, digest = qarapp.prepare_signing(folder)
        value = qarapp.raw_signature_to_der(qarapp.decode_base64(raw_key_vault_signature(digest)))
        result = qarapp.attach_signature(folder, "Quaternar", KEY.public_der, value)
        self.assertTrue(result.signed)

    def test_signature_over_other_digest_is_refused_on_attach(self) -> None:
        folder = self.adaptation("foxglove")
        with self.assertRaises(qarapp.PackageError):
            qarapp.attach_signature(folder, "Quaternar", KEY.public_der, KEY.sign(bytes(32)))

    def test_tampering_is_refused(self) -> None:
        cases = {
            "changed": lambda folder: (folder / "scripts/foxglove-scene.js").write_text("changed", encoding="utf-8"),
            "unlisted": lambda folder: (folder / "scripts/extra.js").write_text("x", encoding="utf-8"),
            "missing": lambda folder: (folder / "panels/controls/index.html").unlink(),
            "profile": lambda folder: (folder / "profile.json").write_bytes(
                (folder / "profile.json").read_bytes().replace(b'"AppScale": 0.02', b'"AppScale": 0.03')
            ),
        }
        for name, tamper in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.dir / "foxglove", ignore_errors=True)
                folder = self.adaptation()
                qarapp.sign_folder(folder, "Quaternar", KEY.sign, KEY.public_der)
                tamper(folder)
                with self.assertRaises(qarapp.PackageError):
                    qarapp.verify_folder(folder, TRUSTED)

    def test_untrusted_key_is_refused(self) -> None:
        folder = self.adaptation("foxglove")
        qarapp.sign_folder(folder, "Quaternar", OTHER_KEY.sign, OTHER_KEY.public_der)
        with self.assertRaisesRegex(qarapp.PackageError, "not trusted"):
            qarapp.verify_folder(folder, TRUSTED)

    def test_hostile_packages_are_refused(self) -> None:
        manifest = qarapp.package_manifest_bytes()
        profile = (ROOT / "adaptations/foxglove/profile.json").read_bytes()
        cases = {
            "escape": [("package.json", manifest), ("adaptation/profile.json", profile), ("adaptation/../evil.js", b"x")],
            "outside": [("package.json", manifest), ("adaptation/profile.json", profile), ("evil.js", b"x")],
            "newer": [("package.json", b'{"formatVersion": 2, "kind": "web-app-adaptation"}'), ("adaptation/profile.json", profile)],
            "kind": [("package.json", b'{"formatVersion": 1, "kind": "executable-app"}'), ("adaptation/profile.json", profile)],
            "unlisted": [("package.json", manifest), ("adaptation/profile.json", profile), ("adaptation/x.js", b"x")],
        }
        for name, entries in cases.items():
            with self.subTest(name):
                package = self.dir / f"{name}.qarapp"
                package.write_bytes(qarapp.write_zip(entries))
                with self.assertRaises(qarapp.PackageError):
                    qarapp.read_package(package, None)

    def test_versions_order_like_semver(self) -> None:
        ordered = ["0.9.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0", "1.0.1", "1.10.0"]
        parsed = [qarapp.Version.parse(text) for text in ordered]
        for lower, higher in zip(parsed, parsed[1:]):
            self.assertLess(lower, higher, f"{lower} < {higher}")
        for bad in ("1.0", "1.0.0.0", "v1.0.0", "1.0.0-", ""):
            with self.assertRaises(qarapp.PackageError):
                qarapp.Version.parse(bad)


class CheckVersionsTests(Scratch):
    def git(self, *arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=self.dir, check=True, capture_output=True)

    def set_version(self, name: str, version: str) -> None:
        path = self.dir / "adaptations" / name / "profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["Version"] = version
        path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def test_change_needs_a_bump(self) -> None:
        for name in ("foxglove", "threejs-shinjuku"):
            shutil.copytree(ROOT / "adaptations" / name, self.dir / "adaptations" / name)
        self.git("init", "-q")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init", "--allow-empty")
        self.git("add", ".")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "adaptations")
        errors, _, changed = check_versions.check(self.dir, None)
        self.assertEqual(errors, [])
        self.assertTrue(changed)
        self.git("tag", "2026.11.14.1")
        self.assertEqual(check_versions.release_tags(self.dir), ["2026.11.14.1"])

        errors, _, changed = check_versions.check(self.dir, "2026.11.14.1")
        self.assertEqual((errors, changed), ([], False))

        script = self.dir / "adaptations/foxglove/scripts/foxglove-scene.js"
        script.write_text(script.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
        errors, _, changed = check_versions.check(self.dir, "2026.11.14.1")
        self.assertTrue(changed)
        self.assertEqual(len(errors), 1)
        self.assertIn("foxglove", errors[0])

        self.set_version("foxglove", "0.1.1")
        errors, _, _ = check_versions.check(self.dir, "2026.11.14.1")
        self.assertEqual(errors, [])

        self.set_version("threejs-shinjuku", "0.1.1")
        errors, _, _ = check_versions.check(self.dir, "2026.11.14.1")
        self.assertEqual(errors, [])  # the version edit is itself a change, and a bump

        self.set_version("threejs-shinjuku", "0.0.9")
        errors, _, _ = check_versions.check(self.dir, "2026.11.14.1")
        self.assertEqual(len(errors), 1)


class IndexTests(Scratch):
    def build_packages(self, key: qarapp.SigningKey | None) -> Path:
        out = self.dir / "out"
        for name in ("foxglove", "threejs-examples"):
            folder = self.adaptation(name)
            if key is not None:
                qarapp.sign_folder(folder, "Quaternar", key.sign, key.public_der)
            else:
                qarapp.write_manifest(folder)
            profile = qarapp.read_profile(folder)
            qarapp.export_package(folder, out / qarapp.package_file_name(profile["Id"], profile["Version"]))
        return out

    def test_signed_index_verifies_and_detects_changes(self) -> None:
        out = self.build_packages(KEY)
        config = make_index.load_config(ROOT / "release.json")
        index = make_index.build_index(out, "2026.11.14.1", config, TRUSTED)
        digest = make_index.index_digest(index)
        value = qarapp.raw_signature_to_der(qarapp.decode_base64(raw_key_vault_signature(digest)))
        index = make_index.attach(index, "Quaternar", KEY.public_der, value)
        self.assertIn("signed by Quaternar", make_index.verify_index(index, TRUSTED, out, True))
        tampered = json.loads(json.dumps(index))
        tampered["adaptations"][0]["version"] = "9.9.9"
        with self.assertRaises(make_index.IndexFailure):
            make_index.verify_index(tampered, TRUSTED, None, True)
        with self.assertRaises(make_index.IndexFailure):
            make_index.verify_index(index, [("Quaternar", OTHER_KEY.public_der)], None, True)

    def test_index_matches_schema_fields(self) -> None:
        out = self.build_packages(None)
        index = make_index.build_index(out, "2026.11.14.1", make_index.load_config(ROOT / "release.json"), None)
        index = make_index.attach(index, "Quaternar", KEY.public_der, KEY.sign(make_index.index_digest(index)))
        schema = json.loads((ROOT / "schemas/webapps-index.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(set(schema["required"]) <= set(index) <= set(schema["properties"]))
        entry_schema = schema["$defs"]["adaptation"]
        for entry in index["adaptations"]:
            self.assertTrue(set(entry_schema["required"]) <= set(entry) <= set(entry_schema["properties"]))
        signature_schema = schema["$defs"]["signature"]
        self.assertEqual(set(index["signature"]), set(signature_schema["properties"]))


if __name__ == "__main__":
    unittest.main()
