// The suite is not self-contained: there is no webServer entry, so `npm test`
// on its own cannot reach the app and the specs fail with ECONNREFUSED. Start
// the dev server first, from the repository root, then run the tests:
//
//     python tools/serve.py 8080 build/web   # serves build/web at "/"
//     npm test
//
// The specs load http://localhost:8080/, so the root argument must be the
// directory holding the built index.html, build/web. A webServer entry here
// would make the suite self-contained, but that changes the test lifecycle
// (Tasks 5-6 were built against a manually started server), so it is
// deliberately omitted.
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/web',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 60000,
  use: {
    // The WebGL context must be real, not SwiftShader, or the frame
    // contents differ and the render assertions are meaningless.
    launchOptions: {
      args: ['--use-gl=angle', '--enable-unsafe-swiftshader'],
    },
  },
});
