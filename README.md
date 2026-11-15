# qaros-webapps

Web app adaptations for QAROS: the scripts and settings that let QAROS stream a website (three.js
examples, Foxglove) to every user's view in stereo with depth. Each adaptation is published as a
`.qarapp` package; QAROS downloads new releases by itself.

This repository holds adaptations useful to a broad audience, the ones the Visualizer shows in
user mode. Developer and debugging samples stay with the QAROS product.

Index of the newest release (fixed address, no API token, no rate limit):

```
https://github.com/Quaternar/qaros-webapps/releases/latest/download/webapps-index.json
```

## Layout

```
adaptations/<name>/          one adaptation folder, packaged as it is
  profile.json               Id, Name, DisplayName, Version, StartAddress, AddressPattern, PageRegion, Scripts, ...
  scripts/*.js               the scripts profile.json names (Scripts[].File)
  panels/                    optional served panel pages
shared/                      libraries several adaptations copy (see shared/README.md)
  copies.json                which adaptation script is a copy of which library
schemas/webapps-index.schema.json
scripts/                     build tooling (Python 3, standard library only)
release.json                 repository name and the minimum QAROS version per adaptation
CHANGELOG.md                 changes per release, grouped per adaptation
AGENTS.md                    contribution rules (versions, changelog, public-repo rules)
.github/workflows/           ci.yml (pull requests), release.yml (main)
```

Everything in an adaptation folder ends up in its package, so keep only adaptation files there.
A `profile.json` in the repository never holds `Files` or `Signature`: the build writes both.

## Adaptations

| Folder | Id | Opens | Version |
|---|---|---|---|
| `foxglove` | `com.quaternar.foxglove` | https://app.foxglove.dev/ | 0.1.0 |
| `threejs-examples` | `com.quaternar.threejs-examples` | https://threejs.org/examples/ | 0.1.0 |
| `threejs-littlest-tokyo` | `com.quaternar.threejs-littlest-tokyo` | three.js `webgl_animation_keyframes` | 0.1.0 |
| `threejs-shinjuku` | `com.quaternar.threejs-shinjuku` | Shinjuku Station indoor map demo | 0.1.0 |

## Versioning

- Every adaptation has its own semantic version, `Version` in its `profile.json`. All start at
  0.1.0: below 1.0 an adaptation is not yet considered stable.
- Any change to an adaptation folder (a script, a panel file, a profile field) needs a higher
  `Version`. While below 1.0: MINOR for features and breaking changes, PATCH for fixes. From 1.0:
  MAJOR for breaking changes (a newer QAROS needed, different addresses matched), MINOR for
  features, PATCH for fixes. `scripts/check_versions.py` refuses a changed folder without a bump,
  compared with the previous release tag; CI runs it on every pull request.
- A user-noticeable change also gets a one-line entry in `CHANGELOG.md` under `[Unreleased]`, in
  the same commit as the bump (see AGENTS.md).
- QAROS installs a package only when it is newer than the copy it has, so a version is never
  reused and never goes down.
- `Id` is permanent. A different Id is a different adaptation: add a new folder.
- `release.json` sets `minQarosVersion` (the oldest QAROS that installs the packages), globally or
  per folder under `adaptations`.
- QAROS stops shipping its own copies of these adaptations and takes them from this repository's
  releases, so QAROS product versions and adaptation versions never compete.
