import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  const api = 'http://127.0.0.1:18000/api'
  expect((await request.put(`${api}/settings/provider`, { data: {
    base_url: 'http://127.0.0.1:18090/v1', model: 'mock-model',
    context_window: 16384, max_output_tokens: 256,
  } })).ok()).toBeTruthy()
  expect((await request.put(`${api}/settings/extraction`, { data: {
    provider_profile: 'compatible', structured_output: 'text', max_output_tokens: 1024,
    auto_retry: false,
  } })).ok()).toBeTruthy()
})

test('simulation: bounded steps, intervention, resume, time and cancellation', async ({ page, request }) => {
  const api = 'http://127.0.0.1:18000/api'
  const world = await (await request.post(`${api}/worlds`, { data: { name: 'Simulationswelt' } })).json()
  const base = `${api}/worlds/${world.id}`
  const place = await (await request.post(`${base}/locations`, { data: { name: 'Marktplatz' } })).json()
  for (const name of ['Lumia', 'Power']) {
    await request.post(`${base}/characters`, { data: {
      name, location_id: place.id, travel_status: 'present', profile: { Geheimnis: `${name}-privat` },
    } })
  }
  await page.goto('/')
  await page.getByRole('button', { name: 'Simulationswelt öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Simulationen', exact: true }).click()
  await page.getByRole('button', { name: 'Neue Simulation', exact: true }).click()
  await page.getByLabel('Titel', { exact: true }).fill('Marktgespräch')
  await page.getByRole('checkbox', { name: 'Lumia' }).check()
  await page.getByRole('checkbox', { name: 'Power' }).check()
  await page.getByLabel('Szenenort', { exact: true }).selectOption(place.id)
  await page.getByRole('button', { name: 'Anlegen', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Marktgespräch', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '1 Runde', exact: true }).click()
  await expect(page.getByText('Steuerung · Pausiert', { exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.ensemble-message')).toHaveCount(1)
  await expect(page.locator('.ensemble-layout')).toContainText('Runden: 1 / 20')
  await expect(page.getByRole('region', { name: 'Simulationsereignisse' })).toContainText('Übernommen: 1')
  await page.getByLabel('Eingriff im pausierten Gespräch').fill('Besprecht den Markt.')
  await page.getByRole('button', { name: 'Beitrag senden', exact: true }).click()
  await expect(page.locator('.ensemble-message')).toHaveCount(2)
  await page.getByRole('button', { name: '1 Runde', exact: true }).click()
  await expect(page.locator('.ensemble-layout')).toContainText('Runden: 2 / 20', { timeout: 30000 })
  await expect(page.locator('.ensemble-message')).toHaveCount(3)
  await expect(page.locator('.ensemble-transcript')).not.toContainText('-privat')
  await page.getByRole('button', { name: 'Abbrechen', exact: true }).click()
  await expect(page.getByText('Steuerung · Abgebrochen', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Fortsetzen', exact: true })).toBeDisabled()
  const sessions = await (await request.get(`${base}/simulations`)).json()
  expect(sessions[0].completed_rounds).toBe(2)
  expect((await (await request.get(`${base}/clock`)).json()).elapsed_minutes).toBe(2)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('group conversation: human contribution and independently selected speakers', async ({ page, request }) => {
  const api = 'http://127.0.0.1:18000/api'
  const world = await (await request.post(`${api}/worlds`, { data: { name: 'Gruppenwelt' } })).json()
  const base = `${api}/worlds/${world.id}`
  const place = await (await request.post(`${base}/locations`, { data: { name: 'Garten' } })).json()
  for (const name of ['Ari', 'Bela']) {
    await request.post(`${base}/characters`, { data: { name, location_id: place.id, travel_status: 'present' } })
  }
  await page.goto('/')
  await page.getByRole('button', { name: 'Gruppenwelt öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Gruppengespräche', exact: true }).click()
  await page.getByRole('button', { name: 'Neues Gruppengespräch', exact: true }).click()
  await page.getByRole('checkbox', { name: 'Ari' }).check()
  await page.getByRole('checkbox', { name: 'Bela' }).check()
  await page.getByLabel('Szenenort', { exact: true }).selectOption(place.id)
  await page.getByRole('button', { name: 'Anlegen', exact: true }).click()
  await page.getByLabel('Dein Beitrag').fill('Guten Morgen.')
  await page.getByRole('button', { name: 'Beitrag senden', exact: true }).click()
  await page.getByRole('button', { name: 'Ari antwortet', exact: true }).click()
  await expect(page.locator('.ensemble-message')).toHaveCount(2)
  await page.getByRole('button', { name: 'Bela antwortet', exact: true }).click()
  await expect(page.locator('.ensemble-message')).toHaveCount(3)
  await expect(page.locator('.ensemble-message strong')).toHaveText(['Du', 'Ari', 'Bela'])
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('relationship graph edits the existing directed edge and world export is downloadable', async ({ page, request }) => {
  const api = 'http://127.0.0.1:18000/api'
  const world = await (await request.post(`${api}/worlds`, { data: { name: 'Graphwelt' } })).json()
  const base = `${api}/worlds/${world.id}`
  const a = await (await request.post(`${base}/characters`, { data: { name: 'Ari' } })).json()
  const b = await (await request.post(`${base}/characters`, { data: { name: 'Bela' } })).json()
  await request.post(`${base}/relationships`, { data: { source_id: a.id, target_id: b.id, kind: 'Rivalität' } })
  await page.goto('/')
  await page.getByRole('button', { name: 'Graphwelt öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Beziehungen', exact: true }).click()
  await page.locator('.relationship-graph').getByText('Rivalität', { exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Gerichtete Beziehung', exact: true })).toBeVisible()
  await page.getByRole('navigation').getByRole('button', { name: 'Welteditor', exact: true }).click()
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Welt exportieren', exact: true }).click()
  const download = await downloading
  expect(download.suggestedFilename()).toBe(`openworld-${world.id}.json`)
  await expect(page.getByRole('alert')).toHaveCount(0)
})
