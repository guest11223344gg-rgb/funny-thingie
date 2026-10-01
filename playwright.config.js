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
