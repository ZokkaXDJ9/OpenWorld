import * as Tabs from '@radix-ui/react-tabs'
import { Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText } from './api'
import { Attributes } from './Attributes'
import { canMoveLocation } from './locationStructure'
import { Memories } from './Memories'
import type { Entity, KnowledgeKind, Resource } from './types'
import { ConfirmButton, Field } from './ui'

export const knowledgeLabels: Record<KnowledgeKind, string> = {
  fact: 'Objektiver Weltfakt', knowledge: 'Persönliches Wissen', belief: 'Überzeugung',
  suspicion: 'Vermutung', rumor: 'Gerücht', secret: 'Geheimnis', memory: 'Erinnerung',
  received: 'Erhaltene Information',
}
const profileFields = [
  'Aliasnamen', 'Erscheinungsbild', 'Persoenlichkeit', 'Biografie', 'Herkunft', 'Spezies',
  'Alter', 'Faehigkeiten', 'Interessen', 'Aengste', 'Ziele', 'Motivation', 'Moralvorstellungen',
  'Sprachstil', 'Inventar',
]
const profileLabels: Record<string, string> = {
  Persoenlichkeit: 'Persönlichkeit', Faehigkeiten: 'Fähigkeiten', Aengste: 'Ängste',
}

export function Editor({
  resource, item, worldId, locations, characters, objects, onSaved, onCancel, report,
  structureBusy = false, onBusyChange,
}: {
  resource: Resource; item?: Entity; worldId: string; locations: Entity[]
  characters: Entity[]; objects: Entity[]; onSaved: () => Promise<void>
  onCancel: () => void; report: (error: string) => void
  structureBusy?: boolean; onBusyChange?: (busy: boolean) => void
}) {
  const [draft, setDraft] = useState<Entity>(item ?? {
    id: '', revision: 1, name: '', description: '', attributes: [], state: {},
    kind: resource === 'knowledge' ? 'knowledge' : resource === 'locations' ? 'Ort' : 'Bekanntschaft',
    profile: {}, travel_status: 'unknown', character_id: characters[0]?.id ?? null,
    source_id: characters[0]?.id ?? '', target_id: characters[1]?.id ?? '',
    content: '', source: 'Editor', confidence: 100,
  })
  const [busy, setBusy] = useState(false)
  const [newState, setNewState] = useState('')
  const [newProfile, setNewProfile] = useState('')
  useEffect(() => {
    if (resource === 'locations' && item) {
      setDraft(current => ({ ...current, parent_id: item.parent_id }))
    }
  }, [resource, item?.parent_id])
  function setSaving(value: boolean) { setBusy(value); onBusyChange?.(value) }
  function patch(change: Partial<Entity>) { setDraft({ ...draft, ...change }) }
  const path = resource === 'worlds' ? '/worlds' : `/worlds/${worldId}/${resource}`
  async function save(event: FormEvent) {
    event.preventDefault()
    if (structureBusy) return
    setSaving(true)
    let data: Record<string, unknown>
    const common = {
      name: draft.name, description: draft.description ?? '', attributes: draft.attributes ?? [],
      state: draft.state ?? {}, ...(item ? { revision: item.revision } : {}),
    }
    if (resource === 'worlds') data = common
    else if (resource === 'locations') data = {
      ...common, kind: draft.kind, parent_id: draft.parent_id || null, tags: draft.tags ?? [],
    }
    else if (resource === 'characters') data = {
      ...common, profile: draft.profile ?? {}, location_id: draft.location_id || null,
      destination_id: draft.destination_id || null, travel_status: draft.travel_status ?? 'unknown',
    }
    else if (resource === 'relationships') data = {
      source_id: draft.source_id, target_id: draft.target_id, kind: draft.kind,
      description: draft.description ?? '', attributes: draft.attributes ?? [],
      secret: draft.secret ?? false, ...(item ? { revision: item.revision } : {}),
    }
    else data = {
      character_id: draft.kind === 'fact' ? null : draft.character_id,
      kind: draft.kind, content: draft.content, source: draft.source ?? 'Editor',
      confidence: draft.confidence ?? 100, public: draft.kind === 'fact' && (draft.public ?? false),
      ...(item ? { revision: item.revision } : {}),
    }
    try {
      await api(`${path}${item ? `/${item.id}` : ''}`, item ? 'PUT' : 'POST', data)
      await onSaved()
    } catch (error) { report(errorText(error)) }
    finally { setSaving(false) }
  }
  async function remove() {
    if (!item || structureBusy) return
    setSaving(true)
    try {
      await api(`${path}/${item.id}?revision=${item.revision}`, 'DELETE')
      await onSaved()
    } catch (error) { report(errorText(error)) }
    finally { setSaving(false) }
  }
  const general = <>
    <Field label="Name"><input required maxLength={200} value={draft.name ?? ''}
      onChange={e => patch({ name: e.target.value })} /></Field>
    <Field label={resource === 'worlds' ? 'Öffentliche Weltbeschreibung' : 'Beschreibung'}>
      <textarea rows={5} value={draft.description ?? ''}
        onChange={e => patch({ description: e.target.value })} />
    </Field>
    {resource === 'locations' && <>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Typ"><input required value={draft.kind ?? ''}
          onChange={e => patch({ kind: e.target.value })} placeholder="Region, Stadt, Dimension ..." /></Field>
        <Field label="Übergeordneter Ort"><select value={draft.parent_id ?? ''}
          onChange={e => patch({ parent_id: e.target.value || null })}>
          <option value="">Direkt in der Welt</option>{locations.filter(o =>
            !item || canMoveLocation(locations, item.id, o.id))
            .map(o => <option value={o.id} key={o.id}>{o.name}</option>)}</select></Field>
      </div>
      <Field label="Tags (durch Komma getrennt)"><input value={(draft.tags ?? []).join(', ')}
        onChange={e => patch({ tags: e.target.value.split(',').map(s => s.trim()) })} /></Field>
    </>}
    <Attributes value={draft.attributes ?? []} onChange={attributes => patch({ attributes })}
      objects={objects.filter(o => o.id !== draft.id)} />
  </>
  const stateEditor = <section className="space-y-4">
    <p className="muted text-sm">Veränderlicher Zustand. Die ursprüngliche Beschreibung bleibt erhalten.
      Ereignisvorschläge werden nach den Freigaberegeln übernommen und protokolliert.</p>
    {Object.entries(draft.state ?? {}).map(([key, value]) => <div key={key} className="flex gap-2 items-end">
      <div className="flex-1"><Field label={key}><input value={String(value)}
        onChange={e => patch({ state: { ...draft.state, [key]: e.target.value } })} /></Field></div>
      <button type="button" className="button small" onClick={() => {
        const state = { ...draft.state }; delete state[key]; patch({ state })
      }}>Entfernen</button>
    </div>)}
    <div className="flex items-end gap-2">
      <div className="flex-1"><Field label="Neues Zustandsfeld"><input value={newState}
        onChange={e => setNewState(e.target.value)} placeholder="z. B. Emotionaler Zustand" /></Field></div>
      <button type="button" className="button" disabled={!newState.trim()} onClick={() => {
        patch({ state: { ...draft.state, [newState.trim()]: '' } }); setNewState('')
      }}>Hinzufügen</button>
    </div>
  </section>
  return <form onSubmit={save} className="editor panel space-y-5">
    <div className="section-heading"><div><p className="eyebrow">{item ? 'Bearbeiten' : 'Neu anlegen'}</p>
      <h2>{resource === 'knowledge' ? 'Wissen & Erinnerungen' :
        resource === 'relationships' ? 'Gerichtete Beziehung' : draft.name ||
          (resource === 'worlds' ? 'Neue Welt' : resource === 'locations' ? 'Neuer Ort' : 'Neuer Charakter')}</h2>
    </div><button type="button" className="button subtle" onClick={onCancel}>Schließen</button></div>
    {(resource === 'worlds' || resource === 'locations') && <>
      {general}<details><summary>Aktueller Zustand</summary><div className="mt-4">{stateEditor}</div></details>
      <p className="muted text-xs">Welt- und Ortsbeschreibungen gelten als öffentlich.
        Versteckte Fakten bitte im Wissenseditor anlegen.</p>
    </>}
    {resource === 'characters' && <Tabs.Root defaultValue="general">
      <Tabs.List className="tabs" aria-label="Charakterbereiche">
        <Tabs.Trigger value="general">Allgemeines</Tabs.Trigger>
        <Tabs.Trigger value="profile">Persönlichkeit & Hintergrund</Tabs.Trigger>
        <Tabs.Trigger value="state">Zustand & Ort</Tabs.Trigger>
        {item && <Tabs.Trigger value="memories">Erinnerungen</Tabs.Trigger>}
      </Tabs.List>
      <Tabs.Content value="general" className="space-y-4 mt-5">
        {general}
      </Tabs.Content>
      <Tabs.Content value="profile" className="space-y-4 mt-5">
        <p className="muted text-sm">Alle Profilfelder sind optional und nur diesem Charakter bekannt.</p>
        {Array.from(new Set([...profileFields, ...Object.keys(draft.profile ?? {})])).map(key =>
          <Field label={profileLabels[key] ?? key} key={key}><textarea rows={2} value={draft.profile?.[key] ?? ''}
            onChange={e => patch({ profile: { ...draft.profile, [key]: e.target.value } })} /></Field>)}
        <div className="flex gap-2 items-end">
          <div className="flex-1"><Field label="Eigenes Profilfeld"><input value={newProfile}
            onChange={e => setNewProfile(e.target.value)} /></Field></div>
          <button type="button" className="button" disabled={!newProfile.trim()} onClick={() => {
            patch({ profile: { ...draft.profile, [newProfile.trim()]: '' } }); setNewProfile('')
          }}>Hinzufügen</button>
        </div>
      </Tabs.Content>
      <Tabs.Content value="state" className="space-y-4 mt-5">
        <Field label="Aufenthaltsstatus"><select value={draft.travel_status}
          onChange={e => patch({
            travel_status: e.target.value as Entity['travel_status'],
            ...(e.target.value === 'unknown' ? { location_id: null, destination_id: null } : {}),
          })}><option value="unknown">Unbekannt</option><option value="present">Anwesend</option>
          <option value="traveling">Unterwegs</option></select></Field>
        {draft.travel_status !== 'unknown' && <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Aktueller Ort"><select required={draft.travel_status === 'present'}
            value={draft.location_id ?? ''} onChange={e => patch({ location_id: e.target.value || null })}>
            <option value="">Kein bekannter Ort</option>{locations.map(o =>
              <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
          <Field label="Reiseziel (optional)"><select value={draft.destination_id ?? ''}
            onChange={e => patch({ destination_id: e.target.value || null })}>
            <option value="">Kein Ziel</option>{locations.map(o =>
              <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
        </div>}
        {stateEditor}
      </Tabs.Content>
      {item && <Tabs.Content value="memories">
        <Memories worldId={worldId} characterId={item.id} report={report} />
      </Tabs.Content>}
    </Tabs.Root>}
    {resource === 'relationships' && <>
      <div className="grid sm:grid-cols-2 gap-4">
        {(['source_id', 'target_id'] as const).map(key => <Field key={key}
          label={key === 'source_id' ? 'Von Charakter' : 'Zu Charakter'}>
          <select required value={draft[key]} onChange={e => patch({ [key]: e.target.value })}>
            <option value="">Charakter wählen</option>{characters.map(c =>
              <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>)}
      </div>
      <Field label="Beziehungstyp"><input required value={draft.kind}
        onChange={e => patch({ kind: e.target.value })} /></Field>
      <Field label="Gemeinsame Geschichte / Einschätzung"><textarea rows={4}
        value={draft.description ?? ''} onChange={e => patch({ description: e.target.value })} /></Field>
      <label className="checkbox"><input type="checkbox" checked={draft.secret ?? false}
        onChange={e => patch({ secret: e.target.checked })} /> Geheime Beziehung</label>
      <p className="muted text-sm">A → B ist unabhängig von B → A. Im Chat wird nur die Sicht
        des aktuellen Charakters verwendet.</p>
      <Attributes value={draft.attributes ?? []} onChange={attributes => patch({ attributes })}
        objects={objects} />
    </>}
    {resource === 'knowledge' && <>
      <Field label="Wissensart"><select value={draft.kind} onChange={e =>
        patch({ kind: e.target.value, public: false })}>
        {Object.entries(knowledgeLabels).map(([kind, label]) =>
          <option key={kind} value={kind}>{label}</option>)}</select></Field>
      {draft.kind !== 'fact' ? <Field label="Bekannt für"><select required value={draft.character_id ?? ''}
        onChange={e => patch({ character_id: e.target.value })}>
        <option value="">Charakter wählen</option>{characters.map(c =>
          <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field> :
        <label className="checkbox"><input type="checkbox" checked={draft.public ?? false}
          onChange={e => patch({ public: e.target.checked })} /> Öffentlich bekannt</label>}
      <Field label="Inhalt"><textarea required rows={5} value={draft.content ?? ''}
        onChange={e => patch({ content: e.target.value })} /></Field>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Quelle"><input value={draft.source ?? ''} maxLength={200}
          onChange={e => patch({ source: e.target.value })} /></Field>
        <Field label="Vertrauensgrad (%)"><input type="number" required min={0} max={100}
          value={draft.confidence ?? 100} onChange={e => patch({ confidence: Number(e.target.value) })} /></Field>
      </div>
      {draft.source_message_id && <p className="muted text-xs">Herkunft: Chatnachricht {draft.source_message_id}.
        Änderungen der Quelle werden auf abhängige Ereignisse geprüft.</p>}
      <p className="muted text-sm">Nicht öffentliche Weltfakten gelangen nicht in den Chatkontext.
        Persönliches Wissen gilt nur für den gewählten Charakter, auch wenn es falsch ist.</p>
    </>}
    <div className="editor-footer">
      <button className="button primary" disabled={busy || structureBusy}><Save size={16} />
        {busy ? 'Speichert ...' : 'Speichern'}</button>
      {item && <ConfirmButton title="Objekt wirklich löschen?"
        description="Abhängige Chats, Beziehungen und Wissen werden ebenfalls entfernt. Verwendete Orte und Feldreferenzen müssen zuerst gelöst werden."
        onConfirm={remove} disabled={busy || structureBusy} />}
    </div>
  </form>
}
