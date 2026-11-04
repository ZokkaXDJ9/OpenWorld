import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageCircle, Plus, RefreshCw, Send, Pencil } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, errorText, streamChat } from './api'
import type { Conversation, Entity, EventSettings, ExtractionJob, Message, WorldEvent } from './types'
import { ConfirmButton, Empty, Field } from './ui'

export function Chat({
  worldId, characters, report, onEvents,
}: { worldId: string; characters: Entity[]; report: (text: string) => void; onEvents: () => void }) {
  const client = useQueryClient()
  const [conversationId, setConversationId] = useState('')
  const [characterId, setCharacterId] = useState(characters[0]?.id ?? '')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [partial, setPartial] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [editing, setEditing] = useState('')
  const [editText, setEditText] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  const conversations = useQuery({
    queryKey: ['conversations', worldId],
    queryFn: () => api<Conversation[]>(`/worlds/${worldId}/conversations`),
  })
  const history = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => api<Message[]>(`/conversations/${conversationId}/messages`),
    enabled: !!conversationId,
  })
  const eventSettings = useQuery({ queryKey: ['event-settings', worldId],
    queryFn: () => api<EventSettings>(`/worlds/${worldId}/event-settings`) })
  const jobs = useQuery({ queryKey: ['extraction-jobs', worldId, conversationId],
    queryFn: () => api<ExtractionJob[]>(`/worlds/${worldId}/extraction-jobs?conversation_id=${conversationId}`),
    enabled: !!conversationId, refetchInterval: 3000 })
  const events = useQuery({ queryKey: ['events', worldId, conversationId],
    queryFn: () => api<WorldEvent[]>(`/worlds/${worldId}/events?conversation_id=${conversationId}`),
    enabled: !!conversationId, refetchInterval: 3000 })
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) },
    [partial, history.data?.length])
  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['messages', conversationId] }),
      client.invalidateQueries({ queryKey: ['entities', worldId] }),
      client.invalidateQueries({ queryKey: ['events', worldId] }),
      client.invalidateQueries({ queryKey: ['extraction-jobs', worldId] }),
    ])
  }
  async function create() {
    try {
      const conversation = await api<Conversation>(`/worlds/${worldId}/conversations`, 'POST', {
        character_id: characterId,
        title: `Gespräch mit ${characters.find(c => c.id === characterId)?.name ?? 'Charakter'}`,
      })
      await client.invalidateQueries({ queryKey: ['conversations', worldId] })
      setConversationId(conversation.id)
    } catch (error) { report(errorText(error)) }
  }
  async function send(regenerate = false) {
    if (!conversationId || busy || (!regenerate && !input.trim())) return
    setBusy(true); setPartial(''); report('')
    const content = input
    setSubmitted(regenerate ? '' : content)
    if (!regenerate) setInput('')
    try {
      await streamChat(`/conversations/${conversationId}/${regenerate ? 'regenerate' : 'messages'}`,
        regenerate ? {} : { content }, chunk => setPartial(text => text + chunk),
        () => { void client.invalidateQueries({ queryKey: ['messages', conversationId] }) })
    } catch (error) {
      if (!regenerate) setInput(content)
      report(`${errorText(error)} Prüfe den Verlauf vor dem erneuten Senden. Bereits gespeicherte Nachrichten bleiben erhalten; „Erneut antworten“ wiederholt die letzte Anfrage ohne neue Benutzernachricht.`)
    } finally {
      setBusy(false); setPartial(''); setSubmitted('')
      await refresh()
    }
  }
  const selected = conversations.data?.find(c => c.id === conversationId)
  const character = characters.find(c => c.id === selected?.character_id)
  return <div className="chat-layout">
    <aside className="panel chat-list">
      <div className="section-heading"><h3>Gespräche</h3><MessageCircle size={18} /></div>
      <Field label="Charakter"><select value={characterId} onChange={e => setCharacterId(e.target.value)}>
        <option value="">Charakter wählen</option>{characters.map(c =>
          <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <button className="button primary w-full justify-center" disabled={!characterId || busy}
        onClick={() => { void create() }}><Plus size={16} /> Neues Gespräch</button>
      {conversations.isPending && <p className="muted">Lädt ...</p>}
      {conversations.error && <p role="alert" className="error-text">{errorText(conversations.error)}</p>}
      <div className="space-y-2">{conversations.data?.map(c =>
        <button key={c.id} disabled={busy} className={`list-item ${conversationId === c.id ? 'selected' : ''}`}
          onClick={() => { setConversationId(c.id); setEditing('') }}>
          <MessageCircle size={16} /><span>{c.title}<small>
            {new Date(c.created_at).toLocaleDateString('de-DE')}</small></span>
        </button>)}</div>
    </aside>
    <section className="panel chat-window">
      {!selected ? <Empty title="Kein Gespräch ausgewählt"
        text="Ein vorhandenes Gespräch öffnen oder einen Charakter für ein neues Gespräch auswählen." /> : <>
        <header className="chat-header">
          <div className="avatar">{character?.name?.slice(0, 1) ?? '?'}</div>
          <div className="flex-1"><h3>{character?.name}</h3><p className="muted text-xs">
            Einzelgespräch</p></div>
          <ConfirmButton title="Gespräch löschen?"
            description="Der Verlauf und daraus gespeicherte erhaltene Informationen werden entfernt."
            disabled={busy} onConfirm={async () => {
              try {
                await api(`/conversations/${conversationId}`, 'DELETE')
                setConversationId('')
                await client.invalidateQueries({ queryKey: ['conversations', worldId] })
                await client.invalidateQueries({ queryKey: ['entities', worldId, 'knowledge'] })
              } catch (error) { report(errorText(error)) }
            }} />
        </header>
        <div className="messages" aria-live="polite" aria-busy={busy}>
          {history.isPending && <p className="muted">Nachrichten werden geladen ...</p>}
          {history.error && <p role="alert" className="error-text">{errorText(history.error)}</p>}
          {history.data?.length === 0 && <Empty title="Noch keine Nachrichten"
            text="Nachricht eingeben und senden." />}
          {history.data?.map(message => <article key={message.id}
            className={`message ${message.role === 'user' ? 'from-user' : ''}`}>
            <div className="message-meta">{message.role === 'user' ? 'Du' : character?.name}
              <time>{new Date(message.created_at).toLocaleTimeString('de-DE', {
                hour: '2-digit', minute: '2-digit',
              })}</time>
              {message.role === 'user' && <button className="icon-button" disabled={busy}
                aria-label="Nachricht bearbeiten" onClick={() => {
                  setEditing(message.id); setEditText(message.content)
                }}><Pencil size={13} /></button>}
            </div>
            {editing === message.id ? <div className="space-y-3">
              <textarea value={editText} onChange={e => setEditText(e.target.value)} rows={4} />
              <div className="flex gap-2">
                <ConfirmButton title="Gespräch ab hier neu beginnen?"
                  description="Alle folgenden Nachrichten und ihre abgeleiteten Erinnerungen werden gelöscht. Die Erinnerung dieser Nachricht wird aktualisiert. Objektive Weltfakten bleiben unverändert."
                  destructive={false} disabled={!editText.trim()} onConfirm={async () => {
                    try {
                      await api(`/conversations/${conversationId}/messages/${message.id}`, 'PUT', {
                        content: editText, confirm_discard: true,
                      })
                      setEditing(''); await refresh()
                    } catch (error) { report(errorText(error)) }
                  }}>Änderung speichern</ConfirmButton>
                <button className="button" onClick={() => setEditing('')}>Abbrechen</button>
              </div>
            </div> : <p>{message.content}</p>}
          </article>)}
          {busy && submitted && history.data?.at(-1)?.content !== submitted &&
            <article className="message from-user"><div className="message-meta">Du</div><p>{submitted}</p></article>}
          {busy && <article className="message"><div className="message-meta">
            {character?.name}<span className="pulse">schreibt ...</span></div>
            <p>{partial || 'Die Verbindung zum Modell wird aufgebaut ...'}</p></article>}
          <div ref={bottom} />
        </div>
        <form className="composer" onSubmit={e => { e.preventDefault(); void send() }}>
          <textarea aria-label="Deine Nachricht" placeholder={`Nachricht an ${character?.name}`}
            value={input} onChange={e => setInput(e.target.value)} rows={2} disabled={busy}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault(); void send()
              }
            }} />
          <div className="flex justify-between items-center gap-3">
            <button type="button" className="button subtle small" disabled={busy || !history.data?.length}
              onClick={() => { void send(true) }}><RefreshCw size={14} /> Erneut antworten</button>
            <button className="button primary" disabled={busy || !input.trim()}>
              <Send size={16} /> Senden</button>
          </div>
          {(events.error || jobs.error || eventSettings.error) && <p role="alert" className="error-text">
            {errorText(events.error ?? jobs.error ?? eventSettings.error)}</p>}
          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" className="button subtle small" onClick={onEvents}>
              {events.data?.filter(event => event.status === 'proposed').length ?? 0} mögliche Änderungen erkannt
            </button>
            <span className="muted text-xs">{jobs.data?.some(job => job.status === 'failed') ?
              'Erkennung fehlgeschlagen – Details unter Ereignisse' :
              jobs.data?.some(job => ['pending', 'running'].includes(job.status)) ? 'Ereignisse werden geprüft ...' :
                eventSettings.data?.enabled ? 'Ereigniserkennung aktiv' : 'Ereigniserkennung ausgeschaltet'}</span>
            {eventSettings.data?.enabled && <button type="button" className="button subtle small" disabled={busy}
              onClick={async () => {
                try {
                  await api(`/conversations/${conversationId}/extract`, 'POST')
                  await refresh()
                } catch (error) { report(errorText(error)) }
              }}>Verlauf prüfen</button>}
          </div>
          <p className="muted text-xs">Behauptungen bleiben persönliche Informationen, keine Weltfakten.
            Änderungen werden nach den Freigaberegeln geprüft.</p>
        </form>
      </>}
    </section>
  </div>
}
