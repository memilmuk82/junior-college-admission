// @ts-check
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: 'phase14_public_calculation.spec.js',
  timeout: 45_000,
  workers: 1,
  use: {
    browserName: 'chromium',
    headless: true,
    trace: 'retain-on-failure',
  },
  reporter: [['list']],
});
