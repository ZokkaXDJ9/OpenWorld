import { Plus, X } from 'lucide-react'
import type { Attribute, Entity } from './types'
import { Field } from './ui'

const labels: Record<Attribute['type'], string> = {
  text: 'Text', number: 'Zahl', boolean: 'Ja / Nein', select: 'Auswahl',
  multiselect: 'Mehrfachauswahl', date: 'Datum', reference: 'Objektreferenz',
}

export function Attributes({
  value, onChange, objects,
}: { value: Attribute[]; onChange: (value: Attribute[]) => void; objects: Entity[] }) {
  function patch(index: number, change: Partial<Attribute>) {
    onChange(value.map((attribute, i) => i === index ? { ...attribute, ...change } : attribute))
  }
  return <section className="space-y-3">
    <div className="section-heading"><h3>Eigene Attribute</h3>
      <button type="button" className="button small" onClick={() => onChange([...value, {
        name: '', type: 'text', value: '', options: [],
      }])}><Plus size={14} /> Feld hinzufügen</button></div>
    {!value.length && <p className="muted text-sm">Optionale Felder bei Bedarf hinzufügen.</p>}
    {value.map((attribute, index) => <div key={index} className="attribute-row">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Feldname"><input required value={attribute.name}
          onChange={e => patch(index, { name: e.target.value })} /></Field>
        <Field label="Feldtyp"><select value={attribute.type} onChange={e => {
          const type = e.target.value as Attribute['type']
          patch(index, {
            type, value: type === 'boolean' ? false : type === 'number' ? 0 :
              type === 'multiselect' ? [] : type === 'select' ? attribute.options[0] ?? '' : '',
          })
        }}>{Object.entries(labels).map(([key, label]) =>
          <option key={key} value={key}>{label}</option>)}</select></Field>
      </div>
      {(attribute.type === 'select' || attribute.type === 'multiselect') &&
        <Field label="Optionen (durch Komma getrennt)"><input value={attribute.options.join(', ')}
          onChange={e => {
            const options = e.target.value.split(',').map(s => s.trim())
            patch(index, {
              options, value: attribute.type === 'select' ? options[0] ?? '' : [],
            })
          }} /></Field>}
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <Field label="Wert">
            {attribute.type === 'boolean' ? <select value={String(attribute.value)}
              onChange={e => patch(index, { value: e.target.value === 'true' })}>
              <option value="false">Nein</option><option value="true">Ja</option></select>
              : attribute.type === 'reference' ? <select required value={String(attribute.value)}
                onChange={e => patch(index, { value: e.target.value })}>
                <option value="">Objekt wählen</option>{objects.map(o =>
                  <option key={o.id} value={o.id}>{o.name ?? o.content ?? o.kind}</option>)}</select>
              : attribute.type === 'select' ? <select value={String(attribute.value)}
                onChange={e => patch(index, { value: e.target.value })}>
                {attribute.options.map((option, i) =>
                  <option key={i} value={option}>{option}</option>)}</select>
              : attribute.type === 'multiselect' ? <select multiple
                value={Array.isArray(attribute.value) ? attribute.value : []}
                onChange={e => patch(index, {
                  value: Array.from(e.target.selectedOptions, o => o.value),
                })}>{attribute.options.map((option, i) =>
                  <option key={i} value={option}>{option}</option>)}</select>
              : <input required type={attribute.type === 'date' ? 'date' :
                attribute.type === 'number' ? 'number' : 'text'}
                step={attribute.type === 'number' ? 'any' : undefined}
                min={attribute.minimum ?? undefined} max={attribute.maximum ?? undefined}
                value={String(attribute.value)} onChange={e => patch(index, {
                  value: attribute.type === 'number' ? Number(e.target.value) : e.target.value,
                })} />}
          </Field>
        </div>
        <button className="icon-button" type="button" aria-label={`Feld ${attribute.name} entfernen`}
          onClick={() => onChange(value.filter((_, i) => i !== index))}><X size={17} /></button>
      </div>
      {attribute.type === 'number' && <div className="grid grid-cols-2 gap-3">
        <Field label="Minimum (optional)"><input type="number" step="any"
          value={attribute.minimum ?? ''} onChange={e => patch(index, {
            minimum: e.target.value === '' ? null : Number(e.target.value),
          })} /></Field>
        <Field label="Maximum (optional)"><input type="number" step="any"
          value={attribute.maximum ?? ''} onChange={e => patch(index, {
            maximum: e.target.value === '' ? null : Number(e.target.value),
          })} /></Field>
      </div>}
    </div>)}
  </section>
}
