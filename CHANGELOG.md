# Changelog

All notable changes to the adaptations in this repository are documented here, following
[Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).
Each adaptation has its own version (`Version` in its `profile.json`); releases are tagged
`YYYY.MM.DD.N` by CI. Entries are grouped per adaptation id. How entries and versions are made:
[AGENTS.md](AGENTS.md).

## [Unreleased]

### com.quaternar.foxglove

#### Features

- Foxglove (https://app.foxglove.dev/) streamed in stereo with depth: the scene of its largest 3D panel renders once per eye of every QAROS user (0.1.0).

### com.quaternar.threejs-examples

#### Features

- Any official three.js example (https://threejs.org/examples/) streamed in stereo with depth, one scene unit per metre (0.1.0).

#### Bug fixes

- An example picked in the examples gallery now streams: it opens as the page itself instead of inside the gallery's frame, and Back returns to the gallery (0.1.1).

### com.quaternar.threejs-littlest-tokyo

#### Features

- The three.js Littlest Tokyo example (animated glTF) streamed in stereo with depth (0.1.0).

### com.quaternar.threejs-shinjuku

#### Features

- The Shinjuku Station indoor map demo streamed in stereo with depth as a 1 m table model, its transparent background as alpha (0.1.0).
