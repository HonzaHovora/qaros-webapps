// scripts/open-example.js: the gallery opens a picked example as the
// page itself, so QAROS finds its renderer. No browser needed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
	new URL("../scripts/open-example.js", import.meta.url),
	"utf8"
);

function page(address, { viewerSrc = null, embedded = false } = {}) {
	const url = new URL(address);
	const navigations = [];
	const listeners = [];
	const viewer = { getAttribute: (name) => (name === "src" ? viewerSrc : null) };
	const window = {
		addEventListener: (type, listener, capture) => listeners.push({ type, listener, capture }),
	};
	window.top = embedded ? {} : window;
	const location = {
		href: url.href,
		origin: url.origin,
		pathname: url.pathname,
		assign: (to) => navigations.push({ how: "assign", to }),
		replace: (to) => navigations.push({ how: "replace", to }),
	};
	const document = { getElementById: (id) => (id === "viewer" ? viewer : null) };
	vm.runInNewContext(source, { window, location, document, URL });
	function click(href, init = {}) {
		const anchor = { getAttribute: (name) => (name === "href" ? href : null) };
		const event = {
			button: 0,
			target: { closest: (selector) => (selector === 'a[target="viewer"]' ? anchor : null) },
			defaultPrevented: false,
			propagationStopped: false,
			preventDefault() { this.defaultPrevented = true; },
			stopPropagation() { this.propagationStopped = true; },
			...init,
		};
		for (const { type, listener } of listeners) if (type === "click") listener(event);
		return event;
	}
	return { navigations, listeners, click };
}

test("a gallery card opens its example as the page", () => {
	const gallery = page("https://threejs.org/examples/");
	assert.equal(gallery.listeners.length, 1);
	assert.equal(gallery.listeners[0].capture, true);
	const event = gallery.click("webgl_geometry_cube.html");
	assert.equal(event.defaultPrevented, true);
	assert.equal(event.propagationStopped, true);
	assert.deepEqual(gallery.navigations, [
		{ how: "assign", to: "https://threejs.org/examples/webgl_geometry_cube.html" },
	]);
});

test("a gallery opened at index.html behaves the same", () => {
	const gallery = page("https://threejs.org/examples/index.html");
	gallery.click("webgpu_lights_custom.html");
	assert.deepEqual(gallery.navigations, [
		{ how: "assign", to: "https://threejs.org/examples/webgpu_lights_custom.html" },
	]);
});

test("a gallery opened with an example in its hash is replaced by that example", () => {
	const gallery = page("https://threejs.org/examples/#webgl_animation_skinning_blending", {
		viewerSrc: "webgl_animation_skinning_blending.html",
	});
	assert.deepEqual(gallery.navigations, [
		{ how: "replace", to: "https://threejs.org/examples/webgl_animation_skinning_blending.html" },
	]);
});

test("modified clicks, other links and other origins are left to the browser", () => {
	const gallery = page("https://threejs.org/examples/");
	for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
		assert.equal(gallery.click("webgl_geometry_cube.html", init).defaultPrevented, false);
	}
	assert.equal(gallery.click("https://example.com/webgl_geometry_cube.html").defaultPrevented, false);
	assert.equal(gallery.click("../manual/index.html").defaultPrevented, false);
	assert.equal(gallery.click("sub/page.html").defaultPrevented, false);
	assert.equal(gallery.click("index.html").defaultPrevented, false);
	assert.equal(gallery.click("").defaultPrevented, false);
	assert.deepEqual(gallery.navigations, []);
});

test("an example page and an embedded frame are untouched", () => {
	const example = page("https://threejs.org/examples/webgl_geometry_cube.html", {
		viewerSrc: "webgl_other.html",
	});
	assert.equal(example.listeners.length, 0);
	assert.deepEqual(example.navigations, []);
	const framed = page("https://threejs.org/examples/", { embedded: true, viewerSrc: "webgl_other.html" });
	assert.equal(framed.listeners.length, 0);
	assert.deepEqual(framed.navigations, []);
});

test("the gallery placeholder (no example loaded) stays", () => {
	const gallery = page("https://threejs.org/examples/", { viewerSrc: null });
	assert.deepEqual(gallery.navigations, []);
});
