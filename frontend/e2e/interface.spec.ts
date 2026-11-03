import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

async function expectUtilityInterface(page: Page) {
  await expect(page).toHaveTitle('OpenWorld')
  await expect(page.locator('.hero, .hero-art, .footer')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(
    /CREATE\. CONNECT|CREATE WORLDS|GRENZENLOS|Lebendige Welten|Deine Ideen im Mittelpunkt|Deine Welten gehoeren dir|Dein Modell\. Deine Wahl|Eine Unterhaltung beginnt mit dir|Geschichten lebendig|Vorstellungskraft/,
  )
}

test('worlds, editors and chat use functional labels without promotional sections', async ({ page }) => {
  await page.route('**/api/worlds', route => route.fulfill({
    json: [{ id: 'ui-world', revision: 1, name: 'Testwelt', description: '', attributes: [], state: {} }],
  }))
  await page.route('**/api/worlds/ui-world/*', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expectUtilityInterface(page)
  await expect(page.getByText('Keine Beschreibung.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Testwelt öffnen' }).click()
  await expectUtilityInterface(page)
  for (const [navigation, emptyTitle] of [
    ['Charaktere', 'Keine Charaktere vorhanden'],
    ['Beziehungen', 'Keine Beziehungen vorhanden'],
    ['Wissen & Erinnerungen', 'Keine Wissenseinträge vorhanden'],
    ['Chats', 'Kein Gespräch ausgewählt'],
  ] as const) {
    await page.getByRole('navigation').getByRole('button', { name: navigation, exact: true }).click()
    await expect(page.getByRole('heading', { name: emptyTitle })).toBeVisible()
    await expectUtilityInterface(page)
  }
  await page.getByRole('navigation').getByRole('button', { name: 'Einstellungen' }).click()
  await expect(page.getByRole('heading', { name: 'KI-Verbindung' })).toBeVisible()
  await expectUtilityInterface(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Meine Welten' }).click()
  await page.getByRole('button', { name: 'Neue Welt', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Neue Welt', exact: true })).toBeVisible()
  await expect(page.getByLabel('Name', { exact: true })).not.toHaveAttribute('placeholder')
  await expect(page.getByLabel('Öffentliche Weltbeschreibung')).not.toHaveAttribute('placeholder')
  await expectUtilityInterface(page)
  await page.route('**/api/worlds', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByText('Über „Neue Welt“ eine Welt anlegen.', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('Ueber')
})

test('German profile labels preserve existing field keys and values', async ({ page, request }) => {
  const worldResponse = await request.post('http://127.0.0.1:18000/api/worlds', {
    data: { name: 'Umlauttest' },
  })
  expect(worldResponse.status()).toBe(201)
  const world: { id: string } = await worldResponse.json()
  const originalProfile = { Persoenlichkeit: 'Ruhig', Faehigkeiten: 'Späher', Aengste: 'Höhen' }
  const characterResponse = await request.post(
    `http://127.0.0.1:18000/api/worlds/${world.id}/characters`,
    { data: { name: 'Änne', profile: originalProfile } },
  )
  expect(characterResponse.status()).toBe(201)
  const character: { id: string } = await characterResponse.json()
  await page.goto('/')
  await page.getByRole('button', { name: 'Umlauttest öffnen' }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Charaktere', exact: true }).click()
  await page.getByRole('button', { name: 'Profil bearbeiten' }).click()
  await page.getByRole('tab', { name: 'Persönlichkeit & Hintergrund' }).click()
  await expect(page.getByLabel('Persönlichkeit', { exact: true })).toHaveValue('Ruhig')
  await expect(page.getByLabel('Fähigkeiten', { exact: true })).toHaveValue('Späher')
  await expect(page.getByLabel('Ängste', { exact: true })).toHaveValue('Höhen')
  await expect(page.locator('body')).not.toContainText(/Persoenlichkeit|Faehigkeiten|Aengste/)
  await page.getByLabel('Persönlichkeit', { exact: true }).fill('Fröhlich')
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Schließen' })).toHaveCount(0)
  const characters: { id: string; profile: Record<string, string> }[] =
    await (await request.get(`http://127.0.0.1:18000/api/worlds/${world.id}/characters`)).json()
  expect(characters.find(item => item.id === character.id)?.profile).toEqual({
    ...originalProfile, Persoenlichkeit: 'Fröhlich',
  })
})
