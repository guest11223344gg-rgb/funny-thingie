const { test, expect } = require('@playwright/test');

// Proves the server sets the headers SharedArrayBuffer needs. If this
// fails, pthreads cannot work later regardless of what the build does.
test('server sends cross-origin isolation headers', async ({ request }) => {
  const res = await request.get('http://localhost:8080/');
  expect(res.status()).toBe(200);
  expect(res.headers()['cross-origin-opener-policy']).toBe('same-origin');
  expect(res.headers()['cross-origin-embedder-policy']).toBe('require-corp');
});

test('page reports crossOriginIsolated as true', async ({ page }) => {
  await page.goto('http://localhost:8080/');
  expect(await page.evaluate(() => self.crossOriginIsolated)).toBe(true);
});
