// Stage: afterLoad, after threejs-render-frame.js. Site-specific for Foxglove (app.foxglove.dev), any
// organization, project and layout.
//
// Which panel streams: Foxglove builds one three.js WebGLRenderer per 3D panel and per Image panel.
// Users get the 3D panel: every panel container carries
// `data-testid="panel-mouseenter-container <Type>!<id>"`, and among several 3D panels the largest
// on screen wins. Should that attribute change, a renderer whose last scene has no
// `foxglove.ImageMode` node counts as a 3D panel. Image panels and smaller 3D panels keep rendering
// in the page only.
//
// Where the room sits: Foxglove's world is ROS Z-up with X forward. The room (Y-up, -Z forward) is
// turned so room up is scene +Z and room forward is scene +X, and its origin is where the 3D
// panel's own camera looks at the ground plane (z = 0). Users see what the panel shows, following
// its follow mode and panning; orbiting the panel never spins the room. A view above the horizon
// keeps the last anchor.
//
// Not streamed: Foxglove's HTML overlays (labels drawn as DOM, the measurement readout) and its
// selection outline pass, which run on the panel's own frame only.
(() => {
	const state = window.__qarAdaptationState;

	function panelType(canvas) {
		const container = canvas.closest('[data-testid^="panel-mouseenter-container"]');
		const panelId = container ? container.getAttribute("data-testid").split(" ")[1] : "";
		return panelId && panelId.includes("!") ? panelId.split("!")[0] : "";
	}

	function isThreeDeePanel(renderer) {
		const type = panelType(renderer.domElement);
		if (type) return type === "3D";
		const scene = renderer.__qarLastScene;
		return !!scene && !scene.children.some((child) => child.name === "foxglove.ImageMode");
	}

	state.chooseRenderer = (renderers) => {
		let best = null;
		let bestArea = 0;
		for (const renderer of renderers) {
			const canvas = renderer.domElement;
			if (!canvas || !canvas.isConnected || !isThreeDeePanel(renderer)) continue;
			const area = canvas.clientWidth * canvas.clientHeight;
			if (area > bestArea) {
				best = renderer;
				bestArea = area;
			}
		}
		return best;
	};

	const zUpFromYUp = [0.5, -0.5, -0.5, 0.5]; // Rz(-90) * Rx(+90)
	let anchor = [0, 0, 0];
	state.sceneFromRoom = () => {
		const camera = state.camera;
		if (camera && camera.matrixWorld) {
			const e = camera.matrixWorld.elements;
			const forwardZ = -e[10];
			if (forwardZ < -1e-3) {
				const t = -e[14] / forwardZ;
				anchor = [e[12] - e[8] * t, e[13] - e[9] * t, 0];
			}
		}
		return { position: anchor, quaternion: zUpFromYUp };
	};
})();
