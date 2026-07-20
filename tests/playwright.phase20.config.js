// @ts-check
import { defineConfig, devices } from '@playwright/test';

const phase20E2eUrl = process.env.PHASE20_E2E_URL;
if (!phase20E2eUrl) {
  throw new Error(
    'PHASE20_E2E_URL is required (for example: https://admission.example.com/demo).',
  );
}

export default defineConfig({
  testDir: '.',
  testMatch: 'phase20_full_demo.spec.js',
  timeout: 180_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  outputDir: '/tmp/phase20-playwright-results',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: phase20E2eUrl,
    headless: true,
    ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === 'true',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
