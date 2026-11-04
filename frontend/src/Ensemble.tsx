import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, errorText } from './api'
import { statusLabels } from './Events'
import type { Entity, ExtractionJob, Message } from './types'
import { Field } from './ui'

type Scene = { character_ids: string[]; location_id: string; scene: string; communication: string }
type Clock = { elapsed_minutes: number; minutes_per_day: number; epoch_label: string; revision: number }
type Session = {
  id: string; title: string; revision: number; status: string; completed_rounds: number
  max_rounds: number; calls_used: number; max_calls: number; tokens_reserved: number; max_tokens: number
  seconds_used: number; timeout_seconds: number; stop_reason: string; error: string
  conversation_id: string; conversation: { scene: string; scene_location_id: string; communication: string }
  participants: { id: string; name: string }[]; messages: Message[]; jobs: ExtractionJob[]
  reported_extraction_tokens: number | null
  event_counts: Record<string, number>; events: { id: string; description: string; status: string }[]
}
type Group = { id: string; title: string; scene: string; scene_location_id: string
  communication: string; participants: { id: string; name: string }[] }
const labels: Record<string, string> = {
  created: 'Bereit', running: 'Läuft', paused: 'Pausiert', completed: 'Beendet',
  cancelled: 'Abgebrochen', failed: 'Fehlgeschlagen', round_limit: 'Rundenlimit',
  token_limit: 'Tokenbudget', call_limit: 'Anfragelimit', time_limit: 'Zeitlimit',
  step_limit: 'Schritt abgeschlossen', backend_restart: 'Backend neu gestartet',
  extraction_failed: 'Extraktion fehlgeschlagen', generation_failed: 'Antwort fehlgeschlagen',
  participants_left: 'Nicht genug anwesende Charaktere', user_pause: 'Manuell pausiert',
  user_cancel: 'Manuell abgebrochen',
}

function SceneFields({ value, change, characters, locations }: {
  value: Scene; change: (scene: Scene) => void; characters: Entity[]; locations: Entity[]
}) {
  return <>
    <Field label="Teilnehmende Charaktere"><div className="space-y-2">{characters.map(character =>
      <label className="checkbox" key={character.id}><input type="checkbox"
        checked={value.character_ids.includes(character.id)} onChange={event => change({
          ...value, character_ids: event.target.checked ? [...value.character_ids, character.id]
            : value.character_ids.filter(id => id !== character.id),
        })} />{character.name} <small className="muted">
          ({locations.find(l => l.id === character.location_id)?.name ?? 'unbekannt'}
          {character.travel_status === 'traveling' ? ' · unterwegs' : ''})</small></label>)}</div></Field>
    <Field label="Szenenort"><select value={value.location_id} required
      onChange={event => change({ ...value, location_id: event.target.value })}>
      <option value="">Ort auswählen</option>
      {locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}
    </select></Field>
    <Field label="Kommunikation"><select value={value.communication}
      onChange={event => change({ ...value, communication: event.target.value })}>
      <option value="in_person">Vor Ort (gleicher Aufenthaltsort erforderlich)</option>
      <option value="remote">Ausdrückliche Fernkommunikation</option>
    </select></Field>
    <Field label="Öffentliche Szene"><textarea rows={3} value={value.scene} maxLength={10000}
      onChange={event => change({ ...value, scene: event.target.value })} /></Field>
  </>
}

