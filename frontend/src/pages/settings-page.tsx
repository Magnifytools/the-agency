import { useState, useEffect, useCallback } from "react"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"
import { usersApi } from "@/lib/api"
import { DEFAULT_SHORTCUTS, SHORTCUT_LABELS } from "@/hooks/use-keyboard-shortcuts"

function formatBinding(binding: string): string {
  return binding
    .replace("Ctrl", "⌃")
    .replace("Cmd", "⌘")
    .replace("Shift", "⇧")
    .replace("Alt", "⌥")
}

interface EditingState {
  key: string
  captured: string | null
}

export default function SettingsPage() {
  const { user, refreshUser } = useAuth()
  const [bindings, setBindings] = useState<Record<string, string>>({
    ...DEFAULT_SHORTCUTS,
    ...(user?.preferences?.shortcuts ?? {}),
  })
  const [editing, setEditing] = useState<EditingState | null>(null)
  const [saving, setSaving] = useState(false)

  // Sync with user preferences when they load
  useEffect(() => {
    setBindings({ ...DEFAULT_SHORTCUTS, ...(user?.preferences?.shortcuts ?? {}) })
  }, [user?.preferences?.shortcuts])

  const startCapture = useCallback((key: string) => {
    setEditing({ key, captured: null })
  }, [])

  const cancelCapture = useCallback(() => {
    setEditing(null)
  }, [])

  useEffect(() => {
    if (!editing) return

    const handler = (e: KeyboardEvent) => {
      e.preventDefault()
      e.stopPropagation()

      if (e.key === "Escape") {
        setEditing(null)
        return
      }

      // Build the shortcut string from the event
      const parts: string[] = []
      if (e.ctrlKey) parts.push("Ctrl")
      if (e.metaKey) parts.push("Ctrl") // normalize meta → Ctrl in storage
      if (e.shiftKey) parts.push("Shift")
      if (e.altKey) parts.push("Alt")

      // Ignore modifier-only keypresses
      if (["Control", "Meta", "Shift", "Alt"].includes(e.key)) return

      parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key)
      const shortcut = parts.join("+")

      setEditing((prev) => (prev ? { ...prev, captured: shortcut } : null))
    }

    window.addEventListener("keydown", handler, { capture: true })
    return () => window.removeEventListener("keydown", handler, { capture: true })
  }, [editing?.key])

  const confirmCapture = () => {
    if (!editing?.captured) return
    setBindings((prev) => ({ ...prev, [editing.key]: editing.captured! }))
    setEditing(null)
  }

  const resetDefaults = () => {
    setBindings({ ...DEFAULT_SHORTCUTS })
  }

  const handleSave = async () => {
    if (!user) return
    setSaving(true)
    try {
      await usersApi.update(user.id, {
        preferences: { ...(user.preferences ?? {}), shortcuts: bindings },
      })
      await refreshUser()
      toast.success("Atajos guardados")
    } catch (err) {
      console.error(err)
      toast.error("Error al guardar los atajos")
    } finally {
      setSaving(false)
    }
  }

  const shortcutKeys = Object.keys(DEFAULT_SHORTCUTS)

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Configuración</h1>
        <p className="text-muted-foreground mt-1">Personaliza tu experiencia en The Agency</p>
      </div>

      <div className="bg-card border border-border rounded-2xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-base font-semibold text-foreground">Atajos de teclado</h2>
            <p className="text-sm text-muted-foreground mt-0.5">Haz clic en Editar para capturar un nuevo atajo</p>
          </div>
          <button
            onClick={resetDefaults}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
          >
            Restaurar por defecto
          </button>
        </div>

        <div className="divide-y divide-border">
          {shortcutKeys.map((key) => {
            const isEditing = editing?.key === key
            const binding = bindings[key] ?? DEFAULT_SHORTCUTS[key]

            return (
              <div key={key} className="flex items-center justify-between py-3.5 gap-4">
                <span className="text-sm text-foreground font-medium">{SHORTCUT_LABELS[key]}</span>

                <div className="flex items-center gap-3 flex-shrink-0">
                  {isEditing ? (
                    <div className="flex items-center gap-2">
                      <div className="min-w-[140px] px-3 py-1.5 bg-brand/10 border border-brand rounded-lg text-sm font-mono text-center text-brand">
                        {editing.captured ? formatBinding(editing.captured) : "Presiona una tecla…"}
                      </div>
                      {editing.captured && (
                        <button
                          onClick={confirmCapture}
                          className="text-xs px-2.5 py-1 bg-brand text-black rounded-lg font-medium hover:bg-brand/90 transition-colors"
                        >
                          OK
                        </button>
                      )}
                      <button
                        onClick={cancelCapture}
                        className="text-xs px-2.5 py-1 bg-muted text-muted-foreground rounded-lg hover:text-foreground transition-colors"
                      >
                        Cancelar
                      </button>
                    </div>
                  ) : (
                    <>
                      <kbd className="inline-flex items-center px-2 py-1 text-[12px] font-mono bg-muted border border-border rounded-lg text-foreground min-w-[60px] justify-center">
                        {formatBinding(binding)}
                      </kbd>
                      <button
                        onClick={() => startCapture(key)}
                        className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
                      >
                        Editar
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {saving ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </div>
    </div>
  )
}
