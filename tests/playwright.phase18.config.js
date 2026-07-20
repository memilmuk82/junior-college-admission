// @ts-check
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: 'phase18_main_admin.spec.js',
  timeout: 90_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  outputDir: '/tmp/phase18-playwright-results',
  use: {
    ...devices['Desktop Chrome'],
    headless: true,
    ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === 'true',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
