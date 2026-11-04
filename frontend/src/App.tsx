import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, BookOpen, ChevronRight, Globe2, Map, MessageCircle, Moon,
  Network, Plus, Settings2, Sparkles, Sun, Users, X,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { api, errorText } from './api'
import { Chat } from './Chat'
import { Editor, knowledgeLabels } from './Editor'
import { Events } from './Events'
import { LocationTree } from './LocationTree'
import { moveLocations } from './locationStructure'
import { Settings } from './Settings'
import { ConnectionSetup } from './ConnectionSetup'
import { Ensemble } from './Ensemble'
import { WorldTransfer } from './WorldTransfer'
import type { Entity, ExtractionJob, KnowledgeKind, ProviderSettings, Resource } from './types'
import { Empty } from './ui'

const RelationshipGraph = lazy(() => import('./RelationshipGraph').then(module =>
  ({ default: module.RelationshipGraph })))

type Page = 'worlds' | 'locations' | 'characters' | 'relationships' | 'knowledge' | 'events' | 'chats' | 'groups' | 'simulations' | 'settings'
const navigation = [
  { id: 'worlds', label: 'Meine Welten', icon: Globe2 },
  { id: 'locations', label: 'Welteditor', icon: Map },
  { id: 'characters', label: 'Charaktere', icon: Users },
  { id: 'relationships', label: 'Beziehungen', icon: Network },
  { id: 'knowledge', label: 'Wissen & Erinnerungen', icon: BookOpen },
  { id: 'events', label: 'Ereignisse', icon: Sparkles },
  { id: 'chats', label: 'Chats', icon: MessageCircle },
  { id: 'groups', label: 'Gruppengespräche', icon: Users },
  { id: 'simulations', label: 'Simulationen', icon: Network },
  { id: 'settings', label: 'Einstellungen', icon: Settings2 },
] as const

function useEntities(worldId: string, resource: Resource) {
  return useQuery({
    queryKey: ['entities', worldId, resource],
    queryFn: () => api<Entity[]>(`/worlds/${worldId}/${resource}`),
    enabled: !!worldId,
  })
}

