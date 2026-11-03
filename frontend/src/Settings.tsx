import { useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Save, Server } from 'lucide-react'
import { useState } from 'react'
import { api, errorText } from './api'
import type { ProviderSettings } from './types'
import { Field } from './ui'

export function Settings({ report }: { report: (text: string) => void }) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['provider'], queryFn: () => api<ProviderSettings>('/settings/provider'),
  })
  const [draft, setDraft] = useState<ProviderSettings | null>(null)
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const value = draft ?? query.data
  if (query.error) return <p role="alert" className="error-text">{errorText(query.error)}</p>
  if (!value) return <p className="muted">Einstellungen werden geladen ...</p>
  function patch(change: Partial<ProviderSettings>) {
    if (value) setDraft({ ...value, ...change })
    setSaved(false)
  }
  return <form className="panel editor space-y-5 max-w-3xl" onSubmit={async e => {
    e.preventDefault(); setBusy(true); report('')
    try {
      const result = await api<ProviderSettings>('/settings/provider', 'PUT', {
        base_url: value.base_url, model: value.model, context_window: value.context_window,
        max_output_tokens: value.max_output_tokens, temperature: value.temperature,
        api_key: key || null, clear_key: clearKey,
      })
      client.setQueryData(['provider'], result); setDraft(result)
      setKey(''); setClearKey(false); setSaved(true)
    } catch (error) { report(errorText(error)) }
    finally { setBusy(false) }
  }}>
    <div className="section-heading"><h2>KI-Verbindung</h2><Server size={25} /></div>
    <p className="muted">OpenAI-kompatible APIs, Ollama und LM Studio.
      Ohne Verbindung funktionieren alle Welt- und Charaktereditoren weiterhin.</p>
    <div className="flex flex-wrap gap-2">
      <button type="button" className="button small" onClick={() => patch({
        base_url: 'http://localhost:11434/v1',
      })}>Ollama</button>
      <button type="button" className="button small" onClick={() => patch({
        base_url: 'http://localhost:1234/v1',
      })}>LM Studio</button>
      <button type="button" className="button small" onClick={() => patch({
        base_url: 'https://api.openai.com/v1',
      })}>OpenAI</button>
    </div>
    <Field label="Base-URL"><input required type="url" value={value.base_url}
      onChange={e => patch({ base_url: e.target.value })} /></Field>
    <Field label="Modellname"><input required value={value.model}
      onChange={e => patch({ model: e.target.value })} placeholder="z. B. llama3.1:8b" /></Field>
    <Field label={`API-Schlüssel ${value.has_api_key ? '(gespeichert; leer lassen zum Beibehalten)' : '(optional bei lokalen Modellen)'}`}>
      <input type="password" value={key} autoComplete="new-password"
        onChange={e => { setKey(e.target.value); setSaved(false) }} /></Field>
    {value.has_api_key && <label className="checkbox"><input type="checkbox" checked={clearKey}
      onChange={e => setClearKey(e.target.checked)} /> Gespeicherten Schlüssel entfernen</label>}
    <p className="muted text-xs flex items-center gap-2"><KeyRound size={14} />
      Verschlüsselte Speicherung ausschließlich im Backend. Kein Schlüssel wird zurückgegeben.</p>
    <details><summary>Erweiterte Modelleinstellungen</summary><div className="space-y-4 mt-5">
      <Field label="Kontextfenster des Modells (Tokens)"><input required type="number" min={1024}
        value={value.context_window} onChange={e => patch({ context_window: Number(e.target.value) })} /></Field>
      <Field label="Reservierte Antwort-Tokens"><input required type="number" min={1}
        value={value.max_output_tokens} onChange={e => patch({ max_output_tokens: Number(e.target.value) })} /></Field>
      <Field label="Temperature"><input required type="number" min={0} max={2} step={0.05}
        value={value.temperature} onChange={e => patch({ temperature: Number(e.target.value) })} /></Field>
      <p className="muted text-sm">Keine globale 8k-/32k-Grenze. Trage das tatsächliche Modellfenster ein.
        Die Tokenzählung nutzt cl100k_base als Näherung; andere Tokenizer können abweichen.</p>
    </div></details>
    <button className="button primary" disabled={busy}><Save size={16} />
      {busy ? 'Speichert ...' : 'Verbindung speichern'}</button>
    {saved && <p role="status" className="success">Einstellungen gespeichert. Die Verbindung wird beim nächsten Chat geprüft.</p>}
    <div className="notice">Lokale Einzelbenutzer-Version: API nur auf dem eigenen Rechner betreiben.
      Benutzerkonten und abgesicherter Serverbetrieb folgen in Phase 4.</div>
  </form>
}
