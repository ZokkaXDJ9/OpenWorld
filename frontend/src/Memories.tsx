import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errorText } from './api'
import { statusLabels } from './Events'
import type { Entity, KnowledgeKind, WorldEvent } from './types'
import { Field } from './ui'

const kinds: Record<string, string> = {
  memory: 'Erinnerung', knowledge: 'Persönliches Wissen', belief: 'Überzeugung',
  suspicion: 'Vermutung', rumor: 'Gerücht', secret: 'Geheimnis', received: 'Erhaltene Information',
}
type Memory = Entity & { links: { source_id: string; target_id: string; relation: string }[] }

export function Memories({ worldId, characterId, report }: {
  worldId: string; characterId: string; report: (error: string) => void
}) {
  const client = useQueryClient()
  const [history, setHistory] = useState(false)
  const [editing, setEditing] = useState<Memory | null>(null)
  const [adding, setAdding] = useState(false)
  const [content, setContent] = useState('')
  const [source, setSource] = useState('Editor')
  const [kind, setKind] = useState<KnowledgeKind>('memory')
  const [confidence, setConfidence] = useState(100)
  const [occurredAt, setOccurredAt] = useState('')
  const [busy, setBusy] = useState(false)
  const memories = useQuery({ queryKey: ['memories', worldId, characterId],
    queryFn: () => api<Memory[]>(`/worlds/${worldId}/characters/${characterId}/memories`) })
  async function change(archive?: Memory) {
    setBusy(true); report('')
    try {
      const event = await api<WorldEvent>(`/worlds/${worldId}/events`, 'POST', {
        event_type: archive ? 'memory_archived' : editing ? 'belief_corrected' : 'personal_memory',
        description: archive ? 'Persönliche Erinnerung entfernt' :
          editing ? 'Persönlichen Wissensstand korrigiert' : 'Persönliche Erinnerung hinzugefügt',
        participant_ids: [characterId], confidence: 100,
        occurred_at: occurredAt && !archive ? new Date(occurredAt).toISOString() : null,
        operations: archive ? [{ op: 'archive', entity_id: archive.id, revision: archive.revision }] : [{
          op: 'knowledge', character_id: characterId, kind, content, source, confidence,
          supersedes: editing ? [editing.id] : [],
        }],
      })
      if (event.status === 'proposed') {
        await api(`/worlds/${worldId}/events/${event.id}/approve`, 'POST', { revision: event.revision })
      } else if (event.status !== 'applied') {
        throw new Error('Die Änderung ist geschützt. Der Vorschlag bleibt unter Ereignisse sichtbar.')
      }
      setAdding(false); setEditing(null); setContent('')
      await Promise.all(['memories', 'entities', 'events'].map(key =>
        client.invalidateQueries({ queryKey: [key] })))
    } catch (error) {
      report(`${errorText(error)} Ein eventuell angelegter Vorschlag ist unter Ereignisse sichtbar.`)
    } finally { setBusy(false) }
  }
  return <section className="space-y-4 mt-5" onKeyDown={e => {
    if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault()
  }}>
    <p className="muted text-sm">Nur der persönliche Wissensstand dieses Charakters.
      Korrekturen erhalten die alte Überzeugung und ihre Herkunft im Verlauf.</p>
    {memories.error && <p role="alert">{errorText(memories.error)}</p>}
    {memories.isPending && <p role="status">Erinnerungen werden geladen ...</p>}
    <div className="flex flex-wrap gap-3">
      <button type="button" className="button" disabled={busy} onClick={() => {
        setAdding(true); setEditing(null); setContent(''); setSource('Editor')
        setKind('memory'); setConfidence(100); setOccurredAt('')
      }}>Erinnerung hinzufügen</button>
      <label className="checkbox"><input type="checkbox" checked={history}
        onChange={e => setHistory(e.target.checked)} /> Verlauf anzeigen</label>
    </div>
    {(adding || editing) && <div className="notice space-y-3">
      <Field label="Art der Erinnerung"><select value={kind} onChange={e => setKind(e.target.value as KnowledgeKind)}>
        {Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      <Field label="Erinnerungsinhalt"><textarea rows={4} value={content}
        onChange={e => setContent(e.target.value)} /></Field>
      <Field label="Informationsquelle"><input value={source} maxLength={200}
        onChange={e => setSource(e.target.value)} /></Field>
      <Field label="Vertrauen in die Erinnerung (%)"><input type="number" min={0} max={100}
        value={confidence} onChange={e => setConfidence(Number(e.target.value))} /></Field>
      <Field label="Zeitpunkt des Erlebnisses (optional)"><input type="datetime-local" value={occurredAt}
        onChange={e => setOccurredAt(e.target.value)} /></Field>
      <div className="flex gap-2"><button type="button" className="button primary" disabled={busy || !content.trim()}
        onClick={() => { void change() }}>Erinnerung speichern</button>
        <button type="button" className="button" disabled={busy} onClick={() => {
          setAdding(false); setEditing(null)
        }}>Abbrechen</button></div>
    </div>}
    {memories.data?.filter(memory => history || memory.status === 'active').map(memory =>
      <article key={memory.id} className="notice space-y-2">
        <div className="flex flex-wrap gap-2"><span className="tag">{kinds[memory.kind ?? 'memory']}</span>
          <span className="muted">{statusLabels[memory.status ?? 'active']}</span></div>
        <p className="whitespace-pre-wrap">{memory.content}</p>
        <p className="muted text-xs">Quelle: {memory.source} · Vertrauen: {memory.confidence} %
          {memory.occurred_at && ` · Erlebt: ${new Date(memory.occurred_at).toLocaleString('de-DE')}`}
          {memory.origin === 'legacy' && ' · Historischer Eintrag aus Phase 1, nicht nachträglich verifiziert'}</p>
        {!!memory.links.length && <p className="muted text-xs">Mit {memory.links.length} früheren/weiteren
          Wissenseinträgen verknüpft ({memory.links.some(link => link.relation === 'contradicts') ?
            'Widerspruch' : 'Korrektur'}).</p>}
        {memory.status === 'active' && <div className="flex gap-2">
          <button type="button" className="button small" disabled={busy} onClick={() => {
            setEditing(memory); setAdding(false); setContent(memory.content ?? '')
            setSource(memory.source ?? 'Editor'); setConfidence(memory.confidence ?? 100)
            setKind((memory.kind ?? 'memory') as KnowledgeKind); setOccurredAt('')
          }}>Korrigieren</button>
          <button type="button" className="button small" disabled={busy}
            onClick={() => { void change(memory) }}>Erinnerung entfernen</button>
        </div>}
      </article>)}
    {memories.data?.length === 0 && <p className="muted">Keine persönlichen Erinnerungen vorhanden.</p>}
  </section>
}
