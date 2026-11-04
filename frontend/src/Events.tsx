import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errorText } from './api'
import type { Entity, EventOperation, EventRule, EventSettings, ExtractionJob, WorldEvent } from './types'
import { Empty, Field } from './ui'

export const statusLabels: Record<string, string> = {
  proposed: 'Vorschlag', applied: 'Übernommen', protected: 'Geschützt', rejected: 'Abgelehnt',
  undone: 'Zurückgenommen', invalidated: 'Quelle geändert', recorded: 'Protokolliert',
  active: 'Aktuell', superseded: 'Überholt', revoked: 'Zurückgenommen', archived: 'Entfernt',
  pending: 'Wartet', running: 'Wird verarbeitet', failed: 'Fehlgeschlagen', complete: 'Abgeschlossen',
}
const modeLabels = { auto: 'Automatisch', confirm: 'Bestätigung', protected: 'Geschützt' }
const classes = { '*': 'Alle Objektklassen', knowledge: 'Wissen', character: 'Charakter',
  relationship: 'Beziehung', location: 'Ort', world: 'Welt' }

function human(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.map(human).join(', ')
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}: ${human(item)}`).join(' · ')
  }
  return String(value)
}

export function EventOptions({ worldId, report }: { worldId: string; report: (error: string) => void }) {
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [eventType, setEventType] = useState('*')
  const [objectClass, setObjectClass] = useState('*')
  const [mode, setMode] = useState<EventRule['mode']>('confirm')
  const settings = useQuery({ queryKey: ['event-settings', worldId],
    queryFn: () => api<EventSettings>(`/worlds/${worldId}/event-settings`) })
  const rules = useQuery({ queryKey: ['event-rules', worldId],
    queryFn: () => api<EventRule[]>(`/worlds/${worldId}/event-rules`) })
  async function saveRule() {
    setBusy(true); report('')
    try {
      const current = rules.data?.find(r => r.event_type === eventType && r.object_class === objectClass)
      await api(`/worlds/${worldId}/event-rules`, 'PUT', {
        event_type: eventType, object_class: objectClass, mode,
        ...(current ? { revision: current.revision } : {}),
      })
      await client.invalidateQueries({ queryKey: ['event-rules', worldId] })
    } catch (error) { report(errorText(error)) }
    finally { setBusy(false) }
  }
  return <details className="panel"><summary>Ereigniserkennung und Freigaben</summary>
    {(settings.error || rules.error) && <p role="alert">{errorText(settings.error ?? rules.error)}</p>}
    <label className="checkbox my-4"><input type="checkbox" checked={settings.data?.enabled ?? false}
      disabled={!settings.data || busy} onChange={async e => {
        if (!settings.data) return
        const previous = settings.data
        const enabled = e.target.checked
        client.setQueryData(['event-settings', worldId], { ...previous, enabled })
        setBusy(true)
        try {
          const result = await api<EventSettings>(`/worlds/${worldId}/event-settings`, 'PUT',
            { enabled, revision: previous.revision })
          client.setQueryData(['event-settings', worldId], result)
        } catch (error) {
          client.setQueryData(['event-settings', worldId], previous)
          report(errorText(error))
          await client.invalidateQueries({ queryKey: ['event-settings', worldId] })
        }
        finally { setBusy(false) }
      }} /> Ereignisse nach Gesprächen erkennen</label>
    <p className="muted text-sm mb-4">Verwendet den konfigurierten Anbieter für zusätzliche Anfragen.
      Bei Cloud-Anbietern können Kosten entstehen. Ausgeschaltet bleibt der Chat unverändert nutzbar.</p>
    <p className="muted text-sm mb-4">Standard: persönliche Informationen automatisch, Beziehungen und
      wichtige Zustände nach Bestätigung. Objektive Weltfakten und Orts-/Weltzustände bleiben geschützt.</p>
    <div className="event-filters">
      <Field label="Ereignistyp der Regel"><input value={eventType} maxLength={100}
        onChange={e => setEventType(e.target.value)} placeholder="* oder z. B. trust_changed" /></Field>
      <Field label="Objektklasse"><select value={objectClass} onChange={e => setObjectClass(e.target.value)}>
        {Object.entries(classes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></Field>
      <Field label="Freigabe"><select value={mode} onChange={e => setMode(e.target.value as EventRule['mode'])}>
        {Object.entries(modeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></Field>
      <button type="button" className="button" disabled={busy || !eventType.trim()}
        onClick={() => { void saveRule() }}>Regel speichern</button>
    </div>
    <ul className="my-4 space-y-2">{rules.data?.map(rule => <li key={rule.id}>
      <button type="button" className="button subtle" onClick={() => {
        setEventType(rule.event_type); setObjectClass(rule.object_class); setMode(rule.mode)
      }}>{rule.event_type} · {classes[rule.object_class as keyof typeof classes]} · {modeLabels[rule.mode]}</button>
    </li>)}</ul>
  </details>
}

function ProposalEditor({ event, worldId, locations, saved, report }: {
  event: WorldEvent; worldId: string; locations: Entity[]
  saved: () => Promise<void>; report: (error: string) => void
}) {
  const [description, setDescription] = useState(event.description)
  const [operations, setOperations] = useState(event.proposal.operations)
  const [busy, setBusy] = useState(false)
  function patch(index: number, operation: EventOperation) {
    setOperations(current => current.map((item, i) => i === index ? operation : item))
  }
  return <div className="space-y-4 my-4">
    <Field label="Beschreibung des Vorschlags"><textarea value={description}
      onChange={e => setDescription(e.target.value)} /></Field>
    {operations.map((operation, index) => <div key={index} className="space-y-3">
      {operation.op === 'knowledge' && <>
        <Field label="Vorgeschlagener Inhalt"><textarea value={operation.content}
          onChange={e => patch(index, { ...operation, content: e.target.value })} /></Field>
        <Field label="Vertrauen in die Information (%)"><input type="number" min={0} max={operation.kind === 'received' ? 50 : 100}
          value={operation.confidence} onChange={e => patch(index, { ...operation, confidence: Number(e.target.value) })} /></Field>
      </>}
      {operation.op === 'relationship' && operation.attributes.map((attribute, attributeIndex) =>
        <Field key={attribute.name} label={`Neuer Wert: ${attribute.name}`}><input
          type={attribute.type === 'number' ? 'number' : 'text'} value={human(attribute.value)}
          min={attribute.minimum ?? undefined} max={attribute.maximum ?? undefined}
          onChange={e => patch(index, { ...operation, attributes: operation.attributes.map((item, i) =>
            i === attributeIndex ? { ...item, value: attribute.type === 'number' ? Number(e.target.value) : e.target.value } : item) })} /></Field>)}
      {operation.op === 'state' && Object.entries(operation.values).map(([key, value]) =>
        <Field key={key} label={`Neuer Zustand: ${key}`}><input value={human(value)}
          type={typeof value === 'number' ? 'number' : 'text'} onChange={e => patch(index, {
            ...operation, values: { ...operation.values, [key]:
              typeof value === 'number' ? Number(e.target.value) :
                typeof value === 'boolean' ? e.target.value === 'true' :
                  Array.isArray(value) ? e.target.value.split(',').map(s => s.trim()) : e.target.value },
          })} /></Field>)}
      {operation.op === 'location' && <Field label="Vorgeschlagener Aufenthaltsort"><select
        value={operation.location_id ?? ''} onChange={e => patch(index, {
          ...operation, location_id: e.target.value || null, destination_id: null,
          travel_status: e.target.value ? 'present' : 'unknown',
        })}><option value="">Unbekannt</option>{locations.map(location =>
          <option key={location.id} value={location.id}>{location.name}</option>)}</select></Field>}
      {operation.op === 'archive' && <p>Erinnerung aus dem aktuellen Wissensstand entfernen.</p>}
    </div>)}
    <button type="button" className="button" disabled={busy || !description.trim()} onClick={async () => {
      setBusy(true)
      try {
        await api(`/worlds/${worldId}/events/${event.id}?revision=${event.revision}`, 'PUT', {
          event_type: event.event_type, description, occurred_at: event.occurred_at,
          participant_ids: event.participants, location_id: event.location_id,
          confidence: event.confidence, operations,
        })
        await saved()
      } catch (error) { report(errorText(error)) }
      finally { setBusy(false) }
    }}>Vorschlag speichern</button>
  </div>
}

export function Events({ worldId, characters, locations, report }: {
  worldId: string; characters: Entity[]; locations: Entity[]; report: (error: string) => void
}) {
  const client = useQueryClient()
  const [filters, setFilters] = useState({ status: '', character_id: '', location_id: '', event_type: '',
    from_time: '', until_time: '' })
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const params = new URLSearchParams({ limit: '50', offset: String(page * 50) })
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, key.endsWith('_time') ? new Date(value).toISOString() : value)
  })
  const events = useQuery({ queryKey: ['events', worldId, params.toString()],
    queryFn: () => api<WorldEvent[]>(`/worlds/${worldId}/events?${params}`), refetchInterval: 3000 })
  const jobs = useQuery({ queryKey: ['extraction-jobs', worldId],
    queryFn: () => api<ExtractionJob[]>(`/worlds/${worldId}/extraction-jobs`), refetchInterval: 3000 })
  const selected = events.data?.find(event => event.id === selectedId)
  async function refresh() {
    setEditing(false)
    await Promise.all(['events', 'entities', 'memories', 'extraction-jobs'].map(key =>
      client.invalidateQueries({ queryKey: [key] })))
  }
  async function action(event: WorldEvent, action: string) {
    setBusy(true); report('')
    try {
      await api(`/worlds/${worldId}/events/${event.id}/${action}`, 'POST', { revision: event.revision })
      await refresh()
    } catch (error) { report(errorText(error)) }
    finally { setBusy(false) }
  }
  return <div className="space-y-5">
    <EventOptions worldId={worldId} report={report} />
    <section className="panel p-5 event-filters">
      <Field label="Status"><select value={filters.status} onChange={e => {
        setFilters({ ...filters, status: e.target.value }); setPage(0)
      }}><option value="">Alle</option>{['proposed', 'applied', 'protected', 'rejected', 'undone', 'invalidated', 'recorded']
        .map(status => <option key={status} value={status}>{statusLabels[status]}</option>)}</select></Field>
      <Field label="Beteiligter Charakter"><select value={filters.character_id} onChange={e => {
        setFilters({ ...filters, character_id: e.target.value }); setPage(0)
      }}><option value="">Alle</option>{characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <Field label="Ereignisort"><select value={filters.location_id} onChange={e => {
        setFilters({ ...filters, location_id: e.target.value }); setPage(0)
      }}><option value="">Alle</option>{locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
      <Field label="Ereignistyp"><input value={filters.event_type} onChange={e => {
        setFilters({ ...filters, event_type: e.target.value }); setPage(0)
      }} /></Field>
      {(['from_time', 'until_time'] as const).map(key => <Field key={key}
        label={key === 'from_time' ? 'Ereigniszeit ab' : 'Ereigniszeit bis'}><input type="datetime-local"
        value={filters[key]} onChange={e => { setFilters({ ...filters, [key]: e.target.value }); setPage(0) }} /></Field>)}
    </section>
    {(events.error || jobs.error) && <p role="alert">{errorText(events.error ?? jobs.error)}</p>}
    {jobs.data?.filter(job => job.status === 'failed').map(job => <div className="error-banner" key={job.id}>
      <span>Erkennung fehlgeschlagen: {job.error}</span>
      <button type="button" className="button small" disabled={busy || job.attempts >= 3} onClick={async () => {
        setBusy(true)
        try { await api(`/worlds/${worldId}/extraction-jobs/${job.id}/retry`, 'POST'); await refresh() }
        catch (error) { report(errorText(error)) }
        finally { setBusy(false) }
      }}>Erneut versuchen</button>
    </div>)}
    {events.isPending && <p role="status">Ereignisse werden geladen ...</p>}
    <div className="event-layout">
      <section className="space-y-3">{events.data?.map(event => <button type="button" key={event.id}
        className={`panel event-item ${selectedId === event.id ? 'selected' : ''}`}
        onClick={() => { setSelectedId(event.id); setEditing(false) }}>
        <span className="tag">{statusLabels[event.status]}</span><strong>{event.description}</strong>
        <small>{new Date(event.occurred_at).toLocaleString('de-DE')} · {event.event_type}</small>
      </button>)}
      {events.data?.length === 0 && <Empty title="Keine Ereignisse"
        text="Noch keine passenden Ereignisse. Die Erkennung kann oben bewusst aktiviert werden." />}
      <div className="flex gap-2">
        <button type="button" className="button" disabled={!page} onClick={() => setPage(page - 1)}>Zurück</button>
        <button type="button" className="button" disabled={(events.data?.length ?? 0) < 50}
          onClick={() => setPage(page + 1)}>Weitere Ereignisse</button>
      </div></section>
      {selected && <article className="panel p-5 space-y-4" aria-label="Ereignisdetails">
        <h2>{selected.description}</h2><p>{statusLabels[selected.status]} · {modeLabels[selected.proposal.mode]}</p>
        <p className="muted text-sm">Ereignis: {new Date(selected.occurred_at).toLocaleString('de-DE')}<br />
          Gespeichert: {new Date(selected.created_at).toLocaleString('de-DE')}</p>
        <p>{selected.participants.map(id => characters.find(c => c.id === id)?.name ?? 'Entfernter Charakter').join(', ')}</p>
        {selected.sources.map((source, i) => <blockquote key={i} className="notice">
          Quelle: {source.speaker_character_id ?
            `Aussage von ${characters.find(c => c.id === source.speaker_character_id)?.name ?? 'entferntem Charakter'}` :
            source.role === 'user' ? 'Benutzeraussage' : 'Charakteraussage'}<br />{source.quote}
          {!source.message_id && <small> · Ursprüngliche Nachricht entfernt</small>}
        </blockquote>)}
        {!selected.sources.length && <p className="muted">Quelle: manueller Eintrag</p>}
        {selected.status === 'proposed' && <p className="notice">Dies ist ein Vorschlag, noch keine bestätigte Weltveränderung.</p>}
        {selected.status === 'protected' && <p className="notice">Geschützt. Nur bewusst im jeweiligen Editor ändern.</p>}
        {['proposed', 'protected'].includes(selected.status) && selected.proposal.preview.map((change, index) =>
          <div className="notice" key={index}><strong>Vorgeschlagene Änderung</strong>
            <p>Vorher: {Object.keys(change.before).length ? human(change.before) : 'Noch kein Eintrag'}</p>
            <p>Nachher: {human(change.after)}</p>
          </div>)}
        <div className="space-y-3">{selected.proposal.operations.map((operation, index) =>
          <div className="notice" key={index}>
            {operation.op === 'knowledge' ? <>
              <strong>{operation.kind === 'received' ? 'Erhaltene Information' : 'Persönlicher Wissenseintrag'}</strong>
              <p>{operation.content}</p><small>Vertrauen: {operation.confidence} % ·
                {operation.supersedes?.length ? ' Korrigiert frühere Überzeugung' : ' Individuelle Sicht, kein Weltfakt'}</small>
            </> : operation.op === 'relationship' ?
              operation.attributes.map(a => <p key={a.name}>{a.name}: neuer Wert {human(a.value)}</p>) :
              operation.op === 'state' ? <p>Zustand: {human(operation.values)}</p> :
                operation.op === 'archive' ? <p>Erinnerung entfernen</p> :
                  <p>Aufenthaltsort: {locations.find(l => l.id === operation.location_id)?.name ?? 'Unbekannt'}</p>}
          </div>)}</div>
        {selected.mutations.map(mutation => <div key={mutation.id} className="notice">
          <strong>{mutation.reverted ? 'Zurückgenommene Änderung' : 'Angewendete Änderung'}</strong>
          <p>Vorher: {Object.keys(mutation.before).length ? human(mutation.before) : 'Noch kein Eintrag'}</p>
          <p>Nachher: {human(mutation.after)}</p>
        </div>)}
        <div className="flex flex-wrap gap-2">
          {selected.status === 'proposed' && <button type="button" className="button primary"
            disabled={busy} onClick={() => { void action(selected, 'approve') }}>Übernehmen</button>}
          {['proposed', 'protected'].includes(selected.status) && <>
            <button type="button" className="button" disabled={busy}
              onClick={() => { void action(selected, 'reject') }}>Ablehnen</button>
            <button type="button" className="button" disabled={busy}
              onClick={() => setEditing(!editing)}>Bearbeiten</button>
          </>}
          {selected.status === 'applied' && <button type="button" className="button" disabled={busy}
            onClick={() => { void action(selected, 'undo') }}>Rückgängig machen</button>}
        </div>
        {editing && <ProposalEditor key={`${selected.id}-${selected.revision}`} event={selected} worldId={worldId}
          locations={locations} saved={refresh} report={report} />}
        <details><summary>Änderungsverlauf</summary><ul className="space-y-2 my-3">
          {selected.audit.map(entry => <li key={entry.id} className="muted text-sm">
            {new Date(entry.created_at).toLocaleString('de-DE')} · {({
              proposed: 'Vorschlag erstellt', applied: 'Übernommen', edited: 'Vorschlag bearbeitet',
              rejected: 'Abgelehnt', invalidated: 'Quelle geändert', undone: 'Zurückgenommen',
              mutation_reverted: 'Zustandsänderung rückgängig gemacht',
            } as Record<string, string>)[entry.action] ?? entry.action} ·
            {entry.actor === 'auto' ? ' automatisch' : entry.actor === 'user' ? ' manuell' : ' Hintergrundverarbeitung'}
          </li>)}</ul></details>
      </article>}
    </div>
  </div>
}
