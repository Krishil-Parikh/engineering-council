import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

// The same browser, the real gateway (with scripted models so no network is needed), and the Vite app in live mode.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, '../..');
const python = process.env.PYTHON ?? path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const gatewayPort = 8765;
const appPort = 3100;

export default defineConfig({
  testDir: './e2e-live',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 8 * 60 * 1000,
  reporter: 'list',
  use: { baseURL: `http://127.0.0.1:${appPort}`, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" tests/gateway/serve_scripted.py ${gatewayPort}`,
      cwd: repo,
      url: `http://127.0.0.1:${gatewayPort}/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: `npm run dev -- --port=${appPort}`,
      cwd: __dirname,
      url: `http://127.0.0.1:${appPort}`,
      reuseExistingServer: false,
      timeout: 120000,
      env: { VITE_TRANSPORT: 'http-sse', VITE_API_BASE_URL: `http://127.0.0.1:${gatewayPort}`, VITE_WORKSPACE_ID: 'workspace-demo', VITE_ENABLE_SIMULATION: 'false' },
    },
  ],
});
