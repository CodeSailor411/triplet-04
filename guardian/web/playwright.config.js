import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: process.env.GUARDIAN_PLAYGROUND_URL || 'http://127.0.0.1:5000',
    browserName: 'chromium',
    headless: true,
  },
});
