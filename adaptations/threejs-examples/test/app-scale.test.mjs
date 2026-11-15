// profile.json: the app scale QAROS applies per example. The first AppScaleByAddress entry whose
// pattern matches the loaded address wins, else AppScale. Patterns match as QAROS matches them:
// `*` any run of characters, `?` one character, the whole address.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const profile = JSON.parse(readFileSync(new URL("../profile.json", import.meta.url), "utf8"));

function matchesAddress(pattern, address) {
	// Greedy match with backtracking to the last `*`, the algorithm QAROS uses.
	let p = 0;
	let a = 0;
	let star = -1;
	let starAddress = 0;
	while (a < address.length) {
		if (p < pattern.length && (pattern[p] === "?" || pattern[p] === address[a])) {
			++p;
			++a;
		} else if (p < pattern.length && pattern[p] === "*") {
			star = p++;
			starAddress = a;
		} else if (star >= 0) {
			p = star + 1;
			a = ++starAddress;
		} else {
			return false;
		}
	}
	while (p < pattern.length && pattern[p] === "*") ++p;
	return p === pattern.length;
}

function appScale(address) {
	for (const entry of profile.AppScaleByAddress ?? []) {
		if (matchesAddress(entry.AddressPattern, address)) return entry.AppScale;
	}
	return profile.AppScale;
}

test("the address matcher matches whole addresses with * and ?", () => {
	assert.ok(matchesAddress("https://a.org/*", "https://a.org/"));
	assert.ok(matchesAddress("https://a.org/*.html", "https://a.org/x/y.html"));
	assert.ok(matchesAddress("https://a.org/?.html", "https://a.org/b.html"));
	assert.ok(!matchesAddress("https://a.org/?.html", "https://a.org/bc.html"));
	assert.ok(!matchesAddress("https://a.org/", "https://a.org/x"));
	assert.ok(!matchesAddress("https://a.org/x", "https://a.org/"));
	assert.ok(matchesAddress("*a*b", "xxaxxb"));
	assert.ok(!matchesAddress("*a*b", "xxaxxbc"));
});

test("Littlest Tokyo (webgl_animation_keyframes) streams at 0.2", () => {
	assert.equal(appScale("https://threejs.org/examples/webgl_animation_keyframes.html"), 0.2);
	assert.equal(appScale("https://threejs.org/examples/webgl_animation_keyframes.html?q=1#x"), 0.2);
});

test("every other example and the gallery keep AppScale", () => {
	assert.equal(profile.AppScale, 1);
	for (const address of [
		"https://threejs.org/examples/",
		"https://threejs.org/examples/#webgl_animation_keyframes",
		"https://threejs.org/examples/webgl_animation_skinning_blending.html",
		"https://threejs.org/examples/webgpu_animation_keyframes.html",
	]) {
		assert.equal(appScale(address), profile.AppScale, address);
	}
});

test("every AppScaleByAddress pattern lies inside the profile's AddressPattern", () => {
	for (const entry of profile.AppScaleByAddress) {
		const example = entry.AddressPattern.replaceAll("*", "").replaceAll("?", "x");
		assert.ok(matchesAddress(profile.AddressPattern, example), entry.AddressPattern);
	}
});
