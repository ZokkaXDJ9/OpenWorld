import { expect, test } from '@playwright/test'

test('events: proposal editing, confirmation, undo and individual memory history', async ({ page, request }) => {
  const base = 'http://127.0.0.1:18000/api'
  const world = await (await request.post(`${base}/worlds`, { data: { name: 'Ereignistest' } })).json()
  const path = `${base}/worlds/${world.id}`
  const lumia = await (await request.post(`${path}/characters`, { data: { name: 'Lumia' } })).json()
  const power = await (await request.post(`${path}/characters`, { data: { name: 'Power' } })).json()
  const relationship = await (await request.post(`${path}/relationships`, { data: {
    source_id: lumia.id, target_id: power.id,
    attributes: [{ name: 'Vertrauen', type: 'number', value: 45, minimum: 0, maximum: 100 }],
  } })).json()
  const proposal = await request.post(`${path}/events`, { data: {
    event_type: 'trust_changed', description: 'Lumia vertraut Power mehr', confidence: 90,
    participant_ids: [lumia.id, power.id],
    operations: [{ op: 'relationship', entity_id: relationship.id, revision: 1,
      attributes: [{ ...relationship.attributes[0], value: 60 }] }],
  } })
  expect(proposal.status()).toBe(201)
  await page.goto('/')
  await page.getByRole('button', { name: 'Ereignistest öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Ereignisse', exact: true }).click()
  await page.locator('.event-item').filter({ hasText: 'Lumia vertraut Power mehr' }).click()
  const details = page.getByRole('article', { name: 'Ereignisdetails' })
  await expect(details).toContainText('noch keine bestätigte Weltveränderung')
  await expect(details).toContainText('value: 45')
  await expect(details).toContainText('value: 60')
  await details.getByRole('button', { name: 'Bearbeiten', exact: true }).click()
  await page.getByLabel('Neuer Wert: Vertrauen').fill('55')
  await page.getByRole('button', { name: 'Vorschlag speichern' }).click()
  await expect(details).toContainText('value: 55')
  await details.getByRole('button', { name: 'Übernehmen', exact: true }).click()
  await expect(details.getByRole('button', { name: 'Rückgängig machen' })).toBeVisible()
  expect((await (await request.get(`${path}/relationships`)).json())[0].attributes[0].value).toBe(55)
  await details.getByRole('button', { name: 'Rückgängig machen' }).click()
  await expect(details).toContainText('Zurückgenommene Änderung')
  expect((await (await request.get(`${path}/relationships`)).json())[0].attributes[0].value).toBe(45)
  await page.getByLabel('Status', { exact: true }).selectOption('proposed')
  await expect(page.getByRole('heading', { name: 'Keine Ereignisse', exact: true })).toBeVisible()
  await page.getByLabel('Status', { exact: true }).selectOption('undone')
  await expect(page.locator('.event-item')).toHaveCount(1)

  await page.getByRole('navigation').getByRole('button', { name: 'Charaktere', exact: true }).click()
  await page.locator('.character-card').filter({ hasText: 'Lumia' })
    .getByRole('button', { name: 'Profil bearbeiten' }).click()
  await page.getByRole('tab', { name: 'Erinnerungen', exact: true }).click()
  await page.getByRole('button', { name: 'Erinnerung hinzufügen' }).click()
  await page.getByLabel('Art der Erinnerung').selectOption('belief')
  await page.getByLabel('Erinnerungsinhalt').fill('Power ist tot.')
  await page.getByLabel('Informationsquelle').fill('Bericht des Orakels')
  await page.getByRole('button', { name: 'Erinnerung speichern' }).click()
  const old = page.getByRole('article').filter({ hasText: 'Power ist tot.' })
  await expect(old).toContainText('Bericht des Orakels')
  await old.getByRole('button', { name: 'Korrigieren' }).click()
  await page.getByLabel('Erinnerungsinhalt').fill('Power lebt. Lumia hat ihn selbst gesehen.')
  await page.getByLabel('Informationsquelle').fill('Eigene Beobachtung')
  await page.getByRole('button', { name: 'Erinnerung speichern' }).click()
  await expect(old).toHaveCount(0)
  await page.getByLabel('Verlauf anzeigen').check()
  await expect(old).toContainText('Überholt')
  const current = page.getByRole('article').filter({ hasText: 'Power lebt.' })
  await expect(current).toContainText('Eigene Beobachtung')
  await current.getByRole('button', { name: 'Erinnerung entfernen' }).click()
  await expect(current).toContainText('Entfernt')
  const powerMemories = await (await request.get(`${path}/characters/${power.id}/memories`)).json()
  expect(powerMemories).toEqual([])
  await expect(page.getByRole('alert')).toHaveCount(0)
})
