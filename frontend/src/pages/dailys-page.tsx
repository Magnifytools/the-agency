import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { format, parseISO } from "date-fns"
import { es } from "date-fns/locale"
import { ChevronDown, ChevronUp, Loader2, MessageCircle, Pencil, RefreshCw, Trash2, Wand2 } from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { DeliveryReceipts, deliveryToast } from "@/components/delivery-receipts"
import { DailyFactPicker } from "@/components/dailys/daily-fact-picker"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useAuth } from "@/context/auth-context"
import { useBusinessDate } from "@/hooks/use-business-date"
import { dailysApi } from "@/lib/api"
import { isEnabled } from "@/lib/hidden-modules"
import type { DailyFact, DailyUpdate } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"

type LocalDraft = {
  rawText: string
  sourceFactKeys: string[]
  sourceFacts: DailyFact[]
  baseId: number | null
  baseRevision: number | null
}
type Editor = { draft: LocalDraft; base: DailyUpdate | null }
const emptyDraft = (): LocalDraft => ({ rawText: "", sourceFactKeys: [], sourceFacts: [], baseId: null, baseRevision: null })
const storageKey = (userId: number, date: string) => `agency:daily-closing:${userId}:${date}`
const dayKey = (userId: number, date: string) => ["dailys", userId, "for-date", date] as const
const factKinds = new Set(["task_completed", "time_logged", "task_advanced", "task_waiting", "next_step"])

function readDraft(userId: number, date: string): LocalDraft | null {
  try {
    const stored = localStorage.getItem(storageKey(userId, date))
    if (!stored) return null
    const value = JSON.parse(stored) as LocalDraft
    if (!value || typeof value.rawText !== "string" || !Array.isArray(value.sourceFactKeys) ||
      !value.sourceFactKeys.every((key) => typeof key === "string") || !Array.isArray(value.sourceFacts) ||
      !value.sourceFacts.every((fact) => fact && typeof fact.key === "string" && typeof fact.title === "string" && factKinds.has(fact.kind))) return null
    return { ...value, baseId: typeof value.baseId === "number" ? value.baseId : null, baseRevision: typeof value.baseRevision === "number" ? value.baseRevision : null }
  } catch { return null }
}
function fromDaily(daily: DailyUpdate): LocalDraft {
  return { rawText: daily.raw_text, sourceFactKeys: (daily.source_facts ?? []).map((fact) => fact.key), sourceFacts: daily.source_facts ?? [], baseId: daily.id, baseRevision: daily.revision }
}
function currentConflict(error: unknown): DailyUpdate | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return detail && typeof detail === "object" && "current" in detail ? (detail as { current: DailyUpdate }).current : null
}
function dailyError(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message
  if (detail && typeof detail === "object" && "current" in detail) return "Hay otra versión guardada. Tus notas locales se conservan."
  return getErrorMessage(error, fallback)
}
function useLiveInstance() {
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  return live
}
function useSourceAccess() {
  const { hasPermission } = useAuth()
  return isEnabled("tasks") && hasPermission("tasks")
}

