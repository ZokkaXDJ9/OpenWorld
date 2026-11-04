import { useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Save, Server } from 'lucide-react'
import { useState } from 'react'
import { api, errorText } from './api'
import type { ExtractionProviderSettings, ProviderSettings } from './types'
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
  return <div className="space-y-5"><form className="panel editor space-y-5 max-w-3xl" onSubmit={async e => {
    e.preventDefault(); setBusy(true); report('')
    try {
      const result = await api<ProviderSettings>('/settings/provider', 'PUT', {
        base_url: value.base_url, model: value.model, context_window: value.context_window,
        max_output_tokens: value.max_output_tokens, temperature: value.temperature,
        reasoning_profile: value.reasoning_profile, reasoning_mode: value.reasoning_mode,
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
      <Field label="Reasoning-Profil des Chats"><select value={value.reasoning_profile}
        onChange={e => patch({
          reasoning_profile: e.target.value as ProviderSettings['reasoning_profile'],
          reasoning_mode: 'default',
        })}>
        <option value="default">Unverändert / Anbietervorgabe</option>
        <option value="lmstudio">LM Studio (reasoning_effort)</option>
        <option value="openai">OpenAI (reasoning_effort)</option>
        <option value="llama_cpp">llama.cpp / vLLM (enable_thinking)</option>
      </select></Field>
      <Field label="Reasoning im Chat"><select value={value.reasoning_mode}
        onChange={e => patch({ reasoning_mode: e.target.value as ProviderSettings['reasoning_mode'] })}>
        <option value="default">Anbietervorgabe</option>
        {value.reasoning_profile !== 'default' && <option value="off">Aus</option>}
        {value.reasoning_profile === 'llama_cpp' && <option value="on">An</option>}
        {value.reasoning_profile === 'openai' && <>
          <option value="low">Gering</option><option value="medium">Mittel</option><option value="high">Hoch</option>
        </>}
      </select></Field>
      <Field label="Kontextfenster des Modells (Tokens)"><input required type="number" min={1024}
        value={value.context_window} onChange={e => patch({ context_window: Number(e.target.value) })} /></Field>
      <Field label="Reservierte Antwort-Tokens"><input required type="number" min={1}
        value={value.max_output_tokens} onChange={e => patch({ max_output_tokens: Number(e.target.value) })} /></Field>
      <Field label="Temperature"><input required type="number" min={0} max={2} step={0.05}
        value={value.temperature} onChange={e => patch({ temperature: Number(e.target.value) })} /></Field>
      <p className="muted text-sm">Keine globale 8k-/32k-Grenze. Trage das tatsächliche Modellfenster ein.
        Die Tokenzählung nutzt cl100k_base als Näherung; andere Tokenizer können abweichen.
        Bei Reasoning-Modellen zählen Denktokens zum Antwortbudget. Chat-Reasoning bleibt
        unabhängig von der Ereignisextraktion; die Anbietervorgabe wird nicht ungefragt geändert.</p>
    </div></details>
    <button className="button primary" disabled={busy}><Save size={16} />
      {busy ? 'Speichert ...' : 'Verbindung speichern'}</button>
    {saved && <p role="status" className="success">Einstellungen gespeichert. Die Verbindung wird beim nächsten Chat geprüft.</p>}
    <div className="notice">Lokale Einzelbenutzer-Version: API nur auf dem eigenen Rechner betreiben.
      Benutzerkonten und abgesicherter Serverbetrieb folgen in Phase 4.</div>
  </form><ExtractionSettings report={report} /></div>
}

function ExtractionSettings({ report }: { report: (text: string) => void }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['extraction-provider'],
    queryFn: () => api<ExtractionProviderSettings>('/settings/extraction') })
  const [draft, setDraft] = useState<ExtractionProviderSettings | null>(null)
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const value = draft ?? query.data
  if (query.error) return <p role="alert">{errorText(query.error)}</p>
  if (!value) return <p className="muted">Extraktionseinstellungen werden geladen ...</p>
  function patch(change: Partial<ExtractionProviderSettings>) {
    if (value) setDraft({ ...value, ...change })
    setSaved(false)
  }
  const reasoningModes = value.provider_profile === 'compatible' ? ['default'] :
    value.provider_profile === 'llama_cpp' ? ['default', 'off', 'on'] :
      value.provider_profile === 'openai' ? ['default', 'off', 'low', 'medium', 'high'] :
        ['default', 'off', 'on', 'low', 'medium', 'high']
  const reasoningLabels: Record<string, string> = {
    default: 'Anbietervorgabe', off: 'Aus', on: 'An', low: 'Gering', medium: 'Mittel', high: 'Hoch',
  }
  return <form aria-label="Ereignisextraktion" className="panel editor space-y-5 max-w-3xl"
    onSubmit={async e => {
      e.preventDefault(); setBusy(true); report('')
      try {
        const { has_api_key: _stored, ...settings } = value
        const result = await api<ExtractionProviderSettings>('/settings/extraction', 'PUT', {
          use_chat_connection: settings.use_chat_connection, base_url: settings.base_url,
          model: settings.model, context_window: settings.context_window,
          max_output_tokens: settings.max_output_tokens, temperature: settings.temperature,
          timeout_seconds: settings.timeout_seconds, provider_profile: settings.provider_profile,
          reasoning_mode: settings.reasoning_mode, structured_output: settings.structured_output,
          auto_retry: settings.auto_retry, api_key: key || null, clear_key: clearKey,
        })
        client.setQueryData(['extraction-provider'], result); setDraft(result)
        setKey(''); setClearKey(false); setSaved(true)
      } catch (error) { report(errorText(error)) }
      finally { setBusy(false) }
    }}>
    <h2>Ereignisextraktion</h2>
    <p className="muted">Eigene Einstellungen für strukturierte Änderungsvorschläge.
      Sie verändern weder das Chatmodell noch dessen Antwortbudget.</p>
    <label className="checkbox"><input type="checkbox" checked={value.use_chat_connection}
      onChange={e => patch({ use_chat_connection: e.target.checked })} />
      Verbindung und Zugangsschlüssel des Chats verwenden</label>
    {!value.use_chat_connection && <>
      <Field label="Extraktion: Base-URL"><input required type="url" value={value.base_url}
        onChange={e => patch({ base_url: e.target.value })} /></Field>
      <Field label={`Extraktion: API-Schlüssel ${value.has_api_key ? '(gespeichert)' : '(optional)'}`}>
        <input type="password" autoComplete="new-password" value={key}
          onChange={e => { setKey(e.target.value); setSaved(false) }} /></Field>
      {value.has_api_key && <label className="checkbox"><input type="checkbox" checked={clearKey}
        onChange={e => { setClearKey(e.target.checked); setSaved(false) }} />
        Separaten Extraktionsschlüssel entfernen</label>}
    </>}
    <Field label="Extraktionsmodell (leer = Chatmodell)"><input value={value.model}
      onChange={e => patch({ model: e.target.value })} /></Field>
    <Field label="Anbieterprofil der Extraktion"><select value={value.provider_profile}
      onChange={e => patch({
        provider_profile: e.target.value as ExtractionProviderSettings['provider_profile'],
        reasoning_mode: 'default', structured_output: 'auto',
      })}>
      <option value="compatible">OpenAI-kompatibel (ohne Reasoning-Steuerung)</option>
      <option value="openai">OpenAI (reasoning_effort)</option>
      <option value="llama_cpp">llama.cpp / vLLM (enable_thinking)</option>
      <option value="ollama">Ollama (native API, think)</option>
      <option value="lmstudio">LM Studio (native API, reasoning)</option>
    </select></Field>
    <Field label="Reasoning bei der Extraktion"><select value={value.reasoning_mode}
      onChange={e => patch({ reasoning_mode: e.target.value as ExtractionProviderSettings['reasoning_mode'] })}>
      {reasoningModes.map(mode => <option key={mode} value={mode}>{reasoningLabels[mode]}</option>)}
    </select></Field>
    <p className="muted text-sm">Profile müssen zum tatsächlich laufenden Server und Modell passen.
      LM Studio nutzt für wirksame Reasoning-Steuerung /api/v1/chat ohne serverseitige
      Gesprächsspeicherung oder Werkzeuge; JSON wird dort per Prompt angefordert und streng geprüft.</p>
    <Field label="Strukturiertes Ausgabeformat"><select value={value.structured_output}
      onChange={e => patch({ structured_output: e.target.value as ExtractionProviderSettings['structured_output'] })}>
      <option value="auto">Automatisch mit begrenzter Format-Aushandlung</option>
      {value.provider_profile !== 'lmstudio' && <>
        <option value="json_schema">JSON-Schema</option><option value="json_object">JSON-Objekt</option>
      </>}
      <option value="text">JSON nur per Prompt</option>
    </select></Field>
    <Field label="Extraktion: Kontextfenster (Tokens)"><input required type="number" min={1024}
      value={value.context_window} onChange={e => patch({ context_window: Number(e.target.value) })} /></Field>
    <Field label="Extraktion: Ausgabetokens"><input required type="number" min={1} max={65536}
      value={value.max_output_tokens} onChange={e => patch({ max_output_tokens: Number(e.target.value) })} /></Field>
    <Field label="Extraktion: Zeitlimit (Sekunden)"><input required type="number" min={15} max={1800}
      value={value.timeout_seconds} onChange={e => patch({ timeout_seconds: Number(e.target.value) })} /></Field>
    <Field label="Extraktion: Temperature"><input required type="number" min={0} max={2} step={0.05}
      value={value.temperature} onChange={e => patch({ temperature: Number(e.target.value) })} /></Field>
    <label className="checkbox"><input type="checkbox" checked={value.auto_retry}
      onChange={e => patch({ auto_retry: e.target.checked })} />
      Höchstens eine gezielte automatische Wiederholung erlauben</label>
    <p className="muted text-sm">Standardbudget: 4.096 Tokens; bei abgeschnittener oder leerer Ausgabe
      kann der Wiederholungsversuch bis zum doppelten Budget erhalten, soweit das Kontextfenster reicht.
      Bei Cloud-Anbietern kann dieser zusätzliche Aufruf Kosten verursachen.
      Insgesamt höchstens drei Versuche je Auftrag; nach zwei Fehlschlägen nur noch manuell.</p>
    <button className="button primary" disabled={busy}><Save size={16} />
      {busy ? 'Speichert ...' : 'Extraktionseinstellungen speichern'}</button>
    {saved && <p role="status" className="success">Extraktionseinstellungen gespeichert.</p>}
  </form>
}
