import { expect, test } from '@playwright/test'
import type { APIRequestContext, Locator, Page } from '@playwright/test'

type Location = {
  id: string; parent_id: string | null; sort_order: number; revision: number; name: string
  description: string; attributes: unknown[]; state: Record<string, unknown>
}
const backend = 'http://127.0.0.1:18000/api'

async function setup(page: Page, request: APIRequestContext, name: string) {
  const worldResponse = await request.post(`${backend}/worlds`, { data: { name } })
  expect(worldResponse.status()).toBe(201)
  const world: { id: string } = await worldResponse.json()
  const path = `${backend}/worlds/${world.id}`
  const create = async (name: string, parent_id: string | null = null): Promise<Location> => {
    const response = await request.post(`${path}/locations`, {
      data: { name, parent_id, description: `Beschreibung von ${name}`, state: { Wetter: 'Regen' } },
    })
    expect(response.status()).toBe(201)
    return response.json()
  }
  const forest = await create('Wald')
  const north = await create('Norden')
  const lake = await create('See')
  const cave = await create('Höhle', forest.id)
  await page.goto('/')
  await page.getByRole('button', { name: `${name} öffnen`, exact: true }).click()
  const row = (location: Location) => page.locator(`[data-location-id="${location.id}"] > .tree-row > .tree-item`)
  const read = async (): Promise<Location[]> => (await request.get(`${path}/locations`)).json()
  return { world, path, forest, north, lake, cave, row, read }
}

async function drag(source: Locator, target: Locator, fraction = 0.9, horizontalOffset = 0) {
  const box = await target.boundingBox()
  expect(box).not.toBeNull()
  if (!box) throw new Error('Drop-Ziel ist nicht sichtbar')
  await source.dragTo(target, {
    sourcePosition: { x: 32, y: 15 },
    targetPosition: { x: 32 + horizontalOffset, y: box.height * fraction },
  })
}

test('dragging reparents complete subtrees, supports world root and persists sibling order', async ({ page, request }) => {
  const e = await setup(page, request, 'Drag-and-drop-Test')
  await drag(e.row(e.forest), e.row(e.north), 0.9, 24)
  await expect.poll(async () => (await e.read()).find(item => item.id === e.forest.id)?.parent_id)
    .toBe(e.north.id)
  const moved = (await e.read()).find(item => item.id === e.forest.id)
  expect(moved?.description).toBe(e.forest.description)
  expect(moved?.state).toEqual(e.forest.state)
  expect((await e.read()).find(item => item.id === e.cave.id)?.parent_id).toBe(e.forest.id)
  await drag(e.row(e.forest), page.locator('.tree-root'))
  await expect.poll(async () => (await e.read()).find(item => item.id === e.forest.id)?.parent_id)
    .toBeNull()
  await drag(e.row(e.lake), e.row(e.north), 0.1)
  const rootOrder = async () => (await e.read()).filter(item => item.parent_id === null).map(item => item.id)
  await expect.poll(rootOrder).toEqual([e.lake.id, e.north.id, e.forest.id])
  await drag(e.row(e.lake), e.row(e.cave), 0.9)
  await expect.poll(rootOrder).toEqual([e.north.id, e.forest.id, e.lake.id])
  await page.reload()
  await page.getByRole('button', { name: 'Drag-and-drop-Test öffnen', exact: true }).click()
  await expect(page.locator('.location-tree > [data-location-id][data-depth="0"] > .tree-row > .tree-item'))
    .toHaveText(['NordenOrt', 'WaldOrt', 'SeeOrt'])
  await expect(page.locator('.error-banner')).toHaveCount(0)
})

