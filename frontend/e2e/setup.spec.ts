import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const api = 'http://127.0.0.1:18000/api'
const mock = 'http://127.0.0.1:18090/v1'

async function openSettings(page: Page) {
  await page.getByRole('navigation').getByRole('button', { name: 'Einstellungen', exact: true }).click()
  await expect(page.getByLabel('Anbieterprofil der Extraktion')).not.toBeVisible()
  await expect(page.getByLabel('Base-URL', { exact: true })).not.toBeVisible()
  await page.getByRole('button', { name: 'KI-Verbindung einrichten', exact: true }).click()
}

async function finish(page: Page, scope = 'Eigene Verbindung (erweitert)') {
  const wizard = page.getByRole('dialog', { name: 'KI einrichten' })
  await wizard.getByRole('radio', { name: scope, exact: true }).check()
  await wizard.getByRole('button', { name: 'Weiter', exact: true }).click()
  if (scope === 'Eigene Verbindung (erweitert)') {
    await wizard.getByLabel('Serveradresse', { exact: true }).fill(mock)
  }
  await wizard.getByRole('button', { name: 'Verbindung prüfen', exact: true }).click()
  await expect(wizard.getByLabel('Modell für deine Charaktere')).toHaveValue('mock-model')
  await expect(wizard.getByRole('button', { name: 'Einrichtung abschließen' })).toBeDisabled()
  await wizard.getByRole('button', { name: 'Antwort testen', exact: true }).click()
  await expect(wizard.getByRole('status')).toContainText('Das Modell hat geantwortet')
  await wizard.getByRole('button', { name: 'Einrichtung abschließen' }).click()
  await expect(wizard).toContainText('Deine KI ist bereit!')
  await wizard.getByRole('button', { name: 'Zurück zum vorherigen Vorgang' }).click()
  await expect(wizard).not.toBeVisible()
}

