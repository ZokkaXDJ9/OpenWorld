import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

const backend = resolve('..', 'backend')
const python = resolve('..', '.venv', 'Scripts', 'python.exe')
export default defineConfig({
  testDir: './e2e',
  timeout: 90000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:15173',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" tests\\e2e_server.py`,
      cwd: backend,
      url: 'http://127.0.0.1:18000/api/health',
      timeout: 60000,
      reuseExistingServer: false,
    },
    {
      command: `"${python}" -m uvicorn mock_server:app --app-dir tests --host 127.0.0.1 --port 18090`,
      cwd: backend,
      url: 'http://127.0.0.1:18090/requests',
      reuseExistingServer: false,
    },
    {
      command: 'node node_modules\\vite\\bin\\vite.js --host 127.0.0.1 --port 15173 --strictPort',
      url: 'http://127.0.0.1:15173',
      env: { OPENWORLD_API_URL: 'http://127.0.0.1:18000' },
      reuseExistingServer: false,
    },
  ],
})
