import { useState, useEffect, useCallback } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"
import { usersApi, categoriesApi, myWeekApi } from "@/lib/api"
import { DEFAULT_SHORTCUTS, SHORTCUT_LABELS } from "@/hooks/use-keyboard-shortcuts"
import { Pencil, Trash2, Plus, Check, X, MapPin, Calendar, FileText, Bell } from "lucide-react"

const SPAIN_REGIONS: { code: string; name: string }[] = [
  { code: "AND", name: "Andalucía" },
  { code: "ARA", name: "Aragón" },
  { code: "AST", name: "Asturias" },
  { code: "BAL", name: "Islas Baleares" },
  { code: "CAN", name: "Canarias" },
  { code: "CAB", name: "Cantabria" },
  { code: "CLM", name: "Castilla-La Mancha" },
  { code: "CYL", name: "Castilla y León" },
  { code: "CAT", name: "Cataluña" },
  { code: "EXT", name: "Extremadura" },
  { code: "GAL", name: "Galicia" },
  { code: "MAD", name: "Comunidad de Madrid" },
  { code: "MUR", name: "Región de Murcia" },
  { code: "NAV", name: "Navarra" },
  { code: "PVA", name: "País Vasco" },
  { code: "RIO", name: "La Rioja" },
  { code: "VAL", name: "Comunidad Valenciana" },
  { code: "CEU", name: "Ceuta" },
  { code: "MEL", name: "Melilla" },
]

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
  const queryClient = useQueryClient()
  const { user, refreshUser, isAdmin, hasPermission } = useAuth()
  const canManageCategories = isAdmin || hasPermission("tasks", true)
  const [bindings, setBindings] = useState<Record<string, string>>({
    ...DEFAULT_SHORTCUTS,
    ...(user?.preferences?.shortcuts ?? {}),
  })
  const [editing, setEditing] = useState<EditingState | null>(null)
  const [saving, setSaving] = useState(false)

  // Category management state
  const [newCatName, setNewCatName] = useState("")
  const [newCatMinutes, setNewCatMinutes] = useState(60)
  const [editingCatId, setEditingCatId] = useState<number | null>(null)
  const [editCatName, setEditCatName] = useState("")
  const [editCatMinutes, setEditCatMinutes] = useState(60)

  // Location state
  const [userRegion, setUserRegion] = useState(user?.region ?? "")
  const [userLocality, setUserLocality] = useState(user?.locality ?? "")
  const [savingLocation, setSavingLocation] = useState(false)

  // Holiday management state
  const [newHolidayDate, setNewHolidayDate] = useState("")
  const [newHolidayName, setNewHolidayName] = useState("")
  const [newHolidayRegion, setNewHolidayRegion] = useState("")
  const [newHolidayLocality, setNewHolidayLocality] = useState("")
  const currentYear = new Date().getFullYear()

  // Digest settings state
  const [digestTone, setDigestTone] = useState(user?.preferences?.digest_default_tone ?? "cercano")
  const [digestRecipients, setDigestRecipients] = useState(user?.preferences?.digest_default_recipients ?? "")
  const [digestAutoSend, setDigestAutoSend] = useState(user?.preferences?.digest_auto_send ?? "manual")
  const [savingDigest, setSavingDigest] = useState(false)

  // Notification preferences state
  const [notifEmail, setNotifEmail] = useState(user?.preferences?.notifications_email ?? true)
  const [notifDiscord, setNotifDiscord] = useState(user?.preferences?.notifications_discord ?? true)
  const [savingNotif, setSavingNotif] = useState(false)

  // Sync with user preferences when they load
  useEffect(() => {
    setBindings({ ...DEFAULT_SHORTCUTS, ...(user?.preferences?.shortcuts ?? {}) })
  }, [user?.preferences?.shortcuts])

  useEffect(() => {
    setDigestTone(user?.preferences?.digest_default_tone ?? "cercano")
    setDigestRecipients(user?.preferences?.digest_default_recipients ?? "")
    setDigestAutoSend(user?.preferences?.digest_auto_send ?? "manual")
    setNotifEmail(user?.preferences?.notifications_email ?? true)
    setNotifDiscord(user?.preferences?.notifications_discord ?? true)
  }, [user?.preferences])

  useEffect(() => {
    setUserRegion(user?.region ?? "")
    setUserLocality(user?.locality ?? "")
  }, [user?.region, user?.locality])

  const { data: holidays = [], refetch: refetchHolidays } = useQuery({
    queryKey: ["holidays", currentYear],
    queryFn: () => myWeekApi.listHolidays(currentYear),
    enabled: isAdmin,
  })

  const saveLocationMut = useMutation({
    mutationFn: () => usersApi.update(user!.id, { region: userRegion || null, locality: userLocality || null }),
    onSuccess: async () => {
      await refreshUser()
      toast.success("Ubicación guardada")
      setSavingLocation(false)
    },
    onError: () => { toast.error("Error al guardar ubicación"); setSavingLocation(false) },
  })

  const createHolidayMut = useMutation({
    mutationFn: (data: { date: string; name: string; region?: string | null; locality?: string | null }) =>
      myWeekApi.createHoliday(data),
    onSuccess: () => {
      refetchHolidays()
      setNewHolidayDate("")
      setNewHolidayName("")
      setNewHolidayRegion("")
      setNewHolidayLocality("")
      toast.success("Festivo creado")
    },
    onError: () => toast.error("Error al crear festivo"),
  })

  const deleteHolidayMut = useMutation({
    mutationFn: (id: number) => myWeekApi.deleteHoliday(id),
    onSuccess: () => { refetchHolidays(); toast.success("Festivo eliminado") },
    onError: () => toast.error("Error al eliminar festivo"),
  })

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
    } catch {
      toast.error("Error al guardar los atajos")
    } finally {
      setSaving(false)
    }
  }

  const handleSaveDigestSettings = async () => {
    if (!user) return
    setSavingDigest(true)
    try {
      await usersApi.update(user.id, {
        preferences: {
          ...(user.preferences ?? {}),
          digest_default_tone: digestTone,
          digest_default_recipients: digestRecipients,
          digest_auto_send: digestAutoSend,
        },
      })
      await refreshUser()
      toast.success("Preferencias de digest guardadas")
    } catch {
      toast.error("Error al guardar preferencias de digest")
    } finally {
      setSavingDigest(false)
    }
  }

  const handleSaveNotifSettings = async () => {
    if (!user) return
    setSavingNotif(true)
    try {
      await usersApi.update(user.id, {
        preferences: {
          ...(user.preferences ?? {}),
          notifications_email: notifEmail,
          notifications_discord: notifDiscord,
        },
      })
      await refreshUser()
      toast.success("Preferencias de notificación guardadas")
    } catch {
      toast.error("Error al guardar preferencias de notificación")
    } finally {
      setSavingNotif(false)
    }
  }

  // Categories queries & mutations
  const { data: categories = [] } = useQuery({
    queryKey: ["task-categories"],
    queryFn: () => categoriesApi.list(),
    enabled: canManageCategories,
  })

  const createCatMut = useMutation({
    mutationFn: (data: { name: string; default_minutes: number }) => categoriesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task-categories"] })
      setNewCatName("")
      setNewCatMinutes(60)
      toast.success("Categoría creada")
    },
    onError: () => toast.error("Error al crear categoría"),
  })

  const updateCatMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name?: string; default_minutes?: number } }) =>
      categoriesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task-categories"] })
      setEditingCatId(null)
      toast.success("Categoría actualizada")
    },
    onError: () => toast.error("Error al actualizar categoría"),
  })

  const deleteCatMut = useMutation({
    mutationFn: (id: number) => categoriesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task-categories"] })
      toast.success("Categoría eliminada")
    },
    onError: () => toast.error("Error al eliminar. ¿Tiene tareas asociadas?"),
  })

  const shortcutKeys = Object.keys(DEFAULT_SHORTCUTS)

  const sections = [
    { id: "shortcuts", label: "Atajos de teclado" },
    ...(canManageCategories ? [{ id: "categories", label: "Categorías de tareas" }] : []),
    { id: "location", label: "Ubicación" },
    { id: "digest", label: "Preferencias de digest" },
    { id: "notifications", label: "Notificaciones" },
    ...(isAdmin ? [{ id: "holidays", label: "Festivos" }] : []),
  ]

  return (
    <div className="flex gap-8 max-w-4xl mx-auto">
      {/* Sidebar nav */}
      <nav className="hidden md:block w-48 shrink-0 sticky top-8 self-start space-y-1">
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="block px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-lg transition-colors"
          >
            {s.label}
          </a>
        ))}
      </nav>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Configuración</h1>
        <p className="text-muted-foreground mt-1">Personaliza tu experiencia en The Agency</p>
      </div>

      {/* Keyboard shortcuts */}
      <div id="shortcuts" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
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

      {/* Task categories — admin or users with tasks write permission */}
      {canManageCategories && (
        <div id="categories" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
          <div className="mb-6">
            <h2 className="text-base font-semibold text-foreground">Categorías de tareas</h2>
            <p className="text-sm text-muted-foreground mt-0.5">Gestiona las categorías disponibles para clasificar tareas</p>
          </div>

          <div className="divide-y divide-border">
            {categories.map((cat) => {
              const isEditingThis = editingCatId === cat.id
              return (
                <div key={cat.id} className="flex items-center justify-between py-3 gap-4">
                  {isEditingThis ? (
                    <div className="flex items-center gap-2 flex-1">
                      <input
                        className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                        value={editCatName}
                        onChange={(e) => setEditCatName(e.target.value)}
                        autoFocus
                      />
                      <input
                        className="w-20 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-center"
                        type="number"
                        min="1"
                        value={editCatMinutes}
                        onChange={(e) => setEditCatMinutes(Number(e.target.value))}
                      />
                      <span className="text-xs text-muted-foreground">min</span>
                      <button
                        onClick={() => updateCatMut.mutate({ id: cat.id, data: { name: editCatName, default_minutes: editCatMinutes } })}
                        className="p-1.5 text-green-600 hover:bg-green-50 rounded-md transition-colors"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => setEditingCatId(null)}
                        className="p-1.5 text-muted-foreground hover:bg-muted rounded-md transition-colors"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="flex-1">
                        <span className="text-sm text-foreground font-medium">{cat.name}</span>
                        <span className="text-xs text-muted-foreground ml-2">{cat.default_minutes} min</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { setEditingCatId(cat.id); setEditCatName(cat.name); setEditCatMinutes(cat.default_minutes) }}
                          className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => { if (confirm(`¿Eliminar "${cat.name}"?`)) deleteCatMut.mutate(cat.id) }}
                          className="p-1.5 text-muted-foreground hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>

          {/* Add new category */}
          <div className="mt-4 flex items-center gap-2">
            <input
              className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              placeholder="Nueva categoría..."
              value={newCatName}
              onChange={(e) => setNewCatName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newCatName.trim()) {
                  e.preventDefault()
                  createCatMut.mutate({ name: newCatName.trim(), default_minutes: newCatMinutes })
                }
              }}
            />
            <input
              className="w-20 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-center"
              type="number"
              min="1"
              value={newCatMinutes}
              onChange={(e) => setNewCatMinutes(Number(e.target.value))}
              placeholder="min"
            />
            <span className="text-xs text-muted-foreground">min</span>
            <button
              onClick={() => newCatName.trim() && createCatMut.mutate({ name: newCatName.trim(), default_minutes: newCatMinutes })}
              disabled={!newCatName.trim() || createCatMut.isPending}
              className="p-1.5 bg-brand text-black rounded-md hover:bg-brand/90 transition-colors disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Location / Region */}
      <div id="location" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
        <div className="flex items-center gap-2 mb-4">
          <MapPin className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold text-foreground">Ubicación</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Tu comunidad autónoma y localidad determinan qué festivos te aplican
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Comunidad Autónoma</label>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={userRegion}
              onChange={(e) => setUserRegion(e.target.value)}
            >
              <option value="">— Sin especificar —</option>
              {SPAIN_REGIONS.map((r) => (
                <option key={r.code} value={r.code}>{r.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Localidad</label>
            <input
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              placeholder="Ej: Madrid, Barcelona..."
              value={userLocality}
              onChange={(e) => setUserLocality(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => { setSavingLocation(true); saveLocationMut.mutate() }}
            disabled={savingLocation}
            className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {savingLocation ? "Guardando…" : "Guardar ubicación"}
          </button>
        </div>
      </div>

      {/* Digest settings */}
      <div id="digest" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
        <div className="flex items-center gap-2 mb-4">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold text-foreground">Preferencias de digest</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Configura los valores por defecto para la generación y envío de digests
        </p>

        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Tono por defecto</label>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={digestTone}
              onChange={(e) => setDigestTone(e.target.value)}
            >
              <option value="cercano">Cercano</option>
              <option value="formal">Formal</option>
              <option value="equipo">Equipo</option>
            </select>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Destinatarios por defecto</label>
            <input
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              placeholder="email1@ejemplo.com, email2@ejemplo.com"
              value={digestRecipients}
              onChange={(e) => setDigestRecipients(e.target.value)}
            />
            <p className="text-xs text-muted-foreground mt-1">Separa múltiples emails con comas</p>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Envío automático</label>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={digestAutoSend}
              onChange={(e) => setDigestAutoSend(e.target.value)}
            >
              <option value="manual">Manual (requiere confirmación)</option>
              <option value="weekly_monday">Semanal — Lunes por la mañana</option>
              <option value="weekly_friday">Semanal — Viernes por la tarde</option>
              <option value="biweekly">Quincenal</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            onClick={handleSaveDigestSettings}
            disabled={savingDigest}
            className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {savingDigest ? "Guardando…" : "Guardar preferencias"}
          </button>
        </div>
      </div>

      {/* Notification preferences */}
      <div id="notifications" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
        <div className="flex items-center gap-2 mb-4">
          <Bell className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold text-foreground">Notificaciones</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Controla cómo y dónde recibes notificaciones
        </p>

        <div className="space-y-4">
          <div className="flex items-center justify-between py-2">
            <div>
              <span className="text-sm text-foreground font-medium">Notificaciones por email</span>
              <p className="text-xs text-muted-foreground mt-0.5">Recibe alertas y resúmenes por correo electrónico</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={notifEmail}
                onChange={(e) => setNotifEmail(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-brand transition-colors after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
            </label>
          </div>

          <div className="border-t border-border" />

          <div className="flex items-center justify-between py-2">
            <div>
              <span className="text-sm text-foreground font-medium">Notificaciones por Discord</span>
              <p className="text-xs text-muted-foreground mt-0.5">Recibe alertas en el canal de Discord configurado</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={notifDiscord}
                onChange={(e) => setNotifDiscord(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-brand transition-colors after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
            </label>
          </div>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            onClick={handleSaveNotifSettings}
            disabled={savingNotif}
            className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {savingNotif ? "Guardando…" : "Guardar notificaciones"}
          </button>
        </div>
      </div>

      {/* Holiday management — admin only */}
      {isAdmin && (
        <div id="holidays" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
          <div className="flex items-center gap-2 mb-4">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">Festivos {currentYear}</h2>
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            Los nacionales se aplican a todos. Los regionales/locales solo a usuarios de esa zona.
          </p>

          <div className="divide-y divide-border max-h-80 overflow-y-auto">
            {holidays.map((h) => (
              <div key={h.id} className="flex items-center justify-between py-2.5 gap-3">
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-foreground">{h.name}</span>
                  <span className="text-xs text-muted-foreground ml-2">
                    {new Date(h.date + "T00:00:00").toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
                  </span>
                  {h.region && (
                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-600">
                      {SPAIN_REGIONS.find((r) => r.code === h.region)?.name ?? h.region}
                    </span>
                  )}
                  {h.locality && (
                    <span className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-500/10 text-purple-600">
                      {h.locality}
                    </span>
                  )}
                  {!h.region && (
                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-600">
                      Nacional
                    </span>
                  )}
                </div>
                <button
                  onClick={() => { if (confirm(`¿Eliminar "${h.name}"?`)) deleteHolidayMut.mutate(h.id) }}
                  className="p-1.5 text-muted-foreground hover:text-red-600 hover:bg-red-50 rounded-md transition-colors flex-shrink-0"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {holidays.length === 0 && (
              <p className="py-4 text-sm text-muted-foreground text-center">No hay festivos configurados</p>
            )}
          </div>

          {/* Add new holiday */}
          <div className="mt-4 pt-4 border-t border-border space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input
                type="date"
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                value={newHolidayDate}
                onChange={(e) => setNewHolidayDate(e.target.value)}
              />
              <input
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                placeholder="Nombre del festivo"
                value={newHolidayName}
                onChange={(e) => setNewHolidayName(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-3 gap-3 items-end">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Ámbito</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                  value={newHolidayRegion}
                  onChange={(e) => setNewHolidayRegion(e.target.value)}
                >
                  <option value="">Nacional</option>
                  {SPAIN_REGIONS.map((r) => (
                    <option key={r.code} value={r.code}>{r.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Localidad (opcional)</label>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                  placeholder="Dejar vacío = toda la CCAA"
                  value={newHolidayLocality}
                  onChange={(e) => setNewHolidayLocality(e.target.value)}
                  disabled={!newHolidayRegion}
                />
              </div>
              <button
                onClick={() => {
                  if (!newHolidayDate || !newHolidayName.trim()) return
                  createHolidayMut.mutate({
                    date: newHolidayDate,
                    name: newHolidayName.trim(),
                    region: newHolidayRegion || null,
                    locality: newHolidayLocality || null,
                  })
                }}
                disabled={!newHolidayDate || !newHolidayName.trim() || createHolidayMut.isPending}
                className="px-3 py-1.5 bg-brand text-black text-sm font-semibold rounded-lg hover:bg-brand/90 transition-colors disabled:opacity-50 flex items-center gap-1.5 justify-center"
              >
                <Plus className="h-4 w-4" /> Añadir
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </div>
  )
}
