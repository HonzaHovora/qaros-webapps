# Shared adaptation libraries

Scripts several adaptations use. Each adaptation is packaged exactly as its folder is, so it holds
its own copy of every library it uses (`adaptations/<name>/scripts/`). `copies.json` lists which
adaptation script is a copy of which library; `scripts/sync_shared.py` writes the copies and
`--check` (CI) fails when one differs. When a library is copied, `__PAGE_REGION_WIDTH__` and
`__PAGE_REGION_HEIGHT__` become the adaptation's `PageRegion`.

| Library | Stage | Purpose |
|---|---|---|
| `render-frame-core.js` | afterLoad | Acknowledges or fails a `qaros-render-frame` request; engine independent. |
| `ui-confinement.js` | afterLoad | Clips a page's `#app-ui` container to the reserved page region; used by `threejs/build-threejs-profile.mjs` (`confineReferenceUi`), no adaptation here copies it. |
| `threejs/threejs-capture.js` | preDocument | Finds the three.js renderer, scene and camera through three.js's devtools hook (no globals needed). |
| `threejs/threejs-render-frame.js` | afterLoad | Renders every eye in one `ArrayCamera` pass and packs colour, depth and optional alpha into the atlas. |

Changing a library: edit it here, run `python -I scripts/sync_shared.py`, and bump the `Version` of
every adaptation whose copy changed.

Tests (Node 20 or newer, no packages):

```
node --test shared/render-frame-core.test.mjs shared/threejs/threejs-capture.test.mjs shared/threejs/threejs-depth-pack.test.mjs
```

`threejs/build-threejs-profile.mjs` builds a single-file three.js profile for a new site (used by
the tests). `threejs/verify-depth.py` checks the shipped depth packing on a running QAROS web app
source through the Visualizer MCP endpoint (Developer UI mode).