export default function App() {
  const client = useQueryClient()
  const [page, setPage] = useState<Page>('worlds')
  const [setupOpen, setSetupOpen] = useState(false)
  const provider = useQuery({ queryKey: ['provider'],
    queryFn: () => api<ProviderSettings>('/settings/provider') })
  const providerStatus = useQuery({ queryKey: ['provider-status'],
    queryFn: () => api<{ state: string; message: string }>('/settings/provider/status'),
    retry: false, refetchOnWindowFocus: false })
  const [worldId, setWorldId] = useState(localStorage.getItem('openworld-world') ?? '')
  const [editor, setEditor] = useState<{ resource: Resource; item?: Entity } | null>(null)
  const [error, setError] = useState('')
  const [dark, setDark] = useState(localStorage.getItem('openworld-theme') !== 'light')
  const [knowledgeFilter, setKnowledgeFilter] = useState('')
  const [moving, setMoving] = useState(false)
  const [locationSaving, setLocationSaving] = useState(false)
  const [moveStatus, setMoveStatus] = useState('')
  const worlds = useQuery({ queryKey: ['worlds'], queryFn: () => api<Entity[]>('/worlds') })
  const locations = useEntities(worldId, 'locations')
  const characters = useEntities(worldId, 'characters')
  const relationships = useEntities(worldId, 'relationships')
  const knowledge = useEntities(worldId, 'knowledge')
  const currentWorld = worlds.data?.find(w => w.id === worldId)
  const jobs = useQuery({ queryKey: ['extraction-jobs', worldId],
    queryFn: () => api<ExtractionJob[]>(`/worlds/${worldId}/extraction-jobs`),
    enabled: !!currentWorld, refetchInterval: 2000 })
  const completedJobs = jobs.data?.filter(job => ['complete', 'invalidated'].includes(job.status))
    .map(job => `${job.id}:${job.status}`).join(',')
  useEffect(() => {
    void client.invalidateQueries({ queryKey: ['entities', worldId] })
    void client.invalidateQueries({ queryKey: ['memories', worldId] })
  }, [completedJobs, client, worldId])
  const editedLocation = editor?.resource === 'locations' && editor.item ?
    locations.data?.find(item => item.id === editor.item?.id) : undefined
  const objects = [...locations.data ?? [], ...characters.data ?? [],
    ...relationships.data ?? [], ...knowledge.data ?? []]
  function navigate(next: Page) { setPage(next); setEditor(null); setError(''); setMoveStatus('') }
  async function moveLocation(id: string, parentId: string | null, beforeId: string | null) {
    if (moving || locationSaving) return
    setMoving(true); setError(''); setMoveStatus('Weltstruktur wird gespeichert ...')
    try {
      const current = locations.data ?? []
      const updated = moveLocations(current, id, parentId, beforeId)
      if (updated.every(item => {
        const original = current.find(location => location.id === item.id)
        return original?.parent_id === item.parent_id && original?.sort_order === item.sort_order
      })) { setMoveStatus('Reihenfolge unverändert.'); return }
      const result = await api<Entity[]>(`/worlds/${worldId}/location-tree`, 'PUT', {
        locations: updated.map(item => ({
          id: item.id, parent_id: item.parent_id ?? null, sort_order: item.sort_order, revision: item.revision,
        })),
      })
      client.setQueryData(['entities', worldId, 'locations'], result)
      setMoveStatus('Weltstruktur gespeichert.')
    } catch (error) {
      setError(errorText(error)); setMoveStatus('')
      await client.invalidateQueries({ queryKey: ['entities', worldId, 'locations'] })
    } finally { setMoving(false) }
  }
  function openWorld(world: Entity) {
    setWorldId(world.id); localStorage.setItem('openworld-world', world.id); navigate('locations')
  }
  async function saved() {
    setEditor(null); setError('')
    await Promise.all([
      client.invalidateQueries({ queryKey: ['worlds'] }),
      client.invalidateQueries({ queryKey: ['entities'] }),
      client.invalidateQueries({ queryKey: ['conversations'] }),
    ])
  }
  const pageLabel = navigation.find(n => n.id === page)?.label
  const relevantError = page === 'locations' ? locations.error : page === 'characters' ?
    characters.error : page === 'relationships' ? relationships.error : page === 'knowledge' ? knowledge.error : null
  return <div className={`app ${dark ? 'dark' : 'light'}`}>
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('worlds') }}>
        <div className="brand-symbol"><Globe2 size={23} /></div><span>OpenWorld</span>
      </a>
      <nav aria-label="Hauptnavigation">{navigation.map(({ id, label, icon: Icon }) =>
        <button key={id} className={`nav-item ${page === id ? 'active' : ''}`}
          disabled={id !== 'worlds' && id !== 'settings' && !currentWorld}
          onClick={() => navigate(id)}><Icon size={18} /><span>{label}</span>
          {id === 'chats' && <span className="nav-dot" />}</button>)}</nav>
      <div className="sidebar-bottom">
        <button className="button subtle small" onClick={() => {
          setDark(!dark); localStorage.setItem('openworld-theme', dark ? 'light' : 'dark')
        }}>{dark ? <Sun size={15} /> : <Moon size={15} />}{dark ? 'Helles Design' : 'Dunkles Design'}</button>
      </div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="breadcrumb"><span>OpenWorld</span><ChevronRight size={14} />
          <strong>{currentWorld && page !== 'worlds' && page !== 'settings' ? currentWorld.name : pageLabel}</strong>
        </div>
        <div className="version-badge">v0.3.1</div>
      </header>
      <div className="content">
        {(['chats', 'groups', 'simulations'].includes(page) || (page === 'worlds' &&
          (providerStatus.data?.state !== 'ready' || !provider.data?.model))) &&
          <section className="panel p-5 mb-5 space-y-3" aria-label="KI-Verbindung">
            {provider.error ? <p role="alert">{errorText(provider.error)}</p> :
              !provider.data ? <p>KI-Verbindung wird geladen …</p> :
                <p>{providerStatus.data?.message ?? (provider.data.model ? `KI-Modell: ${provider.data.model}` :
                  'Für Gespräche und Simulationen benötigst du eine KI-Verbindung. Wir helfen dir bei der Einrichtung.')}</p>}
            {providerStatus.error && <p role="alert">{errorText(providerStatus.error)}</p>}
            <button className="button" disabled={!provider.data} onClick={() => setSetupOpen(true)}>
              KI einrichten</button>
          </section>}
        {(error || worlds.error || relevantError || jobs.error) && <div className="error-banner" role="alert">
          <span>{error || errorText(worlds.error ?? relevantError ?? jobs.error)}</span>
          <button className="icon-button" aria-label="Fehler schliessen" onClick={() => setError('')}><X size={17} /></button>
        </div>}
        <div className="page-heading"><div>
          <h1>{page === 'locations' ? currentWorld?.name ?? 'Welteditor' : pageLabel}</h1>
          </div>
          {(page === 'worlds' || (currentWorld && ['locations', 'characters', 'relationships', 'knowledge'].includes(page))) &&
            <button className="button primary" disabled={moving || locationSaving} onClick={() => setEditor({ resource: page as Resource })}>
              <Plus size={17} />{page === 'worlds' ? 'Neue Welt' : page === 'locations' ? 'Neuer Ort' :
                page === 'characters' ? 'Neuer Charakter' : page === 'relationships' ? 'Neue Beziehung' : 'Neuer Wissenseintrag'}
            </button>}
        </div>
        {editor && editor.resource !== 'locations' ? <div className="editor-layout">
          <Editor key={`${editor.resource}-${editor.item?.id ?? 'new'}`}
            resource={editor.resource} item={editor.item} worldId={worldId}
            locations={locations.data ?? []} characters={characters.data ?? []}
            objects={objects} onSaved={saved} onCancel={() => setEditor(null)} report={setError} />
        </div> : <>
          {page === 'worlds' && <>
            <p className="muted text-sm mb-4">{worlds.data?.length ?? 0} {worlds.data?.length === 1 ? 'Welt' : 'Welten'}</p>
            {worlds.isPending && <p className="muted">Welten werden geladen ...</p>}
            <div className="world-grid">{worlds.data?.map((world, index) =>
              <article className="world-card panel" key={world.id}>
                <button className={`world-cover cover-${index % 3}`} onClick={() => openWorld(world)}
                  aria-label={`${world.name} öffnen`}><Globe2 size={48} /></button>
                <div className="p-5"><h3>{world.name}</h3><p className="muted line-clamp-2 min-h-10 mt-2">
                  {world.description || 'Keine Beschreibung.'}</p>
                  <div className="flex justify-between mt-5 gap-2">
                    <button className="button subtle small" onClick={() => setEditor({ resource: 'worlds', item: world })}>
                      Bearbeiten</button><button className="button small" onClick={() => openWorld(world)}>
                      Welt öffnen <ArrowRight size={14} /></button>
                  </div>
                </div>
              </article>)}</div>
            {worlds.data?.length === 0 && <Empty title="Keine Welten vorhanden"
              text="Über „Neue Welt“ eine Welt anlegen." />}
          </>}
          {currentWorld && page === 'locations' && <div className="world-editor-layout">
            <aside className="panel tree-panel"><div className="section-heading"><h3>Weltstruktur</h3><Map size={17} /></div>
              <LocationTree key={worldId} locations={locations.data ?? []} worldName={currentWorld.name}
                onWorldSelect={() => setEditor({ resource: 'worlds', item: currentWorld })}
                onMove={moveLocation} disabled={moving || locationSaving}
                selectedId={editor?.item?.id}
                onSelect={item => setEditor(current =>
                  current?.resource === 'locations' && current.item?.id === item.id ?
                    null : { resource: 'locations', item })}
                />
              <p role="status" className="tree-help">{moveStatus}</p></aside>
            {editor?.resource === 'locations' ? editedLocation || !editor.item ?
              <Editor key={editor.item?.id ?? 'new-location'} resource="locations" item={editedLocation}
                worldId={worldId} locations={locations.data ?? []} characters={characters.data ?? []}
                objects={objects} onSaved={saved} onCancel={() => setEditor(null)} report={setError}
                structureBusy={moving} onBusyChange={setLocationSaving} /> :
              <Empty title="Ort nicht mehr vorhanden" text="Der Ort wurde entfernt. Einen anderen Ort auswählen." /> :
              <section className="panel p-8">
              <h2>{currentWorld.name}</h2><p className="muted whitespace-pre-wrap my-5">{currentWorld.description}</p>
              <div className="stats-grid">{[
                [locations.data?.length ?? 0, 'Orte'], [characters.data?.length ?? 0, 'Charaktere'],
                [relationships.data?.length ?? 0, 'Beziehungen'],
              ].map(([count, label]) => <div key={label}><strong>{count}</strong><span>{label}</span></div>)}</div>
              <p className="muted mt-8">Ort zum Bearbeiten auswählen oder über „Neuer Ort“ anlegen.</p>
              <button className="button mt-5" onClick={() => setEditor({ resource: 'worlds', item: currentWorld })}>
                Weltbeschreibung bearbeiten</button>
            </section>}
          </div>}
          {currentWorld && page === 'characters' && <>
            <div className="world-grid">{characters.data?.map(character => <article key={character.id} className="panel character-card">
              <div className="avatar large">{character.name?.slice(0, 1)}</div>
              <h3>{character.name}</h3><p className="muted text-xs">
                {character.travel_status === 'traveling' ? 'Unterwegs' :
                  locations.data?.find(l => l.id === character.location_id)?.name ?? 'Standort unbekannt'}</p>
              <p className="muted my-4 line-clamp-3">{character.description || 'Keine Beschreibung.'}</p>
              <button className="button w-full justify-center" onClick={() =>
                setEditor({ resource: 'characters', item: character })}>Profil bearbeiten <ArrowRight size={14} /></button>
            </article>)}</div>
            {characters.data?.length === 0 && <Empty title="Keine Charaktere vorhanden"
              text="Über „Neuer Charakter“ einen Charakter anlegen." />}
          </>}
          {currentWorld && page === 'relationships' && <>
            <Suspense fallback={<p role="status">Beziehungsgraph wird geladen …</p>}>
              <RelationshipGraph characters={characters.data ?? []} relationships={relationships.data ?? []}
                edit={item => setEditor({ resource: 'relationships', item })} />
            </Suspense>
            <section className="panel p-5 mt-5">
            <div className="notice mb-5">Gerichtete Beziehungen: Werte sind unabhängig je Richtung.</div>
            <div className="table-scroll"><table><thead><tr><th>Von</th><th>Zu</th><th>Beziehung</th><th>Sichtbarkeit</th><th /></tr></thead>
              <tbody>{relationships.data?.map(r => <tr key={r.id}>
                <td>{characters.data?.find(c => c.id === r.source_id)?.name}</td>
                <td>{characters.data?.find(c => c.id === r.target_id)?.name}</td>
                <td>{r.kind}</td><td><span className="tag">{r.secret ? 'Geheim' : 'Öffentlich'}</span></td>
                <td><button className="button small" onClick={() => setEditor({ resource: 'relationships', item: r })}>Bearbeiten</button></td>
              </tr>)}</tbody></table></div>
            {relationships.data?.length === 0 && <Empty title="Keine Beziehungen vorhanden"
              text="Über „Neue Beziehung“ zwei Charaktere verknüpfen." />}
          </section></>}
          {currentWorld && page === 'knowledge' && <section className="space-y-4">
            <div className="panel p-5 flex flex-wrap items-center gap-3">
              <BookOpen size={18} /><label htmlFor="knowledge-filter">Wissensstand anzeigen:</label>
              <select id="knowledge-filter" className="max-w-xs" value={knowledgeFilter}
                onChange={e => setKnowledgeFilter(e.target.value)}>
                <option value="">Alle Einträge (Editoransicht)</option><option value="world">Objektive Weltfakten</option>
                {characters.data?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            {(knowledge.data ?? []).filter(k => !knowledgeFilter ||
              (knowledgeFilter === 'world' ? k.kind === 'fact' : k.character_id === knowledgeFilter))
              .map(k => <article className="panel p-5" key={k.id}>
                <div className="section-heading"><div className="flex flex-wrap gap-2">
                  <span className="tag">{knowledgeLabels[k.kind as KnowledgeKind]}</span>
                  <span className="muted text-sm">{characters.data?.find(c => c.id === k.character_id)?.name ??
                    (k.public ? 'Welt · öffentlich' : 'Welt · verborgen')}</span></div>
                  <button className="button small" onClick={() => setEditor({ resource: 'knowledge', item: k })}>Bearbeiten</button></div>
                <p className="whitespace-pre-wrap my-4">{k.content}</p>
                <p className="muted text-xs">Quelle: {k.source} · Vertrauen: {k.confidence} %
                  {k.created_at && ` · ${new Date(k.created_at).toLocaleString('de-DE')}`}</p>
              </article>)}
            {knowledge.data?.length === 0 && <Empty title="Keine Wissenseinträge vorhanden"
              text="Weltfakten oder persönliches Wissen über „Neuer Wissenseintrag“ anlegen." />}
          </section>}
          {currentWorld && page === 'events' && <Events key={worldId} worldId={worldId}
            characters={characters.data ?? []} locations={locations.data ?? []} report={setError}
            onSetup={() => setSetupOpen(true)} />}
          {currentWorld && page === 'chats' && <Chat key={worldId} worldId={worldId}
            characters={characters.data ?? []} report={setError} onEvents={() => navigate('events')} />}
          {currentWorld && (page === 'simulations' || page === 'groups') && <Ensemble
            key={`${worldId}:${page}`} worldId={worldId} simulation={page === 'simulations'}
            characters={characters.data ?? []} locations={locations.data ?? []}
            report={setError} onEvents={() => navigate('events')} />}
          {page === 'worlds' && <WorldTransfer report={setError} />}
          {currentWorld && page === 'locations' && <div className="mt-5">
            <WorldTransfer worldId={worldId} report={setError} /></div>}
          {page === 'settings' && <Settings report={setError} worldId={currentWorld?.id}
            onSetup={() => setSetupOpen(true)} />}
          {!currentWorld && page !== 'worlds' && page !== 'settings' && <Empty title="Wähle zuerst eine Welt."
            text="Öffne eine vorhandene Welt unter Meine Welten oder erstelle eine neue." />}
        </>}
        {page !== 'worlds' && <button className="button subtle small mt-8" onClick={() => navigate('worlds')}>
          <ArrowLeft size={14} /> Alle Welten</button>}
      </div>
    </main>
    {setupOpen && provider.data && <ConnectionSetup initial={provider.data} close={() => {
      setSetupOpen(false); setError('')
    }} />}
  </div>
}
