import { expect, test } from '@playwright/test'
import { api, streamChat } from '../src/api'

const cases = [
  { name: 'empty proxy failure', status: 500, type: 'text/plain', body: '', expected: 'HTTP 500' },
  { name: 'HTML proxy failure', status: 502, type: 'text/html', body: '<html>Bad gateway</html>', expected: 'HTTP 502' },
  { name: 'plain text failure', status: 503, type: 'text/plain', body: 'Service unavailable', expected: 'Service unavailable' },
  { name: 'invalid JSON failure', status: 500, type: 'application/json', body: '{broken', expected: 'ungültiges JSON' },
  { name: 'FastAPI error detail', status: 422, type: 'application/json', body: '{"detail":"Modell fehlt"}', expected: 'Modell fehlt' },
]

for (const scenario of cases) {
  test(`API and chat report ${scenario.name} explicitly`, async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = async () => new Response(scenario.body, {
      status: scenario.status, headers: { 'Content-Type': scenario.type },
    })
    try {
      await expect(api('/worlds')).rejects.toThrow(scenario.expected)
      await expect(streamChat('/conversations/test/messages', { content: 'Hallo' }, () => {
        throw new Error('Failed requests must never deliver a delta')
      })).rejects.toThrow(scenario.expected)
    } finally {
      globalThis.fetch = originalFetch
    }
  })
}

test('missing backend displays startup guidance rather than a JSON parsing error', async ({ page }) => {
  await page.route('**/api/worlds', route => route.fulfill({ status: 500, body: '' }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Backend in einem zweiten Terminal starten')
  await expect(page.getByRole('alert')).not.toContainText('Unexpected end of JSON input')
})
