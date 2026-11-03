import { Globe2, GripVertical, Map as MapIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import {
  canMoveLocation, flattenLocations, LOCATION_INDENT, moveLocations, projectLocationMove,
} from './locationStructure'
import type { LocationProjection } from './locationStructure'
import type { Entity } from './types'

export function LocationTree({
  locations, selectedId, onSelect, onMove, worldName, onWorldSelect, disabled = false,
}: {
  locations: Entity[]; selectedId?: string; onSelect: (item: Entity) => void
  onMove?: (id: string, parentId: string | null, beforeId: string | null) => Promise<void>
  worldName?: string; onWorldSelect?: () => void; disabled?: boolean
}) {
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [projection, setProjection] = useState<LocationProjection | null>(null)
  const [dropping, setDropping] = useState(false)
  const originX = useRef(0)
  const pendingDrop = useRef(false)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  const focusAfterMove = useRef<string | null>(null)
  const editable = !!onMove && !disabled && !dropping
  const rows = flattenLocations(locations)
  const dragged = locations.find(item => item.id === draggedId)
  const previewRows = dragged && projection ?
    flattenLocations(moveLocations(locations, dragged.id, projection.parentId, projection.beforeId)) : rows
  const positions = new Map(previewRows.map((row, index) => [row.item.id, { index, depth: row.depth }]))
  useEffect(() => {
    if (!disabled && !dropping && focusAfterMove.current) {
      buttons.current.get(focusAfterMove.current)?.focus()
      focusAfterMove.current = null
    }
  }, [disabled, dropping, locations])

  function resetDrag() {
    setDraggedId(null); setProjection(null)
  }
  function dragOver(event: DragEvent<HTMLDivElement>) {
    if (!editable || !draggedId) return
    event.preventDefault()
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-location-id]') : null
    if (!target) return
    const header = target.querySelector<HTMLButtonElement>('.tree-item')
    if (!header || !target.dataset.locationId) return
    const rect = header.getBoundingClientRect()
    const next = projectLocationMove(
      locations, draggedId, target.dataset.locationId,
      event.clientY >= rect.top + rect.height / 2, event.clientX - originX.current,
    )
    // Keep the preview stable when the moved subtree arrives under the pointer.
    if (next) setProjection(next)
    event.dataTransfer.dropEffect = next || projection ? 'move' : 'none'
  }
  async function drop(event: DragEvent) {
    event.preventDefault()
    if (!editable || !draggedId || !projection || !onMove) { resetDrag(); return }
    pendingDrop.current = true; setDropping(true)
    focusAfterMove.current = draggedId
    try { await onMove(draggedId, projection.parentId, projection.beforeId) }
    finally {
      pendingDrop.current = false; setDropping(false); resetDrag()
    }
  }
  return <div className="location-tree" aria-label="Ortsstruktur"
    onDragOver={dragOver} onDrop={event => { void drop(event) }}>
    {worldName && <div className="tree-root-row">
      <button className="list-item tree-root" type="button" disabled={disabled} onClick={onWorldSelect}
        onDragOver={event => {
          if (!editable || !draggedId) return
          event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'move'
          setProjection({ parentId: null, beforeId: null, depth: 0 })
        }}>
        <Globe2 size={17} />{worldName}</button>
    </div>}
    {rows.map(({ item, depth }) => {
      const position = positions.get(item.id)
      const preview = !!draggedId && !canMoveLocation(locations, draggedId, item.id)
      return <div key={item.id} data-location-id={item.id} data-depth={position?.depth ?? depth}
        className={preview ? 'tree-entry drag-preview' : 'tree-entry'} style={{ order: position?.index }}>
        <div className="tree-row">
          <button className={`tree-item ${item.id === selectedId ? 'selected' : ''}`}
            ref={button => {
              if (button) buttons.current.set(item.id, button)
              else buttons.current.delete(item.id)
            }}
            style={{ paddingLeft: `${12 + (position?.depth ?? depth) * LOCATION_INDENT}px` }}
            type="button" disabled={disabled} draggable={editable}
            aria-label={`${item.name} ${item.kind}`} aria-expanded={selectedId === item.id}
            onClick={() => onSelect(item)}
            onDragStart={event => {
              event.dataTransfer.setData('application/x-openworld-location', item.id)
              event.dataTransfer.effectAllowed = 'move'
              originX.current = event.clientX
              setDraggedId(item.id); setProjection(null)
            }}
            onDragEnd={() => { if (!pendingDrop.current) resetDrag() }}>
            {onMove && <GripVertical size={13} aria-hidden="true" />}
            <MapIcon size={15} /><span>{item.name}<small>{item.kind}</small></span>
          </button>
        </div>
      </div>
    })}
    {dragged && projection && <span className="sr-only" role="status">
      {dragged.name}: {projection.parentId ?
        `unter ${locations.find(item => item.id === projection.parentId)?.name}` : 'oberste Ebene'}
    </span>}
  </div>
}
