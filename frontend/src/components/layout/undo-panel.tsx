import { useEffect, useRef, useState } from "react"
import { Undo2 } from "lucide-react"
import { formatTimeAgo } from "@/lib/utils"
import { useUndo } from "@/hooks/use-undo"

const ACTION_STYLES: Record<string, string> = {
  create: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  update: "bg-brand/10 text-brand",
  delete: "bg-red-500/10 text-red-600 dark:text-red-400",
}

const ACTION_LABELS: Record<string, string> = {
  create: "Alta",
  update: "Edición",
  delete: "Baja",
}

/** Historial corto de cambios propios, cada uno con su botón de deshacer. */
export function UndoPanel() {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const { entries, undo, isUndoing, pendingId, refresh } = useUndo()

  // Al abrir, relee: entre medias el usuario ha estado trabajando.
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors"
        title="Deshacer cambios recientes (⌘Z)"
        aria-label="Deshacer cambios recientes"
        aria-expanded={open}
      >
        <Undo2 className="h-4 w-4" />
        {entries.length > 0 && (
          <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-brand" />
        )}
      </button>

      {open && (
        <div className="fixed right-4 top-14 w-80 max-w-[calc(100vw-2rem)] max-h-[calc(100vh-4rem)] overflow-auto rounded-xl border border-border bg-card shadow-xl z-50">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-sm font-semibold">Cambios recientes</span>
            <kbd className="px-1.5 py-0.5 text-[10px] font-mono bg-muted border border-border rounded text-muted-foreground">
              ⌘Z
            </kbd>
          </div>

          {entries.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              Aún no has hecho ningún cambio
            </div>
          ) : (
            <div>
              {entries.map((entry) => (
                <div
                  key={entry.id}
                  className="px-3 py-2.5 border-b border-border/50 flex items-start gap-2"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          ACTION_STYLES[entry.action] ?? "bg-muted text-muted-foreground"
                        }`}
                      >
                        {ACTION_LABELS[entry.action] ?? entry.action}
                      </span>
                      <span className="text-[10px] text-muted-foreground/70">
                        {formatTimeAgo(entry.created_at)}
                      </span>
                    </div>
                    <p className="text-sm mt-1 break-words">{entry.label}</p>
                    {entry.operation_count > 1 && (
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        y {entry.operation_count - 1}{" "}
                        {entry.operation_count === 2 ? "cambio más" : "cambios más"}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => undo(entry)}
                    disabled={isUndoing}
                    className="flex-shrink-0 mt-0.5 px-2 py-1 text-xs rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-brand hover:bg-brand/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isUndoing && pendingId === entry.id ? "…" : "Deshacer"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