for (const kind of ['lmstudio', 'ollama'] as const) {
  test(`guided local setup: ${kind}, detected models and actual answer`, async ({ page }) => {
    await page.route('**/api/settings/provider/local', route => route.fulfill({ json: {
      servers: [{ kind, base_url: mock, reachable: true,
        models: [{ id: 'mock-model', name: 'Testmodell', loaded: true }] }],
    } }))
    await page.goto('/')
    await openSettings(page)
    await finish(page, 'Lokale KI auf diesem Computer')
    await expect(page.getByRole('heading', { name: 'Einstellungen', exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}

test('online setup explains cost, requires a key and does not permit hidden retries', async ({ page }) => {
  let tested = 0
  await page.route('**/api/settings/provider/models', route => route.fulfill({ json: {
    models: ['online-model'], details: [{ id: 'online-model', name: 'Online-Modell', loaded: null }],
  } }))
  const settings = { base_url: 'https://api.openai.com/v1', model: 'online-model',
    has_api_key: true, context_window: 4096, max_output_tokens: 1024, temperature: 0.7,
    reasoning_profile: 'openai', reasoning_mode: 'default' }
  await page.route('**/api/settings/provider/test', async route => {
    expect(route.request().postDataJSON().allow_compatibility_retry).toBe(false)
    tested++
    await route.fulfill({ json: { reply: 'OK', settings, verification_token: 'test-proof' } })
  })
  await page.route('**/api/settings/setup', route => route.fulfill({ json: settings }))
  await page.goto('/')
  await openSettings(page)
  const wizard = page.getByRole('dialog')
  await wizard.getByRole('radio', { name: 'KI über einen Online-Anbieter' }).check()
  await wizard.getByRole('button', { name: 'Weiter', exact: true }).click()
  await expect(wizard).toContainText('API-Nutzung kostet')
  await wizard.getByLabel('API-Schlüssel', { exact: true }).fill('synthetic-key')
  await wizard.getByRole('button', { name: 'Verbindung prüfen', exact: true }).click()
  await expect(wizard.getByLabel('Falls nötig einen zweiten Verbindungstest erlauben')).not.toBeChecked()
  await wizard.getByRole('button', { name: 'Antwort testen', exact: true }).click()
  await expect(wizard.getByRole('status')).toContainText('Das Modell hat geantwortet')
  expect(tested).toBe(1)
  await wizard.getByRole('button', { name: 'Später einrichten' }).click()
})

test('first start offers setup without blocking editors; offline guidance does not save', async ({ page, request }) => {
  const original = await (await request.get(`${api}/settings/provider`)).json()
  await page.route('**/api/settings/provider', route => route.fulfill({ json: { ...original, model: '' } }))
  await page.route('**/api/settings/provider/status', route => route.fulfill({ json: {
    state: 'missing', message: 'Für Gespräche benötigst du eine KI. Wir helfen dir bei der Einrichtung.',
  } }))
  await page.route('**/api/settings/provider/local', route => route.fulfill({ json: { servers: [] } }))
  await page.goto('/')
  const notice = page.getByRole('region', { name: 'KI-Verbindung', exact: true })
  await expect(notice).toContainText('Wir helfen dir')
  await expect(page.getByRole('button', { name: 'Neue Welt', exact: true })).toBeEnabled()
  await notice.getByRole('button', { name: 'KI einrichten' }).click()
  const wizard = page.getByRole('dialog')
  await wizard.getByRole('button', { name: 'Weiter', exact: true }).click()
  await expect(wizard.getByRole('status')).toContainText('Noch keine lokale KI erreichbar')
  await page.keyboard.press('Escape')
  await expect(wizard).not.toBeVisible()
  expect(await (await request.get(`${api}/settings/provider`)).json()).toEqual(original)
})

for (const target of ['Chats', 'Gruppengespräche', 'Simulationen'] as const) {
  test(`setup returns to the selected ${target} without losing the original task`, async ({ page, request }) => {
    const world = await (await request.post(`${api}/worlds`, { data: { name: `Setup ${target}` } })).json()
    const base = `${api}/worlds/${world.id}`
    const place = await (await request.post(`${base}/locations`, { data: { name: 'Garten' } })).json()
    for (const name of ['Ari', 'Bela']) {
      await request.post(`${base}/characters`, { data: { name, location_id: place.id, travel_status: 'present' } })
    }
    await page.goto('/')
    await page.getByRole('button', { name: `Setup ${target} öffnen` }).click()
    await page.getByRole('navigation').getByRole('button', { name: target, exact: true }).click()
    if (target === 'Chats') {
      await page.getByLabel('Charakter', { exact: true }).selectOption({ label: 'Ari' })
      await page.getByRole('button', { name: 'Neues Gespräch', exact: true }).click()
      await expect(page.locator('.chat-header h3')).toHaveText('Ari')
      await page.getByLabel('Deine Nachricht').fill('Meine noch nicht gesendete Nachricht')
    } else {
      await page.getByRole('button', { name: target === 'Simulationen' ?
        'Neue Simulation' : 'Neues Gruppengespräch', exact: true }).click()
      await page.getByLabel('Titel', { exact: true }).fill('Meine Ausgangssituation')
      await page.getByRole('checkbox', { name: 'Ari' }).check()
      await page.getByRole('checkbox', { name: 'Bela' }).check()
      await page.getByLabel('Szenenort', { exact: true }).selectOption(place.id)
      await page.getByRole('button', { name: 'Anlegen', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Meine Ausgangssituation', exact: true })).toBeVisible()
    }
    await page.getByRole('region', { name: 'KI-Verbindung', exact: true }).getByRole('button', { name: 'KI einrichten' }).click()
    await finish(page)
    if (target === 'Chats') {
      await expect(page.locator('.chat-header h3')).toHaveText('Ari')
      await expect(page.getByLabel('Deine Nachricht')).toHaveValue('Meine noch nicht gesendete Nachricht')
      await page.getByRole('button', { name: 'Senden', exact: true }).click()
      await expect(page.locator('.messages')).toContainText('Hallo, ich bin Lumia')
    } else {
      await expect(page.getByRole('heading', { name: 'Meine Ausgangssituation', exact: true })).toBeVisible()
      if (target === 'Simulationen') {
        await page.getByRole('button', { name: '1 Runde', exact: true }).click()
        await expect(page.locator('.ensemble-message')).toHaveCount(1, { timeout: 30000 })
        const simulations = await (await request.get(`${base}/simulations`)).json()
        const detail = await (await request.get(`${base}/simulations/${simulations[0].id}`)).json()
        expect(detail.calls_used).toBe(1)
        expect(detail.jobs).toEqual([])
      }
    }
  })
}

test('ordinary memory controls preserve safeguards and do not call the model', async ({ page, request }) => {
  const world = await (await request.post(`${api}/worlds`, { data: { name: 'Gedächtnisoptionen' } })).json()
  await page.goto('/')
  await page.getByRole('button', { name: 'Gedächtnisoptionen öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Einstellungen', exact: true }).click()
  const originalCalls = await (await request.get('http://127.0.0.1:18090/requests')).json()
  await expect(page.getByLabel('Anbieterprofil der Extraktion')).not.toBeVisible()
  await page.getByLabel('Erinnerungen aus Gesprächen automatisch erkennen', { exact: true }).check()
  await expect(page.getByLabel('Wichtige Weltveränderungen vor dem Speichern bestätigen lassen')).toBeChecked()
  await expect.poll(async () => (await (await request.get(
    `${api}/worlds/${world.id}/event-settings`)).json()).enabled).toBe(true)
  await page.getByRole('button', { name: 'Automatische Erinnerungen und Ereignisse deaktivieren' }).click()
  await expect(page.getByRole('status')).toContainText('auch in Simulationen')
  await expect(page.getByRole('button', { name: 'Automatische Erinnerungen und Ereignisse deaktivieren' })).toBeEnabled()
  const current = await (await request.get(`${api}/worlds/${world.id}/event-settings`)).json()
  expect(current.automation_disabled).toBe(true)
  expect(current.confirm_changes).toBe(true)
  expect(current.enabled).toBe(false)
  await page.route(`**/worlds/${world.id}/event-settings`, route =>
    route.request().method() === 'PUT' ? route.fulfill({
      status: 409, json: { detail: 'Einstellungen wurden inzwischen geändert. Bitte erneut versuchen.' },
    }) : route.continue())
  await page.getByLabel('Erinnerungen aus Gesprächen automatisch erkennen', { exact: true }).check()
  await expect(page.getByRole('alert')).toContainText('Bitte erneut versuchen')
  await expect(page.getByLabel('Erinnerungen aus Gesprächen automatisch erkennen', { exact: true })).not.toBeChecked()
  expect(await (await request.get(`${api}/worlds/${world.id}/event-settings`)).json()).toEqual(current)
  expect(await (await request.get('http://127.0.0.1:18090/requests')).json()).toEqual(originalCalls)
})
