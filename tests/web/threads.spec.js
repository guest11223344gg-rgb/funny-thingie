const { test, expect } = require('@playwright/test');

// Proves SharedArrayBuffer is usable under the server's isolation headers
// and that a pthread can actually be created and joined.
test('pthread writes through SharedArrayBuffer and main thread reads it', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });
  await page.waitForFunction(() => window.__threadTestDone === true, { timeout: 20000 });

  expect(errors).toEqual([]);
  const hud = await page.textContent('#hud');
  expect(hud).toContain('thread roundtrip ok');
});
