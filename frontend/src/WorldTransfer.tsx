import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, errorText } from './api'
import type { Entity } from './types'

export function WorldTransfer({ worldId, report }: {
  worldId?: string; report: (error: string) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  async function exportWorld() {
    setBusy(true); report(''); setResult('')
    try {
      const data = await api<unknown>(`/worlds/${worldId}/export`)
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)],
        { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url; link.download = `openworld-${worldId}.json`; link.click()
      URL.revokeObjectURL(url)
      setResult('Weltexport heruntergeladen.')
    } catch (error) { report(errorText(error)) }
    finally { setBusy(false) }
  }
  async function importWorld(file: File) {
    setBusy(true); report(''); setResult('')
    try {
      if (file.size > 50000000) throw new Error('Weltexport ist zu groß (höchstens 50 MB).')
      const world = await api<Entity>('/worlds/import', 'POST', JSON.parse(await file.text()))
      await client.invalidateQueries({ queryKey: ['worlds'] })
      setResult(`Welt „${world.name}“ importiert. Vorhandene Daten wurden nicht überschrieben.`)
    } catch (error) { report(errorText(error)) }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  return <section className="panel p-5 mb-5">
    <div className="flex flex-wrap gap-3">
      {worldId && <button className="button" disabled={busy} onClick={() => void exportWorld()}>
        Welt exportieren</button>}
      <button className="button" disabled={busy} onClick={() => input.current?.click()}>
        Welt importieren</button>
      <input ref={input} type="file" accept=".json,application/json" hidden aria-label="Weltexport auswählen"
        onChange={event => { const file = event.target.files?.[0]; if (file) void importWorld(file) }} />
    </div>
    <p className="muted text-xs mt-3">JSON einschließlich privatem Wissen, Verläufen und Simulationen.
      Sicher aufbewahren. Keine Providerzugänge oder lokalen Laufzeiteinstellungen.
      Vor dem Export pausieren. Identitätskonflikte werden ohne Überschreiben abgelehnt.</p>
    {result && <p role="status" className="mt-3">{result}</p>}
  </section>
}
