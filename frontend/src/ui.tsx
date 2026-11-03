import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { Trash2 } from 'lucide-react'
import { cloneElement, useId, useState } from 'react'
import type { ReactElement, ReactNode } from 'react'

export function Field({ label, children }: {
  label: string; children: ReactElement<{ id?: string }>
}) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label>
    {cloneElement(children, { id })}</div>
}

export function ConfirmButton({
  title, description, onConfirm, children, disabled = false, destructive = true,
}: {
  title: string; description: string; onConfirm: () => Promise<void> | void
  children?: ReactNode; disabled?: boolean; destructive?: boolean
}) {
  const [open, setOpen] = useState(false)
  return <AlertDialog.Root open={open} onOpenChange={setOpen}>
    <AlertDialog.Trigger asChild>
      <button type="button" className={destructive ? 'button danger subtle' : 'button'}
        disabled={disabled}>{children ?? <><Trash2 size={15} /> Löschen</>}</button>
    </AlertDialog.Trigger>
    <AlertDialog.Portal>
      <AlertDialog.Overlay className="dialog-overlay" />
      <AlertDialog.Content className="dialog-content">
        <AlertDialog.Title className="text-xl font-semibold">{title}</AlertDialog.Title>
        <AlertDialog.Description className="muted my-4">{description}</AlertDialog.Description>
        <div className="flex justify-end gap-3">
          <AlertDialog.Cancel asChild><button className="button">Abbrechen</button></AlertDialog.Cancel>
          <AlertDialog.Action asChild><button className={`button ${destructive ? 'danger' : 'primary'}`}
            onClick={() => { void onConfirm() }}>Bestätigen</button></AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Portal>
  </AlertDialog.Root>
}

export function Empty({ title, text }: { title: string; text: string }) {
  return <div className="empty"><h3>{title}</h3><p>{text}</p></div>
}