function NewSession({ simulation, characters, locations, save, busy }: {
  simulation: boolean; characters: Entity[]; locations: Entity[]
  save: (body: object) => Promise<void>; busy: boolean
}) {
  const [title, setTitle] = useState('Begegnung')
  const [scene, setScene] = useState<Scene>({
    character_ids: [], location_id: '', scene: '', communication: 'in_person',
  })
  const [mode, setMode] = useState('rules')
  const [limits, setLimits] = useState({ max_rounds: 20, max_calls: 100, max_tokens: 250000,
    timeout_seconds: 600, minutes_per_round: 1 })
  const [model, setModel] = useState('')
  const numeric = [
    ['max_rounds', 'Rundenlimit', 1, 500], ['max_calls', 'Anfragelimit', 1, 2000],
    ['max_tokens', 'Tokenbudget (konservativ geschätzt)', 1024, 10000000],
    ['timeout_seconds', 'Modellzeit gesamt (Sekunden)', 5, 7200],
    ['minutes_per_round', 'Weltminuten pro Runde', 0, 1440],
  ] as const
  return <form className="panel p-5 space-y-4 mb-5" onSubmit={event => {
    event.preventDefault()
    void save({ title, ...scene, ...(simulation ? { ...limits, event_mode: mode, model } : {}) })
  }}>
    <h2>{simulation ? 'Neue Simulation' : 'Neues Gruppengespräch'}</h2>
    <Field label="Titel"><input value={title} required maxLength={200}
      onChange={event => setTitle(event.target.value)} /></Field>
    <SceneFields value={scene} change={setScene} characters={characters} locations={locations} />
    {simulation && <>
      <Field label="Weltänderungen"><select value={mode} onChange={event => setMode(event.target.value)}>
        <option value="rules">Nach bestehenden Freigaberegeln</option>
        <option value="confirm">Alle Vorschläge bestätigen</option>
        <option value="observe">Nur beobachten (keine Weltänderungen)</option>
      </select></Field>
      <details><summary>Grenzen und Modell</summary><div className="space-y-3 mt-4">
        {numeric.map(([key, label, min, max]) => <Field label={label} key={key}>
          <input type="number" value={limits[key]} min={min} max={max} required
            onChange={event => setLimits({ ...limits, [key]: Number(event.target.value) })} />
        </Field>)}
        <Field label="Simulationsmodell (leer: Chatmodell)"><input value={model} maxLength={200}
          onChange={event => setModel(event.target.value)} /></Field>
      </div></details>
      <p className="muted text-sm">Eine Runde = ein Charakterbeitrag. Reihenfolge wie ausgewählt.
        Jede Extraktion zählt als eigene Anfrage. Keine automatischen Wiederholungen.
        Start nutzt die eingestellten Provider; bei Cloudanbietern können Kosten entstehen.</p>
    </>}
    <button className="button primary" disabled={busy || scene.character_ids.length < 2}>
      {busy ? 'Wird gespeichert …' : 'Anlegen'}</button>
  </form>
}

export function WorldTime({ worldId, report }: { worldId: string; report: (error: string) => void }) {
  const client = useQueryClient()
  const clock = useQuery({ queryKey: ['clock', worldId],
    queryFn: () => api<Clock>(`/worlds/${worldId}/clock`), refetchInterval: 2000 })
  const [minutes, setMinutes] = useState('')
  const [day, setDay] = useState('')
  const [epoch, setEpoch] = useState('')
  const [busy, setBusy] = useState(false)
  const c = clock.data
  return <section className="panel p-5 mb-5">
    <h3>Weltzeit</h3>
    {clock.error && <p role="alert">{errorText(clock.error)}</p>}
    {c && <p>{c.epoch_label} · +{Math.floor(c.elapsed_minutes / c.minutes_per_day)} Tage ·
      {' '}{Math.floor(c.elapsed_minutes % c.minutes_per_day / 60)} h {c.elapsed_minutes % c.minutes_per_day % 60} min</p>}
    <details className="mt-3"><summary>Weltzeit bearbeiten</summary>
      <form className="space-y-3 mt-3" onSubmit={async event => {
        event.preventDefault(); if (!c) return
        setBusy(true); report('')
        try {
          await api(`/worlds/${worldId}/clock`, 'PUT', {
            revision: c.revision, elapsed_minutes: minutes === '' ? c.elapsed_minutes : Number(minutes),
            minutes_per_day: day === '' ? c.minutes_per_day : Number(day),
            epoch_label: epoch || c.epoch_label,
          })
          await client.invalidateQueries({ queryKey: ['clock', worldId] })
          setMinutes(''); setDay(''); setEpoch('')
        } catch (error) { report(errorText(error)) }
        finally { setBusy(false) }
      }}>
        <Field label="Vergangene Weltminuten"><input type="number" min={0} max={1000000000}
          placeholder={String(c?.elapsed_minutes ?? 0)} value={minutes}
          onChange={event => setMinutes(event.target.value)} /></Field>
        <Field label="Minuten pro Tag"><input type="number" min={60} max={100000}
          placeholder={String(c?.minutes_per_day ?? 1440)} value={day}
          onChange={event => setDay(event.target.value)} /></Field>
        <Field label="Kalenderbeginn"><input value={epoch} placeholder={c?.epoch_label} maxLength={200}
          onChange={event => setEpoch(event.target.value)} /></Field>
        <button className="button" disabled={busy || !c}>Als Ereignis speichern</button>
      </form>
    </details>
  </section>
}

function SceneEditor({ session, characters, locations, save, busy }: {
  session: Session; characters: Entity[]; locations: Entity[]; busy: boolean
  save: (body: Scene) => Promise<void>
}) {
  const [scene, setScene] = useState<Scene>({
    character_ids: session.participants.map(p => p.id), scene: session.conversation.scene,
    location_id: session.conversation.scene_location_id,
    communication: session.conversation.communication,
  })
  return <details className="mt-4"><summary>Szene und Teilnehmer ändern</summary>
    <form className="space-y-3 mt-3" onSubmit={event => { event.preventDefault(); void save(scene) }}>
      <SceneFields value={scene} change={setScene} characters={characters} locations={locations} />
      <button className="button" disabled={busy || scene.character_ids.length < 2}>Szene speichern</button>
    </form>
  </details>
}

