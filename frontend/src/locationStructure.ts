import type { Entity } from './types'

export const LOCATION_INDENT = 24
export type TreeLocation = { item: Entity; depth: number }
export type LocationProjection = { parentId: string | null; beforeId: string | null; depth: number }

export function siblings(locations: Entity[], parentId: string | null) {
  return locations.filter(item => (item.parent_id ?? null) === parentId)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
}

export function canMoveLocation(locations: Entity[], id: string, parentId: string | null) {
  const visited = new Set([id])
  while (parentId) {
    if (visited.has(parentId)) return false
    visited.add(parentId)
    const parent = locations.find(item => item.id === parentId)
    if (!parent) return false
    parentId = parent.parent_id ?? null
  }
  return true
}

export function flattenLocations(locations: Entity[], parentId: string | null = null, depth = 0): TreeLocation[] {
  return siblings(locations, parentId).flatMap(item => [
    { item, depth }, ...flattenLocations(locations, item.id, depth + 1),
  ])
}

export function projectLocationMove(
  locations: Entity[], id: string, targetId: string, after: boolean, horizontalOffset: number,
): LocationProjection | null {
  const flat = flattenLocations(locations)
  const moved = flat.find(row => row.item.id === id)
  if (!moved) return null
  const available = flat.filter(row => canMoveLocation(locations, id, row.item.id))
  const targetIndex = available.findIndex(row => row.item.id === targetId)
  if (targetIndex < 0) return null
  const index = targetIndex + (after ? 1 : 0)
  const previous = available[index - 1]
  const next = available[index]
  const desiredDepth = moved.depth + Math.round(horizontalOffset / LOCATION_INDENT)
  const depth = Math.max(next?.depth ?? 0, Math.min(desiredDepth, previous ? previous.depth + 1 : 0))
  const parent = depth === 0 ? null :
    available.slice(0, index).reverse().find(row => row.depth === depth - 1)?.item
  if (depth > 0 && !parent) return null
  const parentId = parent?.id ?? null
  const before = available.slice(index).find(row => (row.item.parent_id ?? null) === parentId)
  return { parentId, beforeId: before?.item.id ?? null, depth }
}

export function moveLocations(
  locations: Entity[], id: string, parentId: string | null, beforeId: string | null,
): Entity[] {
  const moved = locations.find(item => item.id === id)
  if (!moved) throw new Error('Der zu verschiebende Ort wurde nicht gefunden. Bitte neu laden.')
  if (!canMoveLocation(locations, id, parentId)) {
    throw new Error('Ein Ort kann nicht unter sich selbst oder seine Unterorte verschoben werden.')
  }
  if (beforeId === id && (moved.parent_id ?? null) === parentId) return locations
  const target = siblings(locations, parentId).filter(item => item.id !== id)
  const index = beforeId === null ? target.length : target.findIndex(item => item.id === beforeId)
  if (index < 0) throw new Error('Der Zielort wurde inzwischen verschoben. Bitte neu laden.')
  target.splice(index, 0, moved)
  const updated = locations.map(item => item.id === id ? { ...item, parent_id: parentId } : item)
  const orders = new Map<string, number>()
  for (const parent of new Set(updated.map(item => item.parent_id ?? null))) {
    const group = parent === parentId ? target : siblings(updated, parent)
    group.forEach((item, order) => orders.set(item.id, order))
  }
  return updated.map(item => ({ ...item, sort_order: orders.get(item.id) }))
}
