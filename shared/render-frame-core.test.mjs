import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const source = readFileSync(new URL('./render-frame-core.js', import.meta.url), 'utf8');
function harness() {
 const queue = [], draws = [], acknowledgements = [];
 const window = { qaros: { completeRenderFrame: id => acknowledgements.push(id), failRenderFrame: (_, error) => { throw error; } } };
 vm.runInNewContext(source, { window, console, requestAnimationFrame: callback => queue.push(callback) });
 const loop = window.__qarAdaptationCore.createRenderFrameLoop(detail => { draws.push(detail.requestId); return true; });
 return { loop, draws, acknowledgements, tick: timestamp => queue.splice(0).forEach(callback => callback(timestamp)) };
}
test('continuous rendering produces a frame on every tick without another request', () => {
 const h = harness(); h.loop.update({ requestId: 1, continuous: true });
 h.tick(); h.tick(); h.tick();
 assert.deepEqual(h.draws, [1, 1, 1]); assert.deepEqual(h.acknowledgements, [1]);
});
test('updates coalesce to the newest pose and stop cancels queued work', () => {
 const h = harness(); h.loop.update({ requestId: 1, continuous: true }); h.loop.update({ requestId: 2, continuous: true });
 h.tick(); h.loop.update({ requestId: 3, continuous: true }); h.tick(); h.loop.stop(); h.tick();
 assert.deepEqual(h.draws, [2, 3]); assert.deepEqual(h.acknowledgements, [2, 3]);
});
test('legacy requests render once', () => {
 const h = harness(); h.loop.update({ requestId: 7 }); h.tick(); h.tick(); assert.deepEqual(h.draws, [7]);
});

test('pause stops rendering and the next request resumes it', () => {
 const h = harness(); h.loop.update({ requestId: 1, continuous: true }); h.tick(); h.loop.pause(); h.tick();
 h.loop.update({ requestId: 2, continuous: true }); h.tick(); assert.deepEqual(h.draws, [1, 2]);
});

 test('120 Hz ticks render at 60 FPS and use the newest pose without queuing history', () => {
 const h = harness(); h.loop.update({ requestId: 1, continuous: true });
 h.tick(0); h.loop.update({ requestId: 2, continuous: true }); h.tick(1000/120);
 h.loop.update({ requestId: 3, continuous: true }); h.tick(1000/60);
 assert.deepEqual(h.draws, [1, 3]); assert.deepEqual(h.acknowledgements, [1, 3]);
 });

test('60 Hz ticks with timer jitter render on every tick', () => {
 const h = harness(); h.loop.update({ requestId: 1, continuous: true });
 [0, 16.4, 33.5, 49.9, 66.8].forEach(time => h.tick(time));
 assert.equal(h.draws.length, 5);
});

test('a tick during pending work keeps the loop scheduled', () => {
 const queue = [];
 const window = { qaros: { completeRenderFrame() {}, failRenderFrame(_, e) { throw e; } } };
 vm.runInNewContext(source, { window, console, requestAnimationFrame: cb => queue.push(cb) });
 const loop = window.__qarAdaptationCore.createRenderFrameLoop(() => new Promise(() => {}));
 loop.update({ requestId: 1, continuous: true });
 queue.splice(0).forEach(cb => cb(0));
 queue.splice(0).forEach(cb => cb(16.7));
 assert.equal(queue.length, 1, 'the busy tick asked for the next frame');
});

test('asynchronous snapshots never overlap and resume with the newest pose', async () => {
 const queue = [], draws = [], completed = [];
 let release;
 const window = {qaros:{completeRenderFrame:id=>completed.push(id),failRenderFrame:(_,e)=>{throw e}}};
 vm.runInNewContext(source,{window,console,requestAnimationFrame:cb=>queue.push(cb)});
 const loop = window.__qarAdaptationCore.createRenderFrameLoop(detail=>{
   draws.push(detail.requestId); return new Promise(resolve=>{release=()=>resolve(true)});
 });
 const tick = time=>queue.splice(0).forEach(cb=>cb(time));
 loop.update({requestId:1,continuous:true});tick(0);
 loop.update({requestId:2,continuous:true});tick(20);
 loop.update({requestId:3,continuous:true});tick(40);
 assert.deepEqual(draws,[1]);assert.deepEqual(completed,[]);
 release();await new Promise(resolve=>setImmediate(resolve));tick(60);
 assert.deepEqual(draws,[1,3]);assert.deepEqual(completed,[1]);
 release();await new Promise(resolve=>setImmediate(resolve));loop.stop();tick(80);
 assert.deepEqual(completed,[1,3]);assert.deepEqual(draws,[1,3]);
});
