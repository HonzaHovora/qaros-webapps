// Builds an AdaptationProfile (qar_cef_browser/AdaptationProfile.hpp) that adapts a three.js
// application with the shared scripts in this directory: no script of the application's own is
// needed. Used two ways:
//
// - as a module: `buildThreejsProfile({ ... })` returns the profile object; a reference
//   application's own build-profile.mjs adds what is particular to it and writes the file.
// - from the command line, for any three.js application:
//
//     node build-threejs-profile.mjs --name my-app --address "*my-app.example.com*" \
//       --page-width 1024 --page-height 768 [--app-scale 1] [--render-scale 0.75] \
//       [--extra script.js ...] --out my-app.json
//
//   Copy the result into the Visualizer's `assets/web-app-source-profiles` directory (development
//   build trees only; an installed QAROS keeps authored apps through `viz_webapp_register`).
//
// `--extra` scripts run after the shared ones (stage afterLoad), for what one application needs on
// top, such as `window.__qarAdaptationState.selectScene`.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const shared = path.join(here, "..");

function read(file, pageRegion) {
	return readFileSync(file, "utf8")
		.replaceAll("__PAGE_REGION_WIDTH__", String(pageRegion.width))
		.replaceAll("__PAGE_REGION_HEIGHT__", String(pageRegion.height));
}

/// `pageRegion` is the part of the canvas the application keeps for its own UI (top-left), in
/// pixels. `extraScripts` are `{ Name, Stage, JavaScript }` entries appended as given.
export function buildThreejsProfile({
	name,
	addressPattern,
	pageRegion,
	appScale = undefined,
	// Half of each user's eye resolution (960x540 for 1080p): every rendered atlas pixel costs on
	// every frame, and the sender upsamples to the receiver's size. A profile can ask for more.
	renderScale = 0.5,
	shareBrowserProfile = true,
	confineReferenceUi = false,
	extraScripts = [],
}) {
	const profile = {
		Name: name,
		AddressPattern: addressPattern,
		Engine: "three.js",
		PageRegion: { Width: pageRegion.width, Height: pageRegion.height },
		ShareBrowserProfile: shareBrowserProfile,
	};
	if (appScale !== undefined) {
		profile.AppScale = appScale;
	}
	if (renderScale !== undefined) {
		profile.RenderScale = renderScale;
	}
	profile.ContinuousRendering = true;
	profile._sv = 2;
	profile.Scripts = [
		{
			Name: "capture-renderer",
			Stage: "preDocument",
			JavaScript: read(path.join(here, "threejs-capture.js"), pageRegion),
		},
		{
			Name: "render-frame-core",
			Stage: "afterLoad",
			JavaScript: read(path.join(shared, "render-frame-core.js"), pageRegion),
		},
		// Only our atlas-sized reference UI needs this convention. Third-party websites keep
		// their original DOM, styles and controls in the responsive browser viewport.
		...(confineReferenceUi ? [{
			Name: "ui-confinement",
			Stage: "afterLoad",
			JavaScript: read(path.join(shared, "ui-confinement.js"), pageRegion),
		}] : []),
		{
			Name: "render-frame-handler",
			Stage: "afterLoad",
			JavaScript: read(path.join(here, "threejs-render-frame.js"), pageRegion),
		},
		...extraScripts,
	];
	return profile;
}

function parseArguments(argv) {
	const options = { extra: [] };
	for (let index = 0; index < argv.length; index += 1) {
		const key = argv[index];
		const value = argv[index + 1];
		if (!key.startsWith("--") || value === undefined) {
			throw new Error(`Unexpected argument ${key}`);
		}
		index += 1;
		if (key === "--extra") {
			options.extra.push(value);
		} else {
			options[key.slice(2)] = value;
		}
	}
	for (const required of ["name", "address", "page-width", "page-height", "out"]) {
		if (options[required] === undefined) {
			throw new Error(`Missing --${required}`);
		}
	}
	return options;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const options = parseArguments(process.argv.slice(2));
	const pageRegion = { width: Number(options["page-width"]), height: Number(options["page-height"]) };
	const profile = buildThreejsProfile({
		name: options.name,
		addressPattern: options.address,
		pageRegion,
		appScale: options["app-scale"] === undefined ? undefined : Number(options["app-scale"]),
		renderScale: options["render-scale"] === undefined ? undefined : Number(options["render-scale"]),
		extraScripts: options.extra.map((file) => ({
			Name: path.basename(file, path.extname(file)),
			Stage: "afterLoad",
			JavaScript: read(path.resolve(file), pageRegion),
		})),
	});
	writeFileSync(options.out, JSON.stringify(profile, null, 2) + "\n", "utf8");
	console.log(`Wrote ${options.out}`);
}
