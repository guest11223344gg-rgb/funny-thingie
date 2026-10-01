const { test, expect } = require('@playwright/test');

// Proves emcc produced a working WebGL2 build, not merely a build.
test('smoke app creates a WebGL2 context and renders geometry', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('http://localhost:8080/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });

  expect(errors).toEqual([]);

  const hud = await page.textContent('#hud');
  expect(hud).toContain('smoke init complete');
  // Emscripten reports WebGL2 as "OpenGL ES 3.0 ..." — if this says 2.0,
  // the context attributes were not honoured and shaders will not compile.
  expect(hud).toMatch(/OpenGL ES 3\.0/);
});

test('rendered frame is not blank', async ({ page }) => {
  await page.goto('http://localhost:8080/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });
  await page.waitForTimeout(500); // let a few frames run

  // Sample the centre of the canvas. A blank or failed render is uniform;
  // a drawn triangle has a gradient across it.
  //
  // The readback must run inside a requestAnimationFrame callback. WebGL
  // clears the drawing buffer once the compositor has taken the frame, so a
  // readback from any later task (a separate page.evaluate round trip, say)
  // sees the cleared buffer and reports zero variance no matter how correct
  // the render is. The engine registered its own frame callback first, so it
  // runs before this one in the same frame and has just drawn.
  const variance = await page.evaluate(() => new Promise(resolve => {
    requestAnimationFrame(() => {
      const c = document.getElementById('canvas');
      const gl = c.getContext('webgl2');
      const px = new Uint8Array(4 * 16);
      gl.readPixels(c.width / 2 - 2, c.height / 2 - 2, 4, 4,
                    gl.RGBA, gl.UNSIGNED_BYTE, px);
      let min = 255, max = 0;
      for (let i = 0; i < px.length; i += 4) {
        min = Math.min(min, px[i]);
        max = Math.max(max, px[i]);
      }
      resolve(max - min);
    });
  }));
  expect(variance).toBeGreaterThan(0);
});