test('horizontal drag shows the actual indented preview without arrow controls', async ({ page, request }) => {
  const e = await setup(page, request, 'Visuelle Ortsstruktur')
  await expect(page.locator('.tree-actions, .tree-action')).toHaveCount(0)
  await e.row(e.lake).dispatchEvent('dragstart', {
    clientX: 100, dataTransfer: await page.evaluateHandle(() => new DataTransfer()),
  })
  const target = await e.row(e.north).boundingBox()
  if (!target) throw new Error('Ziel fehlt')
  const hover = async (offset: number) => e.row(e.north).dispatchEvent('dragover', {
    clientX: 100 + offset, clientY: target.y + target.height * 0.9,
    dataTransfer: await page.evaluateHandle(() => new DataTransfer()),
  })
  await hover(24)
  await expect(page.locator(`[data-location-id="${e.lake.id}"]`)).toHaveAttribute('data-depth', '1')
  await expect(e.row(e.lake)).toHaveCSS('padding-left', '36px')
  await expect(page.locator(`[data-location-id="${e.lake.id}"]`)).toHaveClass(/drag-preview/)
  await hover(0)
  await expect(page.locator(`[data-location-id="${e.lake.id}"]`)).toHaveAttribute('data-depth', '0')
  await expect(e.row(e.lake)).toHaveCSS('padding-left', '12px')
  await e.row(e.lake).dispatchEvent('dragend')
  expect((await e.read()).find(item => item.id === e.lake.id)?.parent_id).toBeNull()
})

test('side editor survives dragging the open location and saves against its new parent and revision', async ({ page, request }) => {
  const e = await setup(page, request, 'Sicherer Ortseditor')
  await e.row(e.forest).click()
  await page.getByLabel('Beschreibung', { exact: true }).fill('Noch nicht gespeicherte Änderung')
  await expect(page.getByLabel('Übergeordneter Ort').locator('option', { hasText: 'Höhle' })).toHaveCount(0)
  await expect(e.row(e.forest)).toHaveAttribute('draggable', 'true')
  await expect(page.locator('.world-editor-layout > .editor')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Weltstruktur' })).toBeVisible()
  await drag(e.row(e.forest), e.row(e.north), 0.9, 24)
  await expect.poll(async () => (await e.read()).find(item => item.id === e.forest.id)?.parent_id)
    .toBe(e.north.id)
  await expect(page.getByLabel('Beschreibung', { exact: true })).toHaveValue('Noch nicht gespeicherte Änderung')
  await expect(page.getByLabel('Übergeordneter Ort')).toHaveValue(e.north.id)
  await drag(e.row(e.cave), e.row(e.forest), 0.9, -24)
  await expect.poll(async () => (await e.read()).find(item => item.id === e.cave.id)?.parent_id)
    .toBe(e.north.id)
  await expect(page.getByLabel('Beschreibung', { exact: true })).toHaveValue('Noch nicht gespeicherte Änderung')
  await page.getByRole('button', { name: 'Speichern', exact: true }).click()
  await expect.poll(async () => (await e.read()).find(item => item.id === e.forest.id)?.description)
    .toBe('Noch nicht gespeicherte Änderung')
  expect((await e.read()).find(item => item.id === e.forest.id)?.parent_id).toBe(e.north.id)
})

test('failed structural saves show an error without optimistic reordering', async ({ page, request }) => {
  const e = await setup(page, request, 'Strukturkonflikt')
  await page.route(`**/api/worlds/${e.world.id}/location-tree`, route => route.fulfill({
    status: 409, json: { detail: 'Weltstruktur wurde inzwischen geändert. Bitte neu laden.' },
  }))
  await drag(e.row(e.lake), e.row(e.forest), 0.1)
  await expect(page.getByRole('alert')).toContainText('Weltstruktur wurde inzwischen geändert')
  await expect(page.locator('.location-tree > [data-location-id][data-depth="0"] > .tree-row > .tree-item'))
    .toHaveText(['WaldOrt', 'NordenOrt', 'SeeOrt'])
  expect((await e.read()).find(item => item.id === e.forest.id)?.sort_order).toBe(0)
})
