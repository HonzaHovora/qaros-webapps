// Stage: afterLoad -- this needs a parsed DOM, which a preDocument script never has.
//
// Engine-agnostic, like render-frame-core.js alongside it in this shared directory: the only
// convention it depends on is that a reference application collects its entire interface (panels,
// toasts, a popup, an overlay) under one `#app-ui` container, positioned `fixed` at the full viewport
// with `overflow: hidden`, with every one of those pieces itself `position: absolute` against that
// container rather than `position: fixed` against the viewport. That is ordinary application CSS, not
// an adaptation hook, but it is what makes shrinking one box the whole of "confine the interface to
// the page region": clipping `#app-ui` clips its absolutely-positioned descendants along with it. Both
// `sample/threejs-reference-app/` and `sample/webgl-reference-app/` follow it, which is what lets this
// one file serve either.
//
// This is the other half of canvas takeover alongside each application's own engine-specific
// preDocument script: that script keeps the application's own rendered *view* inside the page region;
// this one keeps its *chrome* there too. Without both, a naive capture of the composited page would
// leak panels, toasts, the popup or the overlay into a per-user rendered view -- the exact failure
// these reference applications exist to make visible.
(() => {
	const pageRegion = window.__qarAdaptationPageRegion || {
		width: __PAGE_REGION_WIDTH__,
		height: __PAGE_REGION_HEIGHT__,
	};
	const style = document.createElement("style");
	style.textContent = `
		#app-ui {
			width: var(--qar-page-width, ${pageRegion.width}px) !important;
			height: var(--qar-page-height, ${pageRegion.height}px) !important;
		}
	`;
	document.head.appendChild(style);
})();