export function Ensemble({ worldId, characters, locations, report, onEvents, simulation = true }: {
  worldId: string; characters: Entity[]; locations: Entity[]; report: (error: string) => void
  onEvents: () => void; simulation?: boolean
}) {
  const client = useQueryClient()
  const [id, setId] = useState('')
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  const [content, setContent] = useState('')
  const [address, setAddress] = useState('')
  const [steps, setSteps] = useState(5)
  const resource = simulation ? 'simulations' : 'group-conversations'
  const base = `/worlds/${worldId}/${resource}`
  const key = [resource, worldId]
  const list = useQuery({ queryKey: key, queryFn: () => api<(Session | Group)[]>(base),
    refetchInterval: simulation ? 1500 : false })
  const detail = useQuery<Session | Group>({ queryKey: [...key, id],
    queryFn: () => simulation ? api<Session>(`${base}/${id}`) :
      api<Group>(`/group-conversations/${id}`), enabled: !!id,
    refetchInterval: simulation ? 1000 : false })
  const session = detail.data && 'completed_rounds' in detail.data ? detail.data : undefined
  const group = detail.data && !('completed_rounds' in detail.data) ? detail.data : undefined
  const messages = useQuery({ queryKey: ['group-messages', id],
    queryFn: () => api<Message[]>(`/conversations/${id}/messages`), enabled: !!group,
    refetchInterval: group ? 2000 : false })
  useEffect(() => {
    void client.invalidateQueries({ queryKey: ['entities', worldId] })
  }, [session?.completed_rounds, worldId, client])
  async function action(path: string, method: 'POST' | 'PUT', body: object) {
    setBusy(true); report('')
    try {
      await api(path, method, body)
      await Promise.all([client.invalidateQueries({ queryKey: key }),
        client.invalidateQueries({ queryKey: ['group-messages', id] })])
      return true
    } catch (error) { report(errorText(error)); return false }
    finally { setBusy(false) }
  }
  const available = !!session && ['created', 'paused', 'failed'].includes(session.status)
  const paused = !!session && ['created', 'paused'].includes(session.status)
  const conversationMessages = session?.messages ?? messages.data ?? []
  const people = session?.participants ?? group?.participants ?? []
  const control = (name: string, count?: number) => session && action(
    `${base}/${id}/control/${name}`, 'POST', { revision: session.revision, steps: count })
  return <div>
    {simulation && <WorldTime worldId={worldId} report={report} />}
    <div className="flex flex-wrap gap-3 mb-5">
      <select aria-label={simulation ? 'Simulation auswählen' : 'Gruppengespräch auswählen'}
        className="max-w-sm" value={id} onChange={event => { setId(event.target.value); setCreating(false) }}>
        <option value="">Auswählen</option>{list.data?.map(item => <option key={item.id} value={item.id}>
          {item.title}{'status' in item ? ` · ${labels[item.status] ?? item.status}` : ''}
        </option>)}
      </select>
      <button className="button" onClick={() => setCreating(!creating)}>
        {simulation ? 'Neue Simulation' : 'Neues Gruppengespräch'}</button>
      <button className="button" onClick={onEvents}>Ereignisse prüfen</button>
    </div>
    {(list.error || detail.error || messages.error) && <p role="alert" className="error-banner">
      {errorText(list.error ?? detail.error ?? messages.error)}</p>}
    {creating && <NewSession simulation={simulation} characters={characters} locations={locations}
      busy={busy} save={async body => {
        setBusy(true); report('')
        try {
          const created = await api<Session | Group>(base, 'POST', body)
          setId(created.id); setCreating(false)
          await client.invalidateQueries({ queryKey: key })
        } catch (error) { report(errorText(error)) }
        finally { setBusy(false) }
      }} />}
    {detail.data && <div className="ensemble-layout">
      <section className="panel p-5">
        <h2>{detail.data.title}</h2>
        <p className="muted text-sm mb-5">{people.map(p => p.name).join(' · ')}</p>
        <div className="ensemble-transcript" aria-label="Öffentlicher Gesprächsverlauf" aria-live="polite">
          {conversationMessages.map(message => <article key={message.id} className="ensemble-message">
            <header><strong>{message.speaker_character_id ?
              characters.find(c => c.id === message.speaker_character_id)?.name ?? 'Charakter'
              : 'Du'}</strong>
              {message.world_minute != null && <small className="muted"> · Weltminute {message.world_minute}</small>}
            </header>
            <p className="whitespace-pre-wrap mt-2">{message.content}</p>
          </article>)}
          {!conversationMessages.length && <p className="muted">Noch keine Beiträge.</p>}
        </div>
        {(!simulation || paused) && <form className="space-y-3 mt-5" onSubmit={async event => {
          event.preventDefault()
          const saved = await action(simulation ? `${base}/${id}/interventions` :
            `/group-conversations/${id}/messages`, 'POST', {
              content, ...(session ? { revision: session.revision, address_id: address || null } : {}),
            })
          if (saved) setContent('')
        }}>
          {simulation && <Field label="Direkt ansprechen"><select value={address}
            onChange={event => setAddress(event.target.value)}>
            <option value="">Alle Anwesenden</option>
            {people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></Field>}
          <Field label={simulation ? 'Eingriff im pausierten Gespräch' : 'Dein Beitrag'}>
            <textarea required value={content} maxLength={10000} rows={3}
              onChange={event => setContent(event.target.value)} /></Field>
          <button className="button" disabled={busy || !content.trim()}>Beitrag senden</button>
        </form>}
        {group && <div className="flex flex-wrap gap-3 mt-5">
          {people.map(p => <button key={p.id} className="button" disabled={busy} onClick={() =>
            void action(`/group-conversations/${id}/turn`, 'POST', { speaker_id: p.id })}>
            {p.name} antwortet</button>)}
        </div>}
      </section>
      {session && <aside className="panel p-5 space-y-4">
        <h3>Steuerung · {labels[session.status] ?? session.status}</h3>
        {session.stop_reason && <p>{labels[session.stop_reason] ?? session.stop_reason}</p>}
        {session.error && <p role="alert" className="error-banner">{session.error}</p>}
        <p>Runden: {session.completed_rounds} / {session.max_rounds}<br />
          Anfragen: {session.calls_used} / {session.max_calls}<br />
          Tokenreservierung: {session.tokens_reserved.toLocaleString('de-DE')} / {session.max_tokens.toLocaleString('de-DE')}<br />
          Modellzeit: {session.seconds_used.toFixed(1)} / {session.timeout_seconds} s</p>
        <p className="muted text-xs">Tokens sind konservativ geschätzte Reservierungen, keine gemessene
          Gesamtnutzung. Kosten unbekannt. Extraktion gemeldet: {session.reported_extraction_tokens ?? 'unbekannt'} Tokens.</p>
        <div className="flex flex-wrap gap-2">
          <button className="button primary" disabled={busy || !available} onClick={() =>
            void control(session.status === 'created' ? 'start' : 'resume')}>
            {session.status === 'created' ? 'Starten' : 'Fortsetzen'}</button>
          <button className="button" disabled={busy || session.status !== 'running'}
            onClick={() => void control('pause')}>Pause</button>
          <button className="button danger" disabled={busy || ['completed', 'cancelled'].includes(session.status)}
            onClick={() => void control('cancel')}>Abbrechen</button>
        </div>
        <div className="flex flex-wrap gap-2">{[1, 5, 20].map(count =>
          <button key={count} className="button" disabled={busy || !available} onClick={() =>
            void control(session.status === 'created' ? 'start' : 'resume', count)}>
            {count} {count === 1 ? 'Runde' : 'Runden'}</button>)}</div>
        <Field label="Eigene Rundenzahl"><input type="number" min={1} max={500} value={steps}
          onChange={event => setSteps(Number(event.target.value))} /></Field>
        <button className="button" disabled={busy || !available || steps < 1 || steps > 500}
          onClick={() => void control(session.status === 'created' ? 'start' : 'resume', steps)}>
          Runden ausführen</button>
        <section aria-label="Simulationsereignisse">
          <h3>Ereignisse dieser Simulation</h3>
          <p>Übernommen: {session.event_counts?.applied ?? 0}<br />
            Ausstehende Bestätigungen: {session.event_counts?.proposed ?? 0}<br />
            Geschützte Vorschläge: {session.event_counts?.protected ?? 0}</p>
          <ul className="space-y-2 my-3">{session.events?.map(event => <li key={event.id} className="text-sm">
            <span className="tag">{statusLabels[event.status] ?? event.status}</span> {event.description}
          </li>)}</ul>
          <button className="button" onClick={onEvents}>Details und Freigaben</button>
        </section>
        {paused && <SceneEditor key={`${id}:${session.revision}`} session={session}
          characters={characters} locations={locations} busy={busy}
          save={async scene => { await action(`${base}/${id}/scene`, 'PUT',
            { ...scene, revision: session.revision }) }} />}
        <details><summary>Extraktionsaufträge ({session.jobs.length})</summary>
          {session.jobs.map(job => <p key={job.id} className="muted text-xs mt-3">
            {job.status} · Versuch {job.attempts} / 3 {job.error && `· ${job.error}`}</p>)}
        </details>
      </aside>}
    </div>}
  </div>
}
