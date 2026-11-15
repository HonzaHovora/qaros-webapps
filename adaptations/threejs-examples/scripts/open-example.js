// Stage: afterLoad. threejs-examples only. Opens the example the user picks in the three.js
// examples gallery (https://threejs.org/examples/) as the page itself, instead of in the gallery's
// `viewer` iframe.
//
// Why: QAROS streams the renderer of the top-level page. The gallery shows each example inside an
// iframe, so the top-level page has no canvas, the Visualizer's probe finds no renderer and the
// source never starts. The example's own address (`webgl_xxx.html`) is a normal page this
// adaptation matches, so opening it at top level streams it; Back returns to the gallery.
//
// - A click on a gallery card (`a[target="viewer"]`) opens its address in the page instead. The
//   gallery's own click handler (which sets `#<example>` and loads the iframe) does not run.
// - A gallery opened with `#<example>` already loaded the example in its iframe: the page is
//   replaced by that example (replace, not a new history entry, so Back never lands on a gallery
//   that redirects again).
// - A modified click (Ctrl, Shift, Alt, Meta, middle button) is left to the browser.
// - Only the gallery page itself is touched; an example page loads this script and does nothing.
(() => {
	if (window !== window.top) return;
	const path = location.pathname.replace(/\/index\.html$/, "/");
	if (!/\/examples\/$/.test(path)) return;

	// The example address a gallery link or the viewer iframe points at, or null: same origin,
	// same folder as the gallery, an `.html` page other than the gallery itself.
	function exampleAddress(href) {
		if (!href) return null;
		let url;
		try {
			url = new URL(href, location.href);
		} catch {
			return null;
		}
		if (url.origin !== location.origin) return null;
		if (!url.pathname.startsWith(path) || !url.pathname.endsWith(".html")) return null;
		const file = url.pathname.slice(path.length);
		if (file.includes("/") || file === "index.html") return null;
		return url.href;
	}

	function onClick(event) {
		if (event.button !== 0 || event.ctrlKey || event.shiftKey || event.altKey || event.metaKey) return;
		const anchor = event.target && typeof event.target.closest === "function" ? event.target.closest('a[target="viewer"]') : null;
		if (!anchor) return;
		const address = exampleAddress(anchor.getAttribute("href"));
		if (!address) return;
		event.preventDefault();
		event.stopPropagation();
		location.assign(address);
	}
	// Capture phase on the window: runs before the card's own listener.
	window.addEventListener("click", onClick, true);

	const viewer = document.getElementById("viewer");
	const loaded = viewer ? exampleAddress(viewer.getAttribute("src") || "") : null;
	if (loaded) location.replace(loaded);
})();
