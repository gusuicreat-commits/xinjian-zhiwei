import { defineConfig, devices } from '@playwright/test'

if (!process.env.XINJIAN_EVAL_POSTGRES_DSN) {
  throw new Error('XINJIAN_EVAL_POSTGRES_DSN is required; integration checks cannot be skipped.')
}
if (!process.env.BACKEND_PYTHON) {
  throw new Error('BACKEND_PYTHON is required for the isolated real backend fixture.')
}

const frontendPort = Number(process.env.INTEGRATION_FRONTEND_PORT ?? '15173')
const backendPort = Number(process.env.INTEGRATION_BACKEND_PORT ?? '18101')
if (
  ![frontendPort, backendPort].every(
    (port) => Number.isInteger(port) && port > 1024 && port < 65536,
  )
) {
  throw new Error('Integration ports must be integers between 1025 and 65535.')
}
const baseURL = `http://127.0.0.1:${frontendPort}`
const backendURL = `http://127.0.0.1:${backendPort}`

export default defineConfig({
  testDir: './tests/integration',
  testMatch: '**/*.integration.ts',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: './test-results/integration',
  reporter: [
    ['list'],
    ['html', { outputFolder: './playwright-report/integration', open: 'never' }],
    ['json', { outputFile: './playwright-report/integration/results.json' }],
  ],
  use: {
    baseURL,
    actionTimeout: 15_000,
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'real-postgres-chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(process.env.INTEGRATION_CHROME_CHANNEL
          ? { channel: process.env.INTEGRATION_CHROME_CHANNEL }
          : {}),
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: backendURL, VITE_DEV_API_TARGET: backendURL },
  },
})
