// Stage: afterLoad. Engine-agnostic: nothing in this file mentions three.js, WebGL or WebGPU. This is
// the "shared core adaptation script" the parent spec calls for -- moved here, out of any one
// reference application's own `adaptation/` directory, once a second consumer
// (`sample/webgl-reference-app/`) needed the identical file rather than a copy of it. Every
// `build-profile.mjs` in `sample/*/adaptation/` reads it from this shared location instead of
// duplicating its text. It owns exactly the boilerplate every engine's render-frame handler needs
// regardless of how it actually draws: acknowledging or failing a `qaros-render-frame` request, never
// leaving native code waiting on a request nothing will ever answer.
(() => {
	/// Runs `work` synchronously against one render-frame request's `detail`, then acknowledges it.
	/// A rendered frame is only actually visible to CEF's next paint, not the instant `work` returns
	/// -- the double `requestAnimationFrame` gives the compositor two frames to pick it up before
	/// `completeRenderFrame` tells native code the frame is ready to read back, the same pattern this
	/// module's other painting scripts already use. A thrown error -- a bad camera, a missing
	/// renderer, anything -- fails the request instead of silently publishing a stale or partial
	/// frame; native code marks that cycle's frames invalid and moves on.
	///
	/// When `work` returns true it has tagged its frame (`writeRenderFrameTag`): native code then
	/// recognises the exact paint carrying this request by its tag, so the request is acknowledged
	/// at once instead of after two animation frames.
	function withRenderFrameAcknowledgement(detail, work) {
		function complete(tagged) {
			if (tagged === true) window.qaros.completeRenderFrame(detail.requestId);
			else requestAnimationFrame(() => requestAnimationFrame(() => window.qaros.completeRenderFrame(detail.requestId)));
			return true;
		}
		function fail(error) {
			console.error("QAR adaptation: render-frame request failed", error);
			window.qaros.failRenderFrame(detail.requestId, error);
			return false;
		}
		try {
			const result = work();
			return result && typeof result.then === "function" ? result.then(complete, fail) : complete(result);
		} catch (error) { return fail(error); }
	}

	/// Writes the request's tag into `detail.tag` (the atlas's reserved last row): the request id's
	/// low 24 bits as one pixel's RGB and their complement as the next, so native code can find the
	/// paint that carries this request and reject one that does not. Raw scissored clears on the
	/// default framebuffer, so the bytes are exact -- no blending, colour management or sampling.
	/// Returns false when there is no tag to write; an engine that wraps `gl` must reset its own
	/// state cache afterwards (three.js: `renderer.resetState()`).
	function writeRenderFrameTag(gl, detail) {
		const tag = detail.tag;
		if (!gl || !tag || tag.width < 2) {
			return false;
		}
		const id = Number(BigInt(detail.requestId) & 0xffffffn);
		const values = [id, ~id & 0xffffff];
		const flippedY = gl.drawingBufferHeight - tag.y - 1;
		gl.bindFramebuffer(gl.FRAMEBUFFER, null);
		gl.colorMask(true, true, true, true);
		gl.enable(gl.SCISSOR_TEST);
		if (detail.continuous) {
			gl.scissor(detail.atlas.width - 4, flippedY, 4, 1);
			gl.clearColor(0, 0, 0, 0);
			gl.clear(gl.COLOR_BUFFER_BIT);
		}
		values.forEach((value, index) => {
			gl.scissor(tag.x + index, flippedY, 1, 1);
			gl.clearColor((value & 0xff) / 255, ((value >> 8) & 0xff) / 255, ((value >> 16) & 0xff) / 255, 1);
			gl.clear(gl.COLOR_BUFFER_BIT);
		});
		return true;
	}

	// Camera updates are a mailbox. Rendering follows Chromium's tick, never its paint reply.
	function createRenderFrameLoop(work, maxFramesPerSecond = 60) {
		let latest = null, acknowledged = null, queued = false, stopped = false;
		let lastDraw = -Infinity, busy = false;
		const interval = 1000 / maxFramesPerSecond;
		function tick(timestamp) {
			queued = false;
			if (stopped || !latest) return;
			// Keep the clock running while asynchronous work finishes: waiting for its promise to
			// request the next frame lost a whole tick whenever it resolved after that frame began,
			// halving the frame rate under load.
			if (busy) { schedule(); return; }
			// Three quarters of the interval: 120 Hz ticks still render at 60 FPS, while a 60 Hz tick
			// arriving slightly early (timer jitter) is not skipped for a whole frame.
			if (Number.isFinite(timestamp) && timestamp - lastDraw < interval * 0.75) { schedule(); return; }
			lastDraw = timestamp;
			const detail = latest;
			let result;
			try {
				if (acknowledged !== detail) {
					result = withRenderFrameAcknowledgement(detail, () => work(detail));
					acknowledged = detail;
				} else result = work(detail);
			} catch (error) { window.qaros.failRenderFrame(detail.requestId, error); latest = null; }
			function resume(success) {
				busy = false;
				if (success === false && latest === detail) latest = null;
				if (latest && latest.continuous) schedule();
			}
			if (result && typeof result.then === "function") {
				busy = true;
				if (latest && latest.continuous) schedule();
				result.then(resume, error => { window.qaros.failRenderFrame(detail.requestId, error); resume(false); });
			} else resume(result);
		}
		function schedule() {
			if (!queued && !stopped) { queued = true; requestAnimationFrame(tick); }
		}
		return Object.freeze({
			update(detail) {
				if (stopped) return;
				if (!detail.continuous) {
					latest = null;
					withRenderFrameAcknowledgement(detail, () => work(detail));
					return;
				}
				latest = detail;
				schedule();
			},
			stop() { stopped = true; latest = null; },
			pause() { latest = null; },
		});
	}

	window.__qarAdaptationCore = Object.freeze({
		createRenderFrameLoop,
		withRenderFrameAcknowledgement,
		writeRenderFrameTag,
	});
})();
