import { useMemo } from 'react'
import { Background, Controls, MarkerType, ReactFlow, useNodesState } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Entity } from './types'

export function RelationshipGraph({ characters, relationships, edit }: {
  characters: Entity[]; relationships: Entity[]; edit: (relationship: Entity) => void
}) {
  const initial = useMemo(() => characters.map((character, i) => ({
    id: character.id, data: { label: character.name },
    position: { x: 260 + 230 * Math.cos(i * 2 * Math.PI / Math.max(1, characters.length)),
      y: 210 + 170 * Math.sin(i * 2 * Math.PI / Math.max(1, characters.length)) },
  })), [characters])
  return <section className="panel p-5">
    <h2>Beziehungsgraph</h2>
    <p className="muted text-sm mb-4">Pfeilrichtung: von → zu. Beziehung anklicken zum Bearbeiten.
      Knoten lassen sich für die Ansicht verschieben. Auch geheime Beziehungen sind hier sichtbar.</p>
    <Graph key={initial.map(node => node.id).join(',')} initial={initial}
      relationships={relationships} edit={edit} />
  </section>
}

function Graph({ initial, relationships, edit }: {
  initial: { id: string; data: { label: string | undefined }; position: { x: number; y: number } }[]
  relationships: Entity[]; edit: (relationship: Entity) => void
}) {
  const [nodes, , onNodesChange] = useNodesState(initial)
  const edges = relationships.filter(r => r.source_id && r.target_id).map(r => ({
    id: r.id, source: r.source_id!, target: r.target_id!,
    label: `${r.kind}${r.secret ? ' · geheim' : ''}`,
    type: 'default', markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: r.secret ? '#a975a0' : '#67936a', strokeWidth: 2 },
    labelStyle: { fill: '#243a29' }, interactionWidth: 24,
  }))
  return <div className="relationship-graph" aria-label="Gerichteter Beziehungsgraph">
    <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} fitView
      nodesConnectable={false} onEdgeClick={(_, edge) => {
        const relationship = relationships.find(r => r.id === edge.id)
        if (relationship) edit(relationship)
      }}>
      <Background /><Controls showInteractive={false} />
    </ReactFlow>
  </div>
}
