# Working in qaros-webapps

Rules for everyone changing this repository, people and coding agents alike. What the repository
holds and how releases are made: [README.md](README.md).

## What belongs here

- Adaptations useful to a broad audience, the ones the QAROS Visualizer shows in user mode.
  Developer and debugging samples stay with the QAROS product.
- One folder per adaptation under `adaptations/`; everything in it is packaged. Never put
  `Files` or `Signature` into a `profile.json` (the build writes them).
- A script copied from `shared/` is changed in `shared/`, then `python -I scripts/sync_shared.py`
  updates every copy.

## Checks

Run before committing, as CI does:

```
python -I -m unittest discover -s scripts/tests
node --test shared/render-frame-core.test.mjs shared/threejs/threejs-capture.test.mjs scripts/tests/threejs-examples-open-example.test.mjs
python -I scripts/sync_shared.py --check
python -I scripts/check_versions.py
python -I scripts/build_packages.py --out out
```

## Versions

- Each adaptation has its own Semantic Version, `Version` in its `profile.json`.
- Any change to an adaptation folder bumps that adaptation's `Version` **in the same commit**:
  - below 1.0 (all adaptations today): `MINOR` for features and breaking changes, `PATCH` for
    fixes;
  - from 1.0: `MAJOR` for breaking changes, `MINOR` for features, `PATCH` for fixes.
- A version is never reused and never lowered; `Id` never changes (a new Id is a new folder).
- `scripts/check_versions.py` refuses a changed adaptation without a bump, compared with the
  previous release.
- Release tags are `YYYY.MM.DD.N`, created by CI on `main` only. Never tag by hand.

## Changelog

[CHANGELOG.md](CHANGELOG.md) follows Keep a Changelog. `## [Unreleased]` is on top. Under each
release, entries are grouped per adaptation (`### <adaptation id>`), and under each adaptation the
categories come in this order, as `####` headings, only those with entries:

`Breaking`, `Features`, `Enhancements`, `Bug fixes`, `Deprecated`, `Removed`, `Security`.

- Every change a user can notice (what a site looks like in the glasses, scale, addresses
  matched, a fixed bug, a new or removed adaptation) adds **one line** under `Unreleased`, in the
  right adaptation and category, **in the same commit** as the change and its version bump.
- The line says what changed for the user, not how, and ends with the new version in
  parentheses. Link the related public issue or pull request with its full URL
  (`https://github.com/Quaternar/qaros-webapps/pull/12`) when there is one.
- No entry for tooling, tests, CI or other changes a user cannot notice.
- A `Breaking` entry says what breaks and what to do.

## This repository is public

- Never reference internal documents or trackers: no internal architecture decision records, no
  links to private issues or repositories.
- No AI attribution anywhere: not in commits (no `Co-Authored-By` lines for tools, no "Generated
  with"), not in pull requests, code, comments or docs.
- Commits: a Conventional Commits subject (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`,
  `test:`, ...), then a body of short bullet points.
- Never commit keys (`*.pem` is ignored).