export default function DailysPage() {
  const { user } = useAuth()
  const today = useBusinessDate()
  return user ? <DailyWorkspace key={user.id} userId={user.id} today={today} /> : null
}
function DailyWorkspace({ userId, today }: { userId: number; today: string }) {
  const [date, setDate] = useState(today)
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-bold">Cerrar el día</h1><p className="text-muted-foreground">Revisa los hechos, añade tus notas y guarda. Compartir es una acción aparte.</p></div>
      <label className="space-y-1 text-sm font-medium">Fecha
        <input aria-label="Fecha del daily" type="date" value={date} onChange={(event) => event.target.value && setDate(event.target.value)} className="ml-2 rounded-md border border-border bg-background px-2 py-1.5 text-sm" />
      </label>
    </div>
    <DailyGate key={`${userId}:${date}`} userId={userId} date={date} onDateChange={setDate} />
  </div>
}
function DailyGate(props: { userId: number; date: string; onDateChange: (date: string) => void }) {
  const query = useQuery({ queryKey: dayKey(props.userId, props.date), queryFn: () => dailysApi.forDate(props.date) })
  // A failed background refresh must not unmount an editor with local changes.
  if (query.data === undefined) return query.isError
    ? <ErrorCard message="No se pudo comprobar el resumen de esta fecha. Tus notas locales se conservan." onRetry={() => void query.refetch()} />
    : <p role="status" className="text-sm">Comprobando el resumen de esta fecha…</p>
  return <DailyEditor {...props} serverDaily={query.data} serverError={query.isError} checking={query.isFetching} onRefresh={async () => {
    const result = await query.refetch()
    return !result.isError
  }} />
}
function DailyEditor({ userId, date, onDateChange, serverDaily, serverError, checking, onRefresh }: {
  userId: number; date: string; onDateChange: (date: string) => void
  serverDaily: DailyUpdate | null; serverError: boolean; checking: boolean; onRefresh: () => Promise<boolean>
}) {
  const queryClient = useQueryClient()
  const live = useLiveInstance()
  const canOpenSources = useSourceAccess()
  const [editor, setEditor] = useState<Editor>(() => {
    const local = readDraft(userId, date)
    const draft = local ?? (serverDaily ? fromDaily(serverDaily) : emptyDraft())
    const matches = serverDaily && draft.baseId === serverDaily.id && draft.baseRevision === serverDaily.revision
    return { draft, base: matches ? serverDaily : null }
  })
  const editorRef = useRef(editor)
  const [availableFacts, setAvailableFacts] = useState(editor.draft.sourceFacts)
  const [conflict, setConflict] = useState<DailyUpdate | null>(null)
  const [uncertain, setUncertain] = useState(false)
  const [storageFailed, setStorageFailed] = useState(false)
  const [deleteDaily, setDeleteDaily] = useState<DailyUpdate | null>(null)
  const history = useQuery({ queryKey: ["dailys", userId, "history"], queryFn: () => dailysApi.list({ limit: 50 }) })
  const { draft, base } = editor
  const relevant = (daily: DailyUpdate) => daily.user_id === userId && daily.date === date
  const latestConflict = conflict && serverDaily && (serverDaily.id !== conflict.id || serverDaily.revision > conflict.revision) ? serverDaily : conflict
  const recovery = latestConflict ?? (serverDaily && (base?.id !== serverDaily.id || base.revision !== serverDaily.revision) ? serverDaily : null)
  const deletedElsewhere = !serverError && !serverDaily && draft.baseId !== null
  const isSent = base?.status === "sent" || serverDaily?.status === "sent"
  const dirty = !base || draft.rawText !== base.raw_text || JSON.stringify(draft.sourceFactKeys) !== JSON.stringify((base.source_facts ?? []).map((fact) => fact.key))
  const facts = [...draft.sourceFacts, ...availableFacts.filter((fact) => !draft.sourceFacts.some((selected) => selected.key === fact.key))]

  function change(next: Editor) {
    if (!live.current) return
    editorRef.current = next
    setEditor(next)
    try { localStorage.setItem(storageKey(userId, date), JSON.stringify(next.draft)); setStorageFailed(false) }
    catch { setStorageFailed(true) }
  }
  function editDraft(patch: Partial<LocalDraft>) {
    const current = editorRef.current
    change({ ...current, draft: { ...current.draft, ...patch } })
  }
  function refreshHistory() { void queryClient.invalidateQueries({ queryKey: ["dailys", userId] }) }
  async function checkSaved() {
    if (await onRefresh() && live.current) setUncertain(false)
  }
  function acceptSaved(daily: DailyUpdate) {
    // A response from a disposed date/identity only refreshes server queries.
    // It cannot write its old draft over a newly mounted editor's local storage.
    if (!live.current || !relevant(daily)) { refreshHistory(); return }
    const current = editorRef.current
    const cached = queryClient.getQueryData<DailyUpdate | null>(dayKey(userId, date))
    if (cached && (cached.id !== daily.id || cached.revision > daily.revision || (cached.status === "sent" && daily.status !== "sent"))) {
      setConflict(cached)
      refreshHistory()
      return
    }
    if (current.base && current.base.id === daily.id && current.base.revision > daily.revision) return
    queryClient.setQueryData(dayKey(userId, date), daily)
    change({ base: daily, draft: { ...current.draft, baseId: daily.id, baseRevision: daily.revision } })
    setConflict(null)
    setUncertain(false)
    refreshHistory()
  }
  function onSaveError(error: unknown) {
    if (!live.current) return
    const current = currentConflict(error)
    if (current && relevant(current)) {
      queryClient.setQueryData(dayKey(userId, date), current)
      setConflict(current)
    } else {
      const code = (error as { response?: { status?: number } })?.response?.status
      setUncertain(!code || code >= 500)
    }
    toast.error(dailyError(error, "No se pudo confirmar el guardado. Tus notas se conservan."))
  }
  const save = useMutation({
    mutationFn: (submitted: Editor) => submitted.base
      ? dailysApi.edit(submitted.base.id, { raw_text: submitted.draft.rawText, source_fact_keys: submitted.draft.sourceFactKeys, revision: submitted.base.revision })
      : dailysApi.submit({ raw_text: submitted.draft.rawText, date, source_fact_keys: submitted.draft.sourceFactKeys }),
    onSuccess: (daily) => { acceptSaved(daily); if (live.current) toast.success("Borrador guardado") },
    onError: onSaveError,
  })
  const enrich = useMutation({
    mutationFn: (daily: DailyUpdate) => dailysApi.reparse(daily.id, daily.revision),
    onSuccess: (daily) => { acceptSaved(daily); if (live.current) toast.success("Estructura actualizada. Tus notas se conservan.") },
    onError: onSaveError,
  })
  const prefill = useMutation({
    mutationFn: () => dailysApi.prefill(date),
    onSuccess: (result) => {
      if (!live.current) return
      setAvailableFacts(result.facts)
      toast.success(`${result.completed_count} completadas · ${Math.round(result.total_minutes)} min reales`)
    },
    onError: (error) => live.current && toast.error(getErrorMessage(error, "No se pudieron consultar los hechos")),
  })
  const remove = useMutation({
    mutationFn: (daily: DailyUpdate) => dailysApi.delete(daily.id, daily.revision),
    onSuccess: (_, removed) => {
      if (live.current && relevant(removed)) {
        queryClient.setQueryData(dayKey(userId, date), null)
        const current = editorRef.current
        change({ base: null, draft: { ...current.draft, baseId: null, baseRevision: null } })
        setConflict(null)
      }
      refreshHistory()
      if (live.current) { setDeleteDaily(null); toast.success("Borrador eliminado. Las notas locales se conservan.") }
    },
    onError: (error) => { if (live.current) toast.error(dailyError(error, "No se pudo eliminar el borrador")); refreshHistory() },
  })
  function resolve(daily: DailyUpdate, keepLocal: boolean) {
    queryClient.setQueryData(dayKey(userId, date), daily)
    change({ base: daily, draft: keepLocal
      ? { ...editorRef.current.draft, baseId: daily.id, baseRevision: daily.revision }
      : fromDaily(daily) })
    setConflict(null)
    setUncertain(false)
  }
  const blocked = !!recovery || deletedElsewhere || serverError || checking || isSent || save.isPending || enrich.isPending
  return <div className="space-y-6" id="daily-editor">
    {serverError && <ErrorCard message="No se pudo actualizar la versión guardada. Tus notas siguen aquí." onRetry={() => void checkSaved()} />}
    {uncertain && <ErrorCard message="No se pudo confirmar la operación. Comprueba la versión guardada antes de continuar." onRetry={() => void checkSaved()} />}
    {storageFailed && <p role="alert" className="text-sm">Este navegador no pudo conservar la copia local. Mantén esta página abierta hasta guardar.</p>}
    {recovery && <RecoveryCard daily={recovery} draft={draft} onSaved={() => resolve(recovery, false)} onLocal={() => resolve(recovery, true)} />}
    {deletedElsewhere && <Card><CardContent className="space-y-3 pt-6">
      <p>El resumen guardado ya no existe. Tus notas locales siguen aquí.</p>
      <Button variant="outline" onClick={() => { change({ base: null, draft: { ...draft, baseId: null, baseRevision: null } }); setConflict(null) }}>Preparar un nuevo borrador con mis notas</Button>
    </CardContent></Card>}
    <Card><CardHeader><CardTitle as="h2" className="text-base">Hechos del día</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">Elige las fuentes que quieras incluir. Consultar no cambia tareas ni tiempo.</p>
        <p className="text-xs text-muted-foreground">Completados y horas corresponden a la fecha elegida. Las esperas y próximos pasos reflejan el estado actual.</p>
        <Button variant="outline" size="sm" onClick={() => prefill.mutate()} disabled={prefill.isPending}>
          {prefill.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <RefreshCw className="mr-2 size-4" />}Actualizar hechos
        </Button>
        {(facts.length > 0 || prefill.isSuccess) && <DailyFactPicker facts={facts} selected={draft.sourceFactKeys} canOpenSources={canOpenSources} readOnly={isSent}
          onSelectedChange={(keys) => editDraft({ sourceFactKeys: keys, sourceFacts: facts.filter((fact) => keys.includes(fact.key)) })} />}
        {facts.length > 0 && <Button variant="outline" size="sm" disabled={isSent || !draft.sourceFactKeys.length} onClick={() => {
          const selected = facts.filter((fact) => draft.sourceFactKeys.includes(fact.key))
          const text = selected.map((fact) => `- ${fact.title}${fact.detail ? ` — ${fact.detail}` : ""}`).join("\n")
          editDraft({ rawText: `${draft.rawText}${draft.rawText ? "\n\n" : ""}${text}` })
        }}>Añadir hechos seleccionados a las notas</Button>}
        {(facts.length > 0 || prefill.isSuccess) && <p className="text-xs text-muted-foreground">Las tareas completadas requieren una fecha de finalización fiable; las horas reales se contabilizan de forma independiente.</p>}
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle as="h2" className="text-base">Notas del cierre</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {isSent && <p className="text-sm text-muted-foreground">Este resumen ya fue enviado y se conserva en modo lectura.</p>}
        <textarea aria-label="Notas del daily" value={draft.rawText} disabled={isSent} onChange={(event) => editDraft({ rawText: event.target.value })}
          placeholder="Qué se completó, qué está en espera y cuál es el siguiente paso…"
          className="min-h-48 w-full resize-y rounded-xl border border-border bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand/20" />
        {draft.rawText.length > 50_000 && <p role="alert" className="text-sm">Las notas superan 50.000 caracteres. Redúcelas antes de guardar.</p>}
        <p className="text-xs text-muted-foreground">{draft.sourceFactKeys.length} fuentes seleccionadas · máximo 500</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => save.mutate(editorRef.current)} disabled={blocked || !draft.rawText.trim() || draft.rawText.length > 50_000 || draft.sourceFactKeys.length > 500}>
            {save.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}Guardar borrador
          </Button>
          {base && !isSent && <Button variant="outline" onClick={() => enrich.mutate(base)} disabled={blocked || dirty}>
            {enrich.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Wand2 className="mr-2 size-4" />}Estructurar con IA
          </Button>}
          <span role="status" className="text-xs text-muted-foreground">{save.isPending ? "Guardando…" : enrich.isPending ? "Estructurando la versión guardada…" : dirty ? "Notas locales sin guardar" : "Versión guardada"}</span>
        </div>
        {dirty && base && !isSent && <p className="text-xs text-muted-foreground">Guarda los cambios antes de estructurar.</p>}
        {base?.parsed_data && <ParsedDaily daily={base} canOpenSources={canOpenSources} />}
      </CardContent>
    </Card>
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Últimos 50 resúmenes</h2>
      {history.isPending ? <p role="status">Cargando historial…</p> : history.isError
        ? <ErrorCard message="No se pudo cargar el historial." onRetry={() => void history.refetch()} />
        : history.data?.length ? history.data.map((daily) => <DailyCard key={daily.id} daily={daily} userId={userId} canOpenSources={canOpenSources}
          disableSend={daily.user_id === userId && daily.date === date && (blocked || dirty || uncertain)} onDelete={() => setDeleteDaily(daily)} onEdit={() => { onDateChange(daily.date); document.getElementById("daily-editor")?.scrollIntoView({ behavior: "smooth" }) }} />)
          : <p className="text-sm text-muted-foreground">Sin resúmenes guardados todavía.</p>}
    </section>
    <ConfirmDialog open={!!deleteDaily} onOpenChange={(open) => !open && setDeleteDaily(null)} title="Eliminar borrador" description="Se eliminará el resumen guardado. Los resúmenes con historial de envío se conservan." confirmLabel="Eliminar" onConfirm={() => deleteDaily && remove.mutate(deleteDaily)} />
  </div>
}
function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">{message}</p><Button size="sm" variant="outline" onClick={onRetry}>Reintentar</Button></CardContent></Card>
}
function RecoveryCard({ daily, draft, onSaved, onLocal }: { daily: DailyUpdate; draft: LocalDraft; onSaved: () => void; onLocal: () => void }) {
  return <Card className="border-amber-500/40"><CardContent className="space-y-3 pt-6">
    <p className="text-sm font-medium">Hay otra versión guardada. Compara ambos textos antes de continuar.</p>
    <div className="grid gap-3 md:grid-cols-2">
      <div className="min-w-0 rounded-lg bg-muted/50 p-3"><h3 className="mb-2 text-sm font-medium">Texto guardado · revisión {daily.revision}</h3><p className="whitespace-pre-wrap break-words text-sm">{daily.raw_text}</p><p className="mt-2 text-xs">{(daily.source_facts ?? []).length} fuentes guardadas</p></div>
      <div className="min-w-0 rounded-lg border p-3"><h3 className="mb-2 text-sm font-medium">Mis notas locales</h3><p className="whitespace-pre-wrap break-words text-sm">{draft.rawText || "Sin notas"}</p><p className="mt-2 text-xs">{draft.sourceFactKeys.length} fuentes seleccionadas</p></div>
    </div>
    <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={onSaved}>Usar texto guardado</Button>{daily.status === "draft" && <Button size="sm" onClick={onLocal}>Continuar con mis notas</Button>}</div>
  </CardContent></Card>
}
function DailyCard({ daily, userId, canOpenSources, disableSend, onDelete, onEdit }: {
  daily: DailyUpdate; userId: number; canOpenSources: boolean; disableSend: boolean; onDelete: () => void; onEdit: () => void
}) {
  const queryClient = useQueryClient()
  const live = useLiveInstance()
  const [expanded, setExpanded] = useState(false)
  const [showReceipts, setShowReceipts] = useState(false)
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["dailys", userId] })
  const enrich = useMutation({ mutationFn: () => dailysApi.reparse(daily.id, daily.revision), onSuccess: () => { refresh(); if (live.current) toast.success("Estructura actualizada") }, onError: (error) => live.current && toast.error(dailyError(error, "No se pudo estructurar este borrador")) })
  const send = useMutation({ mutationFn: () => dailysApi.sendDiscord(daily.id), onSuccess: (receipt) => { refresh(); if (live.current) { setShowReceipts(true); deliveryToast(receipt) } }, onError: (error) => live.current && toast.error(getErrorMessage(error, "No se pudo confirmar el envío")) })
  return <Card>
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
      <button className="min-w-0 flex-1 text-left" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <span className="block text-sm font-semibold">{daily.user_name || "Usuario"} · {format(parseISO(`${daily.date}T12:00:00`), "EEEE d MMM yyyy", { locale: es })}</span>
        <span className="block text-xs text-muted-foreground">{daily.status === "sent" ? "Enviado" : "Borrador"} · {(daily.source_facts ?? []).length} fuentes {expanded ? <ChevronUp className="inline size-3" /> : <ChevronDown className="inline size-3" />}</span>
      </button>
      <div className="flex flex-wrap gap-1">
        {daily.user_id === userId && daily.status === "draft" && <Button title="Editar" aria-label="Editar" variant="ghost" size="icon" onClick={onEdit}><Pencil className="size-4" /></Button>}
        {daily.status === "draft" && <Button title="Estructurar con IA" aria-label="Estructurar resumen guardado con IA" variant="ghost" size="icon" disabled={enrich.isPending || disableSend} onClick={() => enrich.mutate()}><Wand2 className="size-4" /></Button>}
        <Button title="Enviar a Discord" aria-label="Enviar a Discord" variant="ghost" size="icon" disabled={send.isPending || disableSend} onClick={() => send.mutate()}><MessageCircle className="size-4" /></Button>
        {daily.user_id === userId && daily.status === "draft" && <Button title="Eliminar" aria-label="Eliminar" variant="ghost" size="icon" disabled={disableSend} onClick={onDelete}><Trash2 className="size-4" /></Button>}
      </div>
    </div>
    {(expanded || showReceipts) && <CardContent className="space-y-4 border-t pt-4">
      <DeliveryReceipts sourceKind="daily" sourceId={daily.id} />
      {expanded && <><p className="whitespace-pre-wrap break-words text-sm">{daily.raw_text}</p><SourceFacts facts={daily.source_facts ?? []} canOpenSources={canOpenSources} />{daily.parsed_data && <ParsedDaily daily={daily} canOpenSources={canOpenSources} />}</>}
    </CardContent>}
  </Card>
}
function SourceFacts({ facts, canOpenSources }: { facts: DailyFact[]; canOpenSources: boolean }) {
  if (!facts.length) return <p className="text-xs text-muted-foreground">Sin fuentes seleccionadas.</p>
  return <div><h3 className="mb-2 text-sm font-medium">Fuentes guardadas</h3><ul className="space-y-1">
    {facts.map((fact) => <li key={fact.key} className="break-words text-sm">
      {fact.href && canOpenSources ? <Link className="text-primary underline" to={fact.href}>{fact.title}</Link> : fact.title}
      {fact.minutes != null && ` · ${Math.round(fact.minutes)} min reales`}{fact.detail && ` · ${fact.detail}`}
    </li>)}
  </ul></div>
}
function ParsedDaily({ daily, canOpenSources }: { daily: DailyUpdate; canOpenSources: boolean }) {
  const parsed = daily.parsed_data
  if (!parsed) return null
  const byKey = new Map((daily.source_facts ?? []).map((fact) => [fact.key, fact]))
  const groups = [...parsed.projects, { name: "Notas libres", client: "", tasks: parsed.general }]
  return <div className="space-y-3 border-t pt-3"><h3 className="text-sm font-medium">Estructura de la versión guardada</h3>
    {groups.filter((group) => group.tasks.length).map((group, index) => <div key={`${group.name}-${index}`}>
      <p className="text-sm font-medium">{group.name}{group.client ? ` · ${group.client}` : ""}</p>
      <ul className="ml-4 list-disc text-sm">{group.tasks.map((task, taskIndex) => {
        const fact = task.fact_keys?.map((key) => byKey.get(key)).find(Boolean)
        return <li key={taskIndex} className="break-words">{fact?.href && canOpenSources ? <Link className="text-primary underline" to={fact.href}>{task.description}</Link> : task.description}{task.details && ` — ${task.details}`}</li>
      })}</ul>
    </div>)}
    {parsed.tomorrow.length > 0 && <p className="text-sm text-muted-foreground">Próximo: {parsed.tomorrow.join(" · ")}</p>}
  </div>
}
