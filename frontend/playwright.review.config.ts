import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/review',
  use: { baseURL: 'http://127.0.0.1:15227', ...devices['Desktop Chrome'] },
  webServer: {
    command:
      'npm run build:review && npx vite preview --outDir review-dist --host 127.0.0.1 --port 15227',
    url: 'http://127.0.0.1:15227',
    reuseExistingServer: false,
  },
})
