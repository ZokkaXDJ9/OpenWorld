import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from './api'
import type { ProviderSettings } from './types'
import { Field } from './ui'

type Kind = 'lmstudio' | 'ollama' | 'openai' | 'compatible'
type Model = { id: string; name: string; loaded: boolean | null }
type Server = { kind: Kind; base_url: string; reachable: boolean; models: Model[]; message?: string }
type Listing = { models: string[]; details: Model[] }
const names = { lmstudio: 'LM Studio', ollama: 'Ollama', openai: 'OpenAI', compatible: 'Eigene Verbindung' }

export function ConnectionSetup({ initial, close }: {
  initial: ProviderSettings; close: () => void
}) {
  const client = useQueryClient()
  const dialog = useRef<HTMLDialogElement>(null)
  const [scope, setScope] = useState('local')
  const [kind, setKind] = useState<Kind>('lmstudio')
  const [online, setOnline] = useState('openai')
  const [value, setValue] = useState(initial)
  const [step, setStep] = useState(1)
  const [key, setKey] = useState('')
  const [models, setModels] = useState<Model[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [manual, setManual] = useState(false)
  const [automatic, setAutomatic] = useState(true)
  const [retry, setRetry] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reply, setReply] = useState('')
  const [proof, setProof] = useState('')
  const [memories, setMemories] = useState(!initial.model)
  const [done, setDone] = useState(false)
  useEffect(() => { dialog.current?.showModal() }, [])
  function patch(change: Partial<ProviderSettings>) {
    setValue(v => ({ ...v, ...change })); setReply(''); setProof(''); setError(''); setNotice('')
  }
  function credentials() {
    return {
      base_url: value.base_url, model: value.model, context_window: value.context_window,
      max_output_tokens: value.max_output_tokens, temperature: value.temperature,
      reasoning_profile: value.reasoning_profile, reasoning_mode: value.reasoning_mode,
      api_key: key || null, clear_key: false,
    }
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (error) { setError(errorText(error)) }
    finally { setBusy(false) }
  }
  function selectServer(server: Server) {
    setKind(server.kind); setModels(server.models); setKey('')
    patch({ base_url: server.base_url, model: server.models.some(m => m.id === initial.model) ? initial.model : '' })
  }
  async function scan() {
    const result = await api<{ servers: Server[] }>('/settings/provider/local')
    setServers(result.servers)
    const available = result.servers.find(s => s.reachable && s.models.some(m => m.loaded)) ??
      result.servers.find(s => s.reachable)
    if (available) selectServer(available)
    else setNotice('Noch keine lokale KI erreichbar. Starte LM Studio mit aktiviertem lokalen Server oder öffne Ollama. Suche anschließend erneut.')
  }
  async function listModels() {
    const result = await api<Listing>('/settings/provider/models', 'POST', { ...credentials(), kind })
    const selected = models.find(m => m.id === value.model)
    setModels(result.details)
    if (!result.models.length) {
      setNotice('Der Server ist erreichbar, hat aber noch kein Chatmodell. Lade im KI-Programm ein Modell herunter bzw. in den Arbeitsspeicher. OpenWorld lädt nichts ungefragt herunter.')
      return
    }
    const match = result.details.find(m => m.id === value.model) ??
      result.details.find(m => m.name === selected?.name && m.loaded) ??
      (result.details.length === 1 ? result.details[0] : undefined)
    patch({ model: match?.id ?? '' })
    setManual(false); setStep(3)
  }
  const selected = models.find(model => model.id === value.model)
  return <dialog ref={dialog} className="setup-dialog panel editor" aria-labelledby="setup-title"
    onCancel={event => { if (busy) event.preventDefault() }} onClose={close}>
    <div className="section-heading"><h2 id="setup-title">KI einrichten</h2>
      <button className="button small" disabled={busy} onClick={() => dialog.current?.close()}>
        {done ? 'Schließen' : 'Später einrichten'}</button></div>
    {!done ? <>
      <p className="muted my-4">Schritt {step} von 3 · {step === 1 ? 'KI auswählen' :
        step === 2 ? 'Verbindung herstellen' : 'Antwort testen'}</p>
      <p className="mb-5">Für Gespräche und Simulationen benötigst du eine KI-Verbindung.
        Wir helfen dir bei der Einrichtung. Deine Welten bleiben auch ohne KI bearbeitbar.</p>
      <form className="space-y-5" onSubmit={event => {
        event.preventDefault()
        if (step === 1) {
          setStep(2); setError(''); setNotice(''); setModels([]); setReply(''); setProof('')
          if (scope === 'local') { setRetry(true); void run(scan) }
          else if (scope === 'online') {
            setKind('openai'); setRetry(false); setOnline('openai')
            patch({ base_url: 'https://api.openai.com/v1', model: '' })
          } else { setKind('compatible'); setRetry(false); setManual(true) }
        } else if (step === 2) { void run(listModels) }
      }}>
        <fieldset disabled={busy} className="space-y-5">
          {step === 1 && <Field label="Welche KI möchtest du verwenden?">
            <div className="space-y-3">{([
              ['local', 'Lokale KI auf diesem Computer'],
              ['online', 'KI über einen Online-Anbieter'],
              ['custom', 'Eigene Verbindung (erweitert)'],
            ] as const).map(([id, name]) => <label className="checkbox" key={id}>
              <input type="radio" name="scope" checked={scope === id}
                onChange={() => { setScope(id); setKey('') }} />{name}</label>)}</div>
          </Field>}
          {step === 2 && scope === 'local' && <>
            <h3>Lokale KI finden</h3>
            <p>Wir prüfen LM Studio und Ollama auf deinem Computer. Es werden nur
              Modellinformationen abgefragt, keine Gespräche gesendet.</p>
            {servers.map(server => <div key={server.kind} className="notice space-y-2">
              <label className="checkbox"><input type="radio" name="server"
                checked={server.reachable && kind === server.kind && value.base_url === server.base_url}
                disabled={!server.reachable} onChange={() => selectServer(server)} />
                {names[server.kind]} · {server.reachable ? `${server.models.length} Modelle gefunden` : 'nicht erreichbar'}</label>
              <p>{server.kind === 'lmstudio' ?
                'LM Studio öffnen → „Developer / Entwickler“ → lokalen Server starten. Ein Chatmodell auswählen und laden.' :
                'Ollama öffnen und ein Chatmodell herunterladen. Ollama während des Spielens geöffnet lassen.'}</p>
              {!server.reachable && server.message && <p>{server.message}</p>}
            </div>)}
            <button type="button" className="button" onClick={() => { void run(scan) }}>Erneut nach lokaler KI suchen</button>
            <p><a href="https://lmstudio.ai/" target="_blank" rel="noreferrer">LM Studio herunterladen</a>
              {' · '}<a href="https://ollama.com/" target="_blank" rel="noreferrer">Ollama herunterladen</a></p>
            <details><summary>Expertenmodus: andere lokale Serveradresse oder Zugangsschlüssel</summary>
              <div className="space-y-3 mt-4">
                <Field label="Serveradresse"><input type="url" required value={value.base_url}
                  onChange={event => patch({ base_url: event.target.value })} /></Field>
                <Field label="Lokaler API-Schlüssel"><input type="password" autoComplete="new-password" value={key}
                  onChange={event => { setKey(event.target.value); setProof(''); setReply('') }} /></Field>
              </div></details>
          </>}
          {step === 2 && scope === 'online' && <>
            <Field label="Online-Anbieter"><select value={online} onChange={event => {
              const next = event.target.value; setOnline(next); setKey('')
              setKind(next === 'openai' ? 'openai' : 'compatible')
              patch({ base_url: next === 'openai' ? 'https://api.openai.com/v1' : 'https://openrouter.ai/api/v1', model: '' })
            }}><option value="openai">OpenAI</option><option value="openrouter">OpenRouter</option></select></Field>
            <p className="notice">Gespräche werden an diesen Anbieter gesendet. API-Nutzung kostet
              normalerweise Geld; ein Chat-Abonnement allein reicht nicht aus. Modelllisten
              erzeugen hier noch keine Antworten.</p>
            <Field label="API-Schlüssel"><input type="password" autoComplete="new-password"
              required={!(initial.has_api_key && initial.base_url === value.base_url)}
              placeholder={initial.has_api_key && initial.base_url === value.base_url ? 'Gespeicherter Schlüssel wird verwendet' : ''}
              value={key} onChange={event => { setKey(event.target.value); setProof(''); setReply('') }} /></Field>
            <a className="button" href={online === 'openai' ? 'https://platform.openai.com/api-keys' : 'https://openrouter.ai/settings/keys'}
              target="_blank" rel="noreferrer">API-Schlüssel beim Anbieter erstellen</a>
          </>}
          {step === 2 && scope === 'custom' && <>
            <p>Für erfahrene Benutzer: Adresse und Modellnamen erhältst du vom Betreiber.
              Falls keine Modellliste angeboten wird, kannst du den Namen selbst eingeben.</p>
            <Field label="Serveradresse"><input type="url" required value={value.base_url}
              onChange={event => patch({ base_url: event.target.value })} /></Field>
            <Field label="API-Schlüssel (optional)"><input type="password" autoComplete="new-password" value={key}
              onChange={event => { setKey(event.target.value); setProof(''); setReply('') }} /></Field>
          </>}
          {step === 3 && <>
            {manual ? <Field label="Modellname"><input required maxLength={200} value={value.model}
              onChange={event => patch({ model: event.target.value })} /></Field> :
              <Field label="Modell für deine Charaktere"><select required value={value.model}
                onChange={event => patch({ model: event.target.value })}>
                <option value="">Bitte ein Modell auswählen</option>
                {models.map(model => <option key={model.id} value={model.id}>{model.name} · {
                  model.loaded ? 'geladen' : model.loaded === false ?
                    kind === 'ollama' ? 'startet beim Test' : 'noch nicht geladen' : 'Bereitschaft wird getestet'
                }</option>)}</select></Field>}
            {selected?.loaded === false && kind === 'lmstudio' && <p className="notice">
              Dieses Modell ist installiert, aber noch nicht geladen. Lade es zuerst in LM Studio
              und aktualisiere dann die Modellliste.</p>}
            <button type="button" className="button" onClick={() => { void run(listModels) }}>Modellliste aktualisieren</button>
            <p>„Antwort testen“ sendet nur eine kurze technische Testfrage, keine Weltdaten.
              {scope === 'local' ? ' Ollama kann dabei ein installiertes Modell in den Arbeitsspeicher laden.' :
                ' Auch dieser Test kann API-Kosten verursachen.'}</p>
            <label className="checkbox"><input type="checkbox" checked={retry}
              onChange={event => setRetry(event.target.checked)} />
              Falls nötig einen zweiten Verbindungstest erlauben</label>
            <p className="muted text-sm">Pro Klick höchstens {retry ? 'zwei' : 'eine'} Modellanfrage
              {retry ? ', nur bei einer nicht unterstützten Einstellung' : ', keine automatische Wiederholung'}.
              Zusätzliche Tests können bei Online-Anbietern zusätzliche Kosten verursachen.</p>
            <button type="button" className="button" disabled={!value.model.trim()} onClick={event => {
              if (!event.currentTarget.form?.reportValidity()) return
              setProof(''); setReply('')
              void run(async () => {
                const result = await api<{ reply: string; settings: ProviderSettings;
                  verification_token: string; warnings?: string[] }>(
                  '/settings/provider/test', 'POST', { ...credentials(), kind, automatic,
                    manual_model: manual, allow_compatibility_retry: retry })
                setValue(result.settings); setReply(result.reply); setProof(result.verification_token)
                setNotice(result.warnings?.join(' ') ?? '')
              })
            }}>Antwort testen</button>
            {reply && <div role="status" className="notice">Das Modell hat geantwortet: {reply}</div>}
            <label className="checkbox"><input type="checkbox" checked={memories}
              onChange={event => setMemories(event.target.checked)} />
              Diese KI auch für Erinnerungen und Weltveränderungen vorbereiten</label>
            <p className="muted text-sm">Bestehende Sondereinstellungen werden nur mit diesem
              Häkchen ersetzt. Zusätzliche automatische KI-Anfragen werden dadurch noch nicht aktiviert.</p>
            <details><summary>Expertenmodus: automatische Konfiguration anpassen</summary>
              <div className="space-y-4 mt-4">
                <label className="checkbox"><input type="checkbox" checked={automatic}
                  onChange={event => { setAutomatic(event.target.checked); setProof(''); setReply('') }} />
                  Verbindung automatisch passend konfigurieren</label>
                <p>Ohne automatische Konfiguration werden die hier sichtbaren Werte verwendet.
                  Bei unbekannten Fähigkeiten wählt OpenWorld sonst vorsichtige Vorgaben.</p>
                <Field label="Kontextfenster (Tokens)"><input type="number" min={1024} required
                  disabled={automatic} value={value.context_window}
                  onChange={event => patch({ context_window: Number(event.target.value) })} /></Field>
                <Field label="Antwortlänge (Tokens)"><input type="number" min={1} required disabled={automatic}
                  max={value.context_window - 257} value={value.max_output_tokens}
                  onChange={event => patch({ max_output_tokens: Number(event.target.value) })} /></Field>
              </div></details>
          </>}
        </fieldset>
        {error && <p role="alert" className="error-banner">{error}</p>}
        {notice && <p role="status" className="notice">{notice}</p>}
        <div className="flex flex-wrap gap-3">
          {step > 1 && <button type="button" className="button" disabled={busy}
            onClick={() => { setStep(step - 1); setError(''); setNotice('') }}>Zurück</button>}
          {step < 3 && <button className="button primary" disabled={busy}>
            {busy ? 'Verbindung wird geprüft …' : step === 1 ? 'Weiter' : 'Verbindung prüfen'}</button>}
          {step === 2 && scope !== 'local' && <button type="button" className="button" disabled={busy}
            onClick={() => { setManual(true); setProof(''); setReply(''); setStep(3); setError('') }}>
            Modellnamen selbst eingeben</button>}
          {step === 3 && <button type="button" className="button primary" disabled={busy || !proof}
            onClick={() => { void run(async () => {
              const result = await api<ProviderSettings>('/settings/setup', 'POST', {
                provider: credentials(), kind, configure_memories: memories, verification_token: proof,
              })
              client.setQueryData(['provider'], result)
              await Promise.all([client.invalidateQueries({ queryKey: ['extraction-provider'] }),
                client.invalidateQueries({ queryKey: ['provider-status'] })])
              setKey(''); setDone(true)
            }) }}>Einrichtung abschließen</button>}
        </div>
        {busy && step === 3 && <p role="status">Bitte warten. Die KI wird geprüft …</p>}
      </form>
    </> : <div className="space-y-4 mt-5" role="status">
      <h3>Deine KI ist bereit! Du kannst jetzt mit deinen Charakteren sprechen.</h3>
      <p>Erinnerungen und Weltveränderungen lassen sich pro Welt in den Einstellungen
        einschalten. Online können dadurch zusätzliche Kosten entstehen.</p>
      <button className="button primary" onClick={() => dialog.current?.close()}>Zurück zum vorherigen Vorgang</button>
    </div>}
  </dialog>
}
