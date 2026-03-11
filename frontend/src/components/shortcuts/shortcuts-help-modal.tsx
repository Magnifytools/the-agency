import { Dialog, DialogHeader, DialogTitle, DialogContent } from "@/components/ui/dialog"
import { DEFAULT_SHORTCUTS, SHORTCUT_LABELS } from "@/hooks/use-keyboard-shortcuts"

interface ShortcutsHelpModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  shortcuts?: Record<string, string>
}

function KbdSequence({ binding }: { binding: string }) {
  // Handle chord shortcuts like G+D
  const parts = binding.split("+")
  if (parts.length === 1) {
    return <kbd className="inline-flex items-center px-1.5 py-0.5 text-[11px] font-mono bg-muted border border-border rounded text-foreground">{binding}</kbd>
  }
  return (
    <span className="inline-flex items-center gap-1">
      {parts.map((part, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-muted-foreground text-[11px]">+</span>}
          <kbd className="inline-flex items-center px-1.5 py-0.5 text-[11px] font-mono bg-muted border border-border rounded text-foreground">
            {part === "Ctrl" ? "⌃" : part === "Cmd" ? "⌘" : part}
          </kbd>
        </span>
      ))}
    </span>
  )
}

const NAV_SHORTCUTS = ["goto_dashboard", "goto_inbox", "goto_timesheet", "goto_clients", "goto_projects", "goto_tasks", "goto_leads"]
const ACTION_SHORTCUTS = ["search", "capture", "new_entry", "show_shortcuts"]

export function ShortcutsHelpModal({ open, onOpenChange, shortcuts = DEFAULT_SHORTCUTS }: ShortcutsHelpModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Atajos de teclado</DialogTitle>
      </DialogHeader>
      <DialogContent>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3">Navegación</p>
            <div className="flex flex-col gap-2">
              {NAV_SHORTCUTS.map((key) => (
                <div key={key} className="flex items-center justify-between gap-4">
                  <span className="text-sm text-foreground">{SHORTCUT_LABELS[key]}</span>
                  <KbdSequence binding={shortcuts[key] ?? ""} />
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3">Acciones</p>
            <div className="flex flex-col gap-2">
              {ACTION_SHORTCUTS.map((key) => (
                <div key={key} className="flex items-center justify-between gap-4">
                  <span className="text-sm text-foreground">{SHORTCUT_LABELS[key]}</span>
                  <KbdSequence binding={shortcuts[key] ?? ""} />
                </div>
              ))}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-4">
          Personaliza estos atajos en <a href="/settings" className="underline hover:text-foreground">Configuración</a>.
        </p>
      </DialogContent>
    </Dialog>
  )
}
