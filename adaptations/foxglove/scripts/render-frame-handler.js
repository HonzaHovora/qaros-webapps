// Stage: afterLoad. Shared by every three.js application's adaptation profile; must be injected after
// render-frame-core.js and after threejs-capture.js has run (preDocument). It answers each
// `qaros-render-frame` request by drawing every connected user's views from the application's own
// renderer and scene, found by threejs-capture.js. It needs no global from the application: no
// `window.THREE`, `window.scene` or `window.camera`.
//
// One animation tick, one scene render: every eye of every user is drawn by a single `renderer.render`
// with an `ArrayCamera`, so the scene is culled, its shadows rendered and its lights set up once per
// tick, and each eye only re-issues the draw calls into its own viewport. The eyes are drawn into
// one offscreen framebuffer of this script's own (raw WebGL2: an RGBA8 colour texture and a 24-bit
// depth texture), which three.js treats as the canvas: for the duration of that render the
// context's `bindFramebuffer(null)` binds it instead. So three.js applies tone mapping and the
// output colour space exactly as it does for the application's own canvas, and passes that switch
// to a render target and back (shadow maps, transmission, reflectors) come back to it. The colour
// and depth of each eye are then copied into their atlas rectangles by two small shaders.
//
// The camera classes come from the renderer itself: `renderer.xr.getCamera()` is an `ArrayCamera`,
// whose base class is `PerspectiveCamera`. three.js culls with the array camera's own frustum, which
// cannot be one eye's when users stand apart, so it is an orthographic box large enough to keep
// everything; each eye's viewport clips the rest. The eye cameras take the application camera's
// layers, so what the application hides by layer stays hidden.
//
// The users' room is the scene's own space unless a profile places it: `window.__qarAdaptationState
// .sceneFromRoom = () => ({ position: [x, y, z], quaternion: [x, y, z, w] })`, asked once per tick,
// is the room's pose in the scene (a Z-up scene, or one followed by the application's own camera).
// The eye cameras are children of that pose, so depth stays along each eye's own view.
//
// Depth: the raw post-projection depth, packed as 24-bit unsigned normalized RGB at half linear
// resolution, two side-by-side tiles of half the view's width and a quarter of its height
// (docs/cef-vulkan-browser.md "Depth", RenderStreamProtocol.cpp `BuildRenderAtlasPlan`). Native
// code is told the projection convention per camera and reconstructs from it. A logarithmic depth
// buffer is not linear post-projection depth and is not supported.
//
// Not covered: post-processing (EffectComposer passes run on the application's own frame only),
// a `WebGPURenderer`, and multisampling of the eye views (they render below the receiver's
// resolution and the sender upsamples them; a resolve per request costs more than the edges gain).
(() => {
	const core = window.__qarAdaptationCore;
	const state = window.__qarAdaptationState;

	const eyeCameras = new Map();
	let cameraClasses = null;
	let arrayCamera = null;
	let pass = null;
	let programs = null;

	function findCameraClasses(renderer) {
		if (cameraClasses) {
			return cameraClasses;
		}
		const xrCamera = renderer.xr && typeof renderer.xr.getCamera === "function" ? renderer.xr.getCamera() : null;
		if (xrCamera && xrCamera.isArrayCamera) {
			const ArrayCamera = xrCamera.constructor;
			const PerspectiveCamera = Object.getPrototypeOf(ArrayCamera.prototype).constructor;
			cameraClasses = { ArrayCamera, PerspectiveCamera };
		} else if (window.THREE && window.THREE.ArrayCamera) {
			cameraClasses = { ArrayCamera: window.THREE.ArrayCamera, PerspectiveCamera: window.THREE.PerspectiveCamera };
		} else {
			throw new Error("QAR adaptation: cannot find three.js camera classes on the renderer.");
		}
		return cameraClasses;
	}

	// The room's pose in the scene; every eye camera is its child.
	let roomInScene = null;
	function updateRoomInScene(classes) {
		if (!roomInScene) {
			const Object3D = Object.getPrototypeOf(Object.getPrototypeOf(classes.PerspectiveCamera.prototype)).constructor;
			roomInScene = new Object3D();
		}
		const pose = typeof state.sceneFromRoom === "function" ? state.sceneFromRoom() : null;
		roomInScene.position.fromArray(pose ? pose.position : [0, 0, 0]);
		roomInScene.quaternion.fromArray(pose ? pose.quaternion : [0, 0, 0, 1]);
		roomInScene.updateMatrixWorld(true);
	}

	function getEyeCamera(classes, key) {
		let camera = eyeCameras.get(key);
		if (!camera) {
			camera = new classes.PerspectiveCamera();
			camera.viewport = { x: 0, y: 0, z: 1, w: 1 };
			roomInScene.add(camera);
			eyeCameras.set(key, camera);
		}
		return camera;
	}

	// An asymmetric projection from the four frustum angles native code supplies: the two eyes of a
	// stereo pair are not generally symmetric.
	function configureCamera(camera, protocolCamera, layersMask) {
		const { pose, fov, nearFar } = protocolCamera;
		camera.position.fromArray(pose.position);
		camera.quaternion.set(pose.orientation[0], pose.orientation[1], pose.orientation[2], pose.orientation[3]);
		camera.near = nearFar.near;
		camera.far = nearFar.far;
		camera.projectionMatrix.makePerspective(
			Math.tan(fov.angleLeft) * camera.near,
			Math.tan(fov.angleRight) * camera.near,
			Math.tan(fov.angleUp) * camera.near,
			Math.tan(fov.angleDown) * camera.near,
			camera.near,
			camera.far,
			camera.coordinateSystem
		);
		camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
		camera.layers.mask = layersMask;
		camera.updateMatrixWorld(true);
	}

	function ensureArrayCamera(classes) {
		if (arrayCamera) {
			return arrayCamera;
		}
		arrayCamera = new classes.ArrayCamera([]);
		const extent = 1e6;
		arrayCamera.projectionMatrix.makeOrthographic(
			-extent,
			extent,
			extent,
			-extent,
			-extent,
			extent,
			arrayCamera.coordinateSystem
		);
		arrayCamera.projectionMatrixInverse.copy(arrayCamera.projectionMatrix).invert();
		return arrayCamera;
	}

	function createTexture(gl, internalFormat, width, height) {
		const texture = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, texture);
		gl.texStorage2D(gl.TEXTURE_2D, 1, internalFormat, width, height);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		return texture;
	}

	function ensurePass(gl, width, height) {
		if (pass && pass.width === width && pass.height === height) {
			return pass;
		}
		if (pass) {
			gl.deleteFramebuffer(pass.framebuffer);
			gl.deleteTexture(pass.color);
			gl.deleteTexture(pass.depth);
		}
		const color = createTexture(gl, gl.RGBA8, width, height);
		const depth = createTexture(gl, gl.DEPTH_COMPONENT24, width, height);
		const framebuffer = gl.createFramebuffer();
		gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, color, 0);
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, depth, 0);
		const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
		gl.bindFramebuffer(gl.FRAMEBUFFER, null);
		if (status !== gl.FRAMEBUFFER_COMPLETE) {
			throw new Error(`QAR adaptation: eye framebuffer incomplete (0x${status.toString(16)})`);
		}
		pass = { width, height, color, depth, framebuffer };
		return pass;
	}

	const fullScreenVertex = `#version 300 es
		void main() {
			vec2 corner = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
			gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
		}`;

	// One texel per destination pixel: `source` + (pixel - `destination`). Opaque: Chromium
	// composites alpha < 1 premultiplied (atlas page) or over white (stream surface), which
	// changes the colour bytes, so the stream never depends on the app's canvas alpha.
	const copyFragment = `#version 300 es
		precision highp float;
		uniform highp sampler2D colorTexture;
		uniform ivec2 sourceOrigin;
		uniform ivec2 destinationOrigin;
		out vec4 outColor;
		void main() {
			outColor = vec4(texelFetch(colorTexture, sourceOrigin + ivec2(gl_FragCoord.xy) - destinationOrigin, 0).rgb, 1.0);
		}`;

	// Row 0 of the packed rectangle is the view's top row, the same atlas convention every colour
	// view relies on. One depth texel per half-resolution sample, never a filtered blend.
	const packFragment = `#version 300 es
		precision highp float;
		uniform highp sampler2D depthTexture;
		uniform ivec2 depthOrigin;
		uniform vec2 depthSize;
		uniform ivec2 destinationOrigin;
		uniform float halfWidth;
		uniform float tileHeight;
		out vec4 outColor;
		void main() {
			vec2 local = floor(gl_FragCoord.xy) - vec2(destinationOrigin);
			float halfHeight = tileHeight * 2.0;
			float packedX = local.x;
			float packedY = tileHeight - 1.0 - local.y;
			float tileIndex = packedX < halfWidth ? 0.0 : 1.0;
			float halfX = tileIndex < 0.5 ? packedX : packedX - halfWidth;
			float halfY = tileIndex < 0.5 ? packedY : packedY + tileHeight;
			vec2 eyeTexel = vec2(
				clamp(floor((halfX + 0.5) * depthSize.x / halfWidth - 0.5), 0.0, depthSize.x - 1.0),
				clamp(floor((halfY + 0.5) * depthSize.y / halfHeight - 0.5), 0.0, depthSize.y - 1.0)
			);
			eyeTexel.y = depthSize.y - 1.0 - eyeTexel.y;
			float rawDepth = texelFetch(depthTexture, depthOrigin + ivec2(eyeTexel), 0).r;
			// At depth 1, float32 rounds 16777215 + 0.5 to 16777216. Saturate before
			// splitting bytes, otherwise the far plane wraps to near-plane black.
			float scaled = min(floor(clamp(rawDepth, 0.0, 1.0) * 16777215.0 + 0.5), 16777215.0);
			outColor = vec4(
				mod(scaled, 256.0) / 255.0,
				mod(floor(scaled / 256.0), 256.0) / 255.0,
				mod(floor(scaled / 65536.0), 256.0) / 255.0,
				1.0
			);
		}`;

	// Alpha at half linear resolution, three consecutive half-resolution rows per atlas row (R, G,
	// B), each sample the mean of its 2x2 eye pixels. Opaque, so CEF keeps every byte; native
	// unpacks it into the colour view's alpha channel.
	const alphaPackFragment = `#version 300 es
		precision highp float;
		uniform highp sampler2D colorTexture;
		uniform ivec2 eyeOrigin;
		uniform ivec2 eyeSize;
		uniform ivec2 destinationOrigin;
		uniform int tileHeight;
		out vec4 outColor;
		float halfAlpha(int column, int row) {
			if (row * 2 >= eyeSize.y) return 0.0;
			float sum = 0.0;
			for (int dy = 0; dy < 2; ++dy) {
				for (int dx = 0; dx < 2; ++dx) {
					int x = min(column * 2 + dx, eyeSize.x - 1);
					int y = min(row * 2 + dy, eyeSize.y - 1);
					sum += texelFetch(colorTexture, eyeOrigin + ivec2(x, eyeSize.y - 1 - y), 0).a;
				}
			}
			return sum * 0.25;
		}
		void main() {
			ivec2 local = ivec2(gl_FragCoord.xy) - destinationOrigin;
			int row = (tileHeight - 1 - local.y) * 3;
			outColor = vec4(halfAlpha(local.x, row), halfAlpha(local.x, row + 1), halfAlpha(local.x, row + 2), 1.0);
		}`;

	function compileProgram(gl, fragmentSource, uniformNames) {
		const shader = (type, source) => {
			const object = gl.createShader(type);
			gl.shaderSource(object, source);
			gl.compileShader(object);
			if (!gl.getShaderParameter(object, gl.COMPILE_STATUS)) {
				throw new Error("QAR adaptation: shader compile failed: " + gl.getShaderInfoLog(object));
			}
			return object;
		};
		const program = gl.createProgram();
		gl.attachShader(program, shader(gl.VERTEX_SHADER, fullScreenVertex));
		gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fragmentSource));
		gl.linkProgram(program);
		if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
			throw new Error("QAR adaptation: shader link failed: " + gl.getProgramInfoLog(program));
		}
		const uniforms = {};
		for (const name of uniformNames) {
			uniforms[name] = gl.getUniformLocation(program, name);
		}
		return { program, uniforms };
	}

	function ensurePrograms(gl) {
		if (programs) {
			return programs;
		}
		programs = {
			copy: compileProgram(gl, copyFragment, ["colorTexture", "sourceOrigin", "destinationOrigin"]),
			pack: compileProgram(gl, packFragment, [
				"depthTexture",
				"depthOrigin",
				"depthSize",
				"destinationOrigin",
				"halfWidth",
				"tileHeight",
			]),
			alpha: compileProgram(gl, alphaPackFragment, [
				"colorTexture",
				"eyeOrigin",
				"eyeSize",
				"destinationOrigin",
				"tileHeight",
			]),
			vertexArray: gl.createVertexArray(),
		};
		return programs;
	}

	// One entry per eye that has a view: its camera, its colour, depth and packed-alpha views (any
	// may be absent) and the size they are rendered at.
	function collectEyes(classes, targets, layersMask) {
		const eyes = [];
		for (const target of targets) {
			const byEye = new Map();
			for (const view of target.views) {
				const eye = byEye.get(view.eye) || { name: view.eye, target };
				eye[view.dataType === "depth" || view.dataType === "alpha" ? view.dataType : "color"] = view;
				byEye.set(view.eye, eye);
			}
			for (const eye of byEye.values()) {
				const sizeView = eye.color || eye.depth;
				eye.width = sizeView.logicalWidth;
				eye.height = sizeView.logicalHeight;
				// Each depth view comes from its own eye's render, or the far eye's depth would be
				// warped against the wrong view.
				const side = eye.name === "right" ? "right" : "left";
				eye.camera = getEyeCamera(classes, `${target.id}:${side}`);
				configureCamera(eye.camera, target.cameras[side], layersMask);
				eyes.push(eye);
			}
		}
		return eyes;
	}

	// One row per user; each eye's camera viewport is its rectangle, y counted from the bottom.
	function layoutEyes(eyes) {
		let width = 0;
		let rowY = 0;
		let rowTarget = null;
		let rowX = 0;
		let rowHeight = 0;
		for (const eye of eyes) {
			if (eye.target !== rowTarget) {
				rowY += rowHeight;
				rowTarget = eye.target;
				rowX = 0;
				rowHeight = 0;
			}
			Object.assign(eye.camera.viewport, { x: rowX, y: rowY, z: eye.width, w: eye.height });
			rowX += eye.width;
			rowHeight = Math.max(rowHeight, eye.height);
			width = Math.max(width, rowX);
		}
		return { width, height: rowY + rowHeight };
	}

	// Users see only what has depth: the mixer places every pixel by its depth and clips it to the
	// app volume, and a pixel at the far plane is "nothing here". An opaque material that writes no
	// depth (a ground plane drawn with depthWrite: false, a common trick for floors and decals) would
	// vanish from every user's view while the page still shows it, so for the users' views every
	// opaque material writes depth. Transparent materials keep theirs. Returns what to restore.
	function writeDepthForOpaqueMaterials(scene) {
		const changed = [];
		const writeDepth = (material) => {
			if (!material || material.depthWrite !== false || material.transparent) return;
			if (material.opacity !== undefined && material.opacity < 1) return;
			material.depthWrite = true;
			changed.push(material);
		};
		scene.traverse((object) => {
			if (!object.isMesh) return;
			if (Array.isArray(object.material)) object.material.forEach(writeDepth);
			else writeDepth(object.material);
		});
		return () => changed.forEach((material) => { material.depthWrite = false; });
	}

	// three.js thinks it draws to the canvas; the context binds the eye framebuffer instead.
	function renderIntoPass(renderer, gl, scene, camera, framebuffer) {
		const bindFramebuffer = gl.bindFramebuffer;
		const drawBuffers = gl.drawBuffers;
		const ownBindFramebuffer = Object.hasOwn(gl, "bindFramebuffer");
		const ownDrawBuffers = Object.hasOwn(gl, "drawBuffers");
		let redirected = false;
		renderer.setRenderTarget(null);
		renderer.resetState();
		gl.bindFramebuffer = (target, buffer) => {
			if (target === gl.FRAMEBUFFER || target === gl.DRAW_FRAMEBUFFER) redirected = buffer === null;
			return bindFramebuffer.call(gl, target, buffer === null ? framebuffer : buffer);
		};
		// three.js selects BACK for its canvas, but the redirected framebuffer owns COLOR_ATTACHMENT0.
		// Intermediate render targets retain their own attachment selection.
		gl.drawBuffers = (buffers) => drawBuffers.call(gl,
			redirected ? buffers.map((buffer) => buffer === gl.BACK ? gl.COLOR_ATTACHMENT0 : buffer) : buffers);
		// Users get the scene without its background: in AR the room shows behind it. Clearing to
		// the page's background colour instead would blend that colour into every antialiased edge
		// (the resolved edge pixel mixes object and clear colour), a coloured fringe in the headset.
		const background = scene.background;
		scene.background = null;
		const restoreDepthWrite = writeDepthForOpaqueMaterials(scene);
		try {
			gl.bindFramebuffer(gl.FRAMEBUFFER, null);
			renderer.setScissorTest(false);
			renderer.clear(true, true, true);
			renderer.render(scene, camera);
		} finally {
			restoreDepthWrite();
			scene.background = background;
			if (ownBindFramebuffer) gl.bindFramebuffer = bindFramebuffer;
			else delete gl.bindFramebuffer;
			if (ownDrawBuffers) gl.drawBuffers = drawBuffers;
			else delete gl.drawBuffers;
			bindFramebuffer.call(gl, gl.FRAMEBUFFER, null);
		}
	}

	function renderAllEyes(classes, renderer, gl, scene, eyes, layersMask) {
		const size = layoutEyes(eyes);
		const target = ensurePass(gl, size.width, size.height);
		const camera = ensureArrayCamera(classes);
		camera.cameras = eyes.map((eye) => eye.camera);
		camera.layers.mask = layersMask;
		// Only the transparent objects' draw order uses the array camera's pose (in scene space).
		eyes[0].camera.matrixWorld.decompose(camera.position, camera.quaternion, camera.scale);
		renderIntoPass(renderer, gl, scene, camera, target.framebuffer);
		return target;
	}

	function drawRect(gl, atlasHeight, rect) {
		const y = atlasHeight - rect.y - rect.height;
		gl.viewport(rect.x, y, rect.width, rect.height);
		gl.scissor(rect.x, y, rect.width, rect.height);
		gl.drawArrays(gl.TRIANGLES, 0, 3);
		return y;
	}

	function copyEyesToAtlas(gl, target, atlasHeight, eyes) {
		const { copy, pack, alpha, vertexArray } = ensurePrograms(gl);
		gl.bindFramebuffer(gl.FRAMEBUFFER, null);
		gl.bindVertexArray(vertexArray);
		gl.disable(gl.DEPTH_TEST);
		gl.disable(gl.BLEND);
		gl.disable(gl.CULL_FACE);
		gl.disable(gl.STENCIL_TEST);
		gl.enable(gl.SCISSOR_TEST);
		gl.colorMask(true, true, true, true);
		gl.activeTexture(gl.TEXTURE0);
		for (const eye of eyes) {
			const viewport = eye.camera.viewport;
			if (eye.color) {
				const rect = eye.color.rect;
				gl.useProgram(copy.program);
				gl.bindTexture(gl.TEXTURE_2D, target.color);
				gl.uniform1i(copy.uniforms.colorTexture, 0);
				gl.uniform2i(copy.uniforms.sourceOrigin, viewport.x, viewport.y);
				gl.uniform2i(copy.uniforms.destinationOrigin, rect.x, atlasHeight - rect.y - rect.height);
				drawRect(gl, atlasHeight, rect);
			}
			if (eye.depth) {
				const rect = eye.depth.rect;
				gl.useProgram(pack.program);
				gl.bindTexture(gl.TEXTURE_2D, target.depth);
				gl.uniform1i(pack.uniforms.depthTexture, 0);
				gl.uniform2i(pack.uniforms.depthOrigin, viewport.x, viewport.y);
				gl.uniform2f(pack.uniforms.depthSize, eye.width, eye.height);
				gl.uniform2i(pack.uniforms.destinationOrigin, rect.x, atlasHeight - rect.y - rect.height);
				gl.uniform1f(pack.uniforms.halfWidth, eye.depth.logicalWidth / 2);
				gl.uniform1f(pack.uniforms.tileHeight, rect.height);
				drawRect(gl, atlasHeight, rect);
			}
			if (eye.alpha) {
				const rect = eye.alpha.rect;
				gl.useProgram(alpha.program);
				gl.bindTexture(gl.TEXTURE_2D, target.color);
				gl.uniform1i(alpha.uniforms.colorTexture, 0);
				gl.uniform2i(alpha.uniforms.eyeOrigin, viewport.x, viewport.y);
				gl.uniform2i(alpha.uniforms.eyeSize, eye.width, eye.height);
				gl.uniform2i(alpha.uniforms.destinationOrigin, rect.x, atlasHeight - rect.y - rect.height);
				gl.uniform1i(alpha.uniforms.tileHeight, rect.height);
				drawRect(gl, atlasHeight, rect);
			}
		}
		gl.bindVertexArray(null);
	}

	if (state.renderFrameLoop) state.renderFrameLoop.stop();
	let surfaceWindow, surfaceCanvas, surfaceContext;
	function streamingSurface(width, height) {
		if (!surfaceWindow || surfaceWindow.closed) {
			surfaceWindow = window.open("about:blank", "__qar_stream_surface__");
			if (!surfaceWindow) throw new Error("QAR adaptation: independent streaming surface was blocked.");
			surfaceWindow.document.documentElement.style.cssText = "margin:0;overflow:hidden;background:black";
			surfaceWindow.document.body.style.margin = "0";
			surfaceCanvas = surfaceWindow.document.createElement("canvas");
			surfaceWindow.document.body.appendChild(surfaceCanvas);
			surfaceContext = surfaceCanvas.getContext("bitmaprenderer");
		}
		if (surfaceCanvas.width !== width) surfaceCanvas.width = width;
		if (surfaceCanvas.height !== height) surfaceCanvas.height = height;
		return surfaceContext;
	}
	// Establish the compositor before native code waits for the first atlas-size paint.
	streamingSurface(1, 1);
	window.addEventListener("pagehide", () => { if (surfaceWindow && !surfaceWindow.closed) surfaceWindow.close(); });
	// Snapshots resolve out of the loop's way; only the newest one reaches the stream surface.
	let snapshotsTaken = 0, newestTransferred = 0;
	function transferSnapshot(snapshot, context) {
		const generation = ++snapshotsTaken;
		snapshot.then((bitmap) => {
			if (generation < newestTransferred || !surfaceWindow || surfaceWindow.closed) {
				bitmap.close();
				return;
			}
			newestTransferred = generation;
			context.transferFromImageBitmap(bitmap);
		}, (error) => console.error("QAR adaptation: stream surface snapshot failed", error));
	}
	const loop = core.createRenderFrameLoop((detail) => {
		const renderer = state && state.renderer;
		const scene = state && state.scene;
		if (!renderer || !scene) {
			throw new Error("QAR adaptation: no captured three.js renderer/scene yet -- the application has not rendered a frame.");
		}
		const gl = typeof renderer.getContext === "function" ? renderer.getContext() : null;
		if (!gl || typeof gl.createShader !== "function") {
			throw new Error("QAR adaptation: this renderer uses WebGPU; the shared stereo/depth pass currently requires a WebGL renderer.");
		}
		const atlasHeight = detail.atlas.height;
		if (gl.drawingBufferWidth !== detail.atlas.width || gl.drawingBufferHeight !== atlasHeight)
			renderer.setSize(renderer.domElement.clientWidth, renderer.domElement.clientHeight);
		// Diagnostic, reported once: the canvas must cover the atlas 1:1 or every view and the
		// render-frame tag land at different rows than native code reads.
		if (
			!state.canvasSizeReported &&
			(gl.drawingBufferWidth !== detail.atlas.width || gl.drawingBufferHeight !== atlasHeight)
		) {
			state.canvasSizeReported = true;
			const rect = renderer.domElement.getBoundingClientRect();
			throw new Error(
				`QAR adaptation: canvas buffer ${gl.drawingBufferWidth}x${gl.drawingBufferHeight}, ` +
					`css ${rect.left},${rect.top} ${rect.width}x${rect.height}, ` +
					`inner ${window.innerWidth}x${window.innerHeight}, dpr ${window.devicePixelRatio}, ` +
					`atlas ${detail.atlas.width}x${atlasHeight}`
			);
		}

		const classes = findCameraClasses(renderer);
		const layersMask = state.camera && state.camera.layers ? state.camera.layers.mask : 1;
		updateRoomInScene(classes);
		state.suspendConfinement = true;
		try {
			const eyes = collectEyes(classes, detail.targets, layersMask);
			if (eyes.length > 0) {
				const target = renderAllEyes(classes, renderer, gl, scene, eyes, layersMask);
				copyEyesToAtlas(gl, target, atlasHeight, eyes);
			}
		} finally {
			state.suspendConfinement = false;
		}
		const tagged = core.writeRenderFrameTag(gl, detail);
		const context = streamingSurface(detail.atlas.width, atlasHeight);
		// Snapshot the atlas before restoring the application's own view. The original WebGL
		// context stays with the app, retaining its GPU environment maps and resources. Default
		// options keep the copy on the GPU (~0.1 ms); "none" for alpha or colour space forces a
		// CPU readback (~118 ms at 8000x4096). Every atlas byte is opaque, so nothing is converted.
		// Not awaited: the copy is queued on the GPU now, and the loop draws again next tick.
		transferSnapshot(createImageBitmap(renderer.domElement), context);
		renderer.resetState();
		if (state.camera) renderer.render(scene, state.camera);
		return tagged;
	});
	state.renderFrameLoop = loop;
	window.addEventListener("qaros-render-frame", ({ detail }) => loop.update(detail));
	window.addEventListener("qaros-render-stop", () => loop.pause());
})();