- Releases currently use date-based tags (`YYYY.MM.DD.N`), not the shared QAROS scheme in [ADR-0001: One versioning scheme for every QAROS repository](https://github.com/Quaternar/qaros/blob/main/docs/adr/0001-one-versioning-scheme.md). Moving to it needs the tools that pick the newest release changed first.

## Releases

Every merge to `main` that changes an adaptation publishes a release (several a day are fine):

1. tests, shared library copies, version check;
2. one package per adaptation: `<id>-<version>.qarapp`;
3. when signing is configured: each package signed with the QAROS release key, held in Azure Key
   Vault (the build hands the package digest to `az keyvault key sign --algorithm ES256` and
   attaches the answer);
4. `webapps-index.json` written, and signed with the same key when signing is configured;
5. everything verified (against the public key when signed), then published as release
   `YYYY.MM.DD.N` (UTC date, N counting from 1 per day), marked latest. Tags are made by CI only.

Signing is optional:

- **Unsigned** (today): none of the Key Vault variables below is set. Packages carry `Files` but no
  `Signature`, the index has no `signature` block, entries say `"signed": false`, and the release
  notes say the release is unsigned.
- **Signed**: all of `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `QAROS_RELEASE_KEY_VAULT` and
  `QAROS_RELEASE_PUBLIC_KEY` are set; every package and the index must then verify as signed.
- Setting only some of them fails the run instead of publishing.

A push that changes no adaptation publishes nothing; run the Release workflow by hand with
`force` to publish anyway.

Signing configuration lives in the GitHub environment `release-signing` (variables only, no
secrets; `azure/login` uses OIDC):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | identity with a federated credential for `repo:Quaternar/qaros-webapps:environment:release-signing` |
| `AZURE_TENANT_ID` | its tenant |
| `AZURE_SUBSCRIPTION_ID` | optional |
| `QAROS_RELEASE_KEY_VAULT` | Key Vault holding the release key (the identity needs the key's `sign` permission, e.g. "Key Vault Crypto User") |
| `QAROS_RELEASE_KEY_NAME` | key name, default `qaros-release` |
| `QAROS_RELEASE_PUBLIC_KEY` | the key's public half (PEM text), the key QAROS pins |

Limit the environment to the `main` branch.

## Package format

A `.qarapp` is a ZIP:

```
package.json             {"content": "adaptation", "formatVersion": 1, "kind": "web-app-adaptation"}
adaptation/profile.json  the profile plus Files and Signature
adaptation/...           exactly the files Files lists
```

- `Files`: every file of the folder except `profile.json`, sorted by path, as
  `{"Path": ..., "Sha256": <lower-case hex>}`. Paths are relative, `/`-separated, at most 512
  bytes, with only `A-Z a-z 0-9 . _ - ~ + @ ( ) ! ,` per segment.
- `Signature`: `{"Signer": "Quaternar", "KeyId": <hex SHA-256 of the DER public key>,
  "PublicKey": <base64 DER SubjectPublicKeyInfo>, "Algorithm": "ECDSA-P256-SHA256",
  "Value": <base64 DER signature>}` over
  `SHA-256("QAROS-ADAPTATION-SIGNATURE-V1" NUL canonical(profile.json without Signature))`,
  canonical meaning sorted keys, no whitespace, UTF-8. Through `Files` it covers every file.
- Entries are deflated, in manifest order, dated 1980-01-01: the same folder gives the same bytes.

The index (`schemas/webapps-index.schema.json`) lists per adaptation `id`, `version`, `asset`,
`url`, `release`, `sha256`, `size`, `formatVersion`, `minQarosVersion` and `signed`. Its `signature`
block (same fields, lower camel case) covers
`SHA-256("QAROS-WEBAPPS-INDEX-SIGNATURE-V1" NUL canonical(index without signature))`.

## Tooling

Python 3.10 or newer, standard library only; run with `python -I`.

```
python -I -m unittest discover -s scripts/tests          tooling tests
python -I scripts/sync_shared.py [--check]               shared library copies
python -I scripts/check_versions.py [--base <tag>]       version bumps against the previous release
python -I scripts/build_packages.py --out out            unsigned packages, verified
python -I scripts/make_index.py build --packages out --release 2026.01.01.1 --out out/webapps-index.json
python -I scripts/make_index.py verify out/webapps-index.json --packages out
python -I scripts/qarapp.py verify out/<package>.qarapp [--public-key key.pem]
```

Signing locally (testing only; never commit a key, `*.pem` is ignored):

```
python -I scripts/qarapp.py keygen test.key.pem test.pub.pem
python -I scripts/build_packages.py --out out --private-key test.key.pem
python -I scripts/make_index.py build --packages out --release 2026.01.01.1 --out out/webapps-index.json --private-key test.key.pem
```

With a key held elsewhere: `qarapp.py digest <folder>` / `make_index.py digest <index>` print the
digest to sign, `qarapp.py attach` / `make_index.py attach --signature-file` attach the detached
signature (raw r||s as Key Vault answers it, or DER). `build_packages.py --tool
<qar-adaptation-tool>` also verifies every package with the QAROS command-line tool.

## Origin

The adaptations were previously generated when QAROS was built, and this repository holds that
output as static folders:

| Here | Came from |
|---|---|
| `threejs-littlest-tokyo`, `threejs-examples`, `threejs-shinjuku` | generated from the three.js libraries with page region 1024 x 1024, `RenderScale` 0.5, per example `AppScale` and address; Shinjuku with `TransportAlpha`. Scripts: `threejs-capture.js` as `capture-renderer`, `render-frame-core.js`, `threejs-render-frame.js` as `render-frame-handler` |
| `foxglove` | a manifest naming the same three libraries plus its own `foxglove-scene.js`, page region 1280 x 1024 |
| `scripts/<script>.js` | the library or local file, with `__PAGE_REGION_WIDTH__`/`__PAGE_REGION_HEIGHT__` replaced by the page region |
| `profile.json` | the manifest with `_sv` 3, `ShareBrowserProfile` true, `Id` `com.quaternar.<name>`, `DisplayName`, `Version`, `Panels` `panels`, `StartAddress`, each script as `File` `scripts/<name>.js` with empty `JavaScript` |
| `shared/` | the shared libraries these adaptations copy, plus `ui-confinement.js` for the three.js profile builder |

Differences from what earlier QAROS builds shipped, none of which changes behaviour:

- `Version` is 0.1.0 instead of the QAROS version (0.9.0): adaptation versions are independent of
  QAROS versions.
- Line endings are LF everywhere (builds on Windows wrote CRLF).
