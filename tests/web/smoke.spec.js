const { test, expect } = require('@playwright/test');

// Proves emcc produced a working WebGL2 build, not merely a build.
test('smoke app creates a WebGL2 context and renders geometry', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });

  expect(errors).toEqual([]);

  const hud = await page.textContent('#hud');
  expect(hud).toContain('smoke init complete');
  // Emscripten reports WebGL2 as "OpenGL ES 3.0 ..." — if this says 2.0,
  // the context attributes were not honoured and shaders will not compile.
  expect(hud).toMatch(/OpenGL ES 3\.0/);
});

test('rendered frame is not blank', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });
  await page.waitForTimeout(500); // let a few frames run

  // Sample a wide central band of the canvas, not a 4x4 speck. The face is a
  // gradient (fragColor = vec4(uv.x, uv.y, 0.25, 1)), so the centre pixel has
  // a known value and the band must vary across it.
  //
  // The readback must run inside a requestAnimationFrame callback. WebGL
  // clears the drawing buffer once the compositor has taken the frame, so a
  // readback from any later task (a separate page.evaluate round trip, say)
  // sees the cleared buffer and reports zero variance no matter how correct
  // the render is. The engine registered its own frame callback first, so it
  // runs before this one in the same frame and has just drawn. (Do not add
  // preserveDrawingBuffer to dodge this: it changes the render path.)
  const sample = await page.evaluate(() => new Promise(resolve => {
    requestAnimationFrame(() => {
      const c = document.getElementById('canvas');
      const gl = c.getContext('webgl2');
      const w = 64, h = 64;
      const px = new Uint8Array(4 * w * h);
      gl.readPixels((c.width - w) / 2, (c.height - h) / 2, w, h,
                    gl.RGBA, gl.UNSIGNED_BYTE, px);
      let min = 255, max = 0;
      for (let i = 0; i < px.length; i += 4) {
        min = Math.min(min, px[i]);
        max = Math.max(max, px[i]);
      }
      // Middle pixel of the band == canvas centre, where uv = (0.5, 0.5).
      const ci = 4 * ((h / 2) * w + (w / 2));
      resolve({ r: px[ci], g: px[ci + 1], b: px[ci + 2], variance: max - min });
    });
  }));

  // fragColor at the centre is (0.5, 0.5, 0.25) => (128, 128, 64). A blank or
  // failed render (the clear colour is (13, 13, 20)) misses this by a mile.
  expect(sample.r).toBeGreaterThan(100);
  expect(sample.r).toBeLessThan(156);
  expect(sample.g).toBeGreaterThan(100);
  expect(sample.g).toBeLessThan(156);
  expect(sample.b).toBeGreaterThan(36);
  expect(sample.b).toBeLessThan(92);
  // The 64-wide band spans ~54 levels of the gradient, so a near-flat frame
  // fails here even if its centre pixel happened to look right.
  expect(sample.variance).toBeGreaterThan(16);
});
