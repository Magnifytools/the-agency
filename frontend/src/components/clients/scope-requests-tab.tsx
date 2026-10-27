import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Trash2 } from "lucide-react"
import { projectsApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { businessDateString, formatCivilDate, getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import {
  SCOPE_DECISION_LABELS,
  SCOPE_DECISIONS,
  formatScopeMinutes,
  parseEstimate,
  scopeRequestKeys,
  scopeRequestsApi,
  type ScopeDecision,
  type ScopeRequest,
} from "@/lib/scope-requests"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

interface Props {
  clientId: number
}

const DECISION_STYLES: Record<ScopeDecision, string> = {
  pending: "bg-amber-500/10 text-amber-700 border-amber-500/30",
  absorb: "bg-muted text-foreground border-border",
  bill: "bg-green-500/10 text-green-700 border-green-500/30",
  swap: "bg-blue-500/10 text-blue-700 border-blue-500/30",
}

/**
 * Peticiones fuera de alcance del cliente (área Trabajo): lo que pide de más
 * por llamada, Slack o email, cuánto cuesta y qué decidimos. Arriba, el total
 * del mes elegido; en la lista, lo del mes y lo pendiente de meses anteriores.
 */
export function ScopeRequestsTab({ clientId }: Props) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("clients", true)
  const canReadProjects = hasPermission("projects")
  const currentMonth = businessDateString().slice(0, 7)
  const [month, setMonth] = useState(currentMonth)
  const qc = useQueryClient()
  const [deleting, setDeleting] = useState<ScopeRequest | null>(null)

  const listQuery = useQuery({
    queryKey: scopeRequestKeys.month(clientId, month),
    queryFn: () => scopeRequestsApi.list(clientId, month),
  })
  const { data: projects = [] } = useQuery({
    queryKey: ["projects", "by-client", clientId],
    queryFn: () => projectsApi.listAll({ client_id: clientId }),
    enabled: canReadProjects && canWrite,
    staleTime: 60_000,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: scopeRequestKeys.all(clientId) })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { decision?: ScopeDecision; decision_note?: string | null } }) =>
      scopeRequestsApi.update(clientId, id, data),
    onSuccess: () => void invalidate(),
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo guardar la decisión")),
  })
  const deleteMut = useMutation({
    mutationFn: (id: number) => scopeRequestsApi.delete(clientId, id),
    onSuccess: () => {
      void invalidate()
      toast.success("Petición borrada. Puedes deshacerlo con ⌘Z.")
    },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo borrar")),
  })

  const data = listQuery.data
  const monthLabel = formatCivilDate(`${month}-01`, { month: "long", year: "numeric" })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Peticiones extra de {monthLabel}</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Lo que el cliente pide fuera de lo contratado, con su coste estimado y qué decidimos.
              </p>
            </div>
            <label className="text-sm">
              <span className="sr-only">Mes</span>
              <input
                aria-label="Mes de las peticiones"
                type="month"
                value={month}
                max={currentMonth}
                onChange={(event) => event.target.value && setMonth(event.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5"
              />
            </label>
          </div>
        </CardHeader>
        <CardContent>
          {listQuery.isLoading ? (
            <p role="status" className="text-sm text-muted-foreground">Cargando…</p>
          ) : listQuery.isError || !data ? (
            <p role="alert" className="text-sm">No se pudieron cargar las peticiones.</p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Total del mes">
              <Total label="La asumimos" minutes={data.totals.absorbed_minutes} />
              <Total label="A facturar" minutes={data.totals.billable_minutes} />
              <Total label="Pendiente de decidir" minutes={data.totals.pending_minutes} highlight={data.totals.pending_minutes > 0} />
              <Total label="A cambio de otra cosa" minutes={data.totals.swapped_minutes} />
            </div>
          )}
        </CardContent>
      </Card>

      {canWrite && (
        <NewScopeRequest
          clientId={clientId}
          projects={canReadProjects ? projects.map((p) => ({ id: p.id, name: p.name })) : []}
          onCreated={(requestedOn) => {
            void invalidate()
            setMonth(requestedOn.slice(0, 7))
          }}
        />
      )}

      {data && (
        <Card>
          <CardContent className="p-0">
            {data.items.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No hay peticiones extra en {monthLabel}.</p>
            ) : (
              <ul className="divide-y">
                {data.items.map((item) => (
                  <ScopeRequestRow
                    key={item.id}
                    item={item}
                    month={month}
                    canWrite={canWrite}
                    onDecide={(decision) => updateMut.mutate({ id: item.id, data: { decision } })}
                    onNote={(decision_note) => updateMut.mutate({ id: item.id, data: { decision_note } })}
                    onDelete={() => setDeleting(item)}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Borrar petición"
        description={`¿Borrar «${deleting?.title ?? ""}»? Se puede deshacer con ⌘Z.`}
        confirmLabel="Borrar"
        onConfirm={() => {
          if (deleting) deleteMut.mutate(deleting.id)
          setDeleting(null)
        }}
      />
    </div>
  )
}

function Total({ label, minutes, highlight = false }: { label: string; minutes: number; highlight?: boolean }) {
  return (
    <div className={`min-w-0 rounded-lg p-3 ${highlight ? "bg-amber-500/10" : "bg-muted/40"}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mono mt-1 text-lg font-semibold">{formatScopeMinutes(minutes)}</p>
    </div>
  )
}

function ScopeRequestRow({ item, month, canWrite, onDecide, onNote, onDelete }: {
  item: ScopeRequest
  month: string
  canWrite: boolean
  onDecide: (decision: ScopeDecision) => void
  onNote: (note: string | null) => void
  onDelete: () => void
}) {
  const [note, setNote] = useState(item.decision_note ?? "")
  const earlier = item.requested_on.slice(0, 7) < month
  const decidedAt = item.decided_at
    ? parseApiInstant(item.decided_at).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: getAgencyTimezone() })
    : null
  return (
    <li className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <p className="break-words font-medium">{item.title}</p>
        <p className="text-xs text-muted-foreground">
          {formatCivilDate(item.requested_on, { day: "numeric", month: "short" })}
          {earlier && " · de un mes anterior"}
          {" · "}<span className="mono">{formatScopeMinutes(item.estimated_minutes)}</span>
          {item.project_name && ` · ${item.project_name}`}
          {item.created_by_name && ` · apuntó ${item.created_by_name}`}
        </p>
        {item.detail && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{item.detail}</p>}
        {item.decision !== "pending" && (
          <p className="text-xs text-muted-foreground">
            Decidió {item.decided_by_name ?? "alguien que ya no está"}{decidedAt && ` el ${decidedAt}`}
            {!canWrite && item.decision_note && ` · ${item.decision_note}`}
          </p>
        )}
        {canWrite && item.decision !== "pending" && (
          <Input
            aria-label={`Nota de la decisión: ${item.title}`}
            placeholder={item.decision === "swap" ? "¿A cambio de qué?" : "Nota (opcional)"}
            value={note}
            maxLength={1000}
            onChange={(event) => setNote(event.target.value)}
            onBlur={() => {
              const next = note.trim() || null
              if (next !== (item.decision_note ?? null)) onNote(next)
            }}
            className="h-8 text-xs"
          />
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {canWrite ? (
          <Select
            aria-label={`Decisión: ${item.title}`}
            value={item.decision}
            onChange={(event) => onDecide(event.target.value as ScopeDecision)}
            className="h-8 w-auto text-xs"
          >
            {SCOPE_DECISIONS.map((decision) => (
              <option key={decision} value={decision}>{SCOPE_DECISION_LABELS[decision]}</option>
            ))}
          </Select>
        ) : (
          <span className={`rounded-full border px-2 py-0.5 text-xs ${DECISION_STYLES[item.decision]}`}>
            {SCOPE_DECISION_LABELS[item.decision]}
          </span>
        )}
        {canWrite && (
          <Button size="sm" variant="ghost" aria-label={`Borrar ${item.title}`} onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </li>
  )
}

function NewScopeRequest({ clientId, projects, onCreated }: {
  clientId: number
  projects: { id: number; name: string }[]
  onCreated: (requestedOn: string) => void
}) {
  const today = businessDateString()
  const [title, setTitle] = useState("")
  const [detail, setDetail] = useState("")
  const [estimate, setEstimate] = useState("")
  const [unit, setUnit] = useState<"min" | "h">("min")
  const [projectId, setProjectId] = useState("")
  const [requestedOn, setRequestedOn] = useState(today)
  const minutes = parseEstimate(estimate, unit)

  const createMut = useMutation({
    mutationFn: () => scopeRequestsApi.create(clientId, {
      title: title.trim(),
      detail: detail.trim() || null,
      estimated_minutes: minutes ?? 0,
      project_id: projectId ? Number(projectId) : null,
      requested_on: requestedOn,
    }),
    onSuccess: (created) => {
      setTitle("")
      setDetail("")
      setEstimate("")
      setProjectId("")
      toast.success("Petición apuntada")
      onCreated(created.requested_on)
    },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo apuntar la petición")),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim() || minutes === null) return
    createMut.mutate()
  }

  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base">Apuntar petición extra</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <Input aria-label="Qué ha pedido" placeholder="Qué ha pedido (p. ej. «Landing para Black Friday»)" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          <Textarea aria-label="Detalle" placeholder="Detalle (opcional): quién lo pidió, por dónde…" value={detail} maxLength={4000} onChange={(e) => setDetail(e.target.value)} />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="flex gap-2">
              <Input aria-label="Coste estimado" inputMode="decimal" placeholder="Coste estimado" value={estimate} onChange={(e) => setEstimate(e.target.value)} />
              <Select aria-label="Unidad" value={unit} onChange={(e) => setUnit(e.target.value as "min" | "h")} className="w-24">
                <option value="min">min</option>
                <option value="h">h</option>
              </Select>
            </div>
            {projects.length > 0 ? (
              <Select aria-label="Proyecto" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">Sin proyecto</option>
                {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
              </Select>
            ) : <div className="hidden sm:block" />}
            <Input aria-label="Fecha de la petición" type="date" value={requestedOn} max={today} onChange={(e) => e.target.value && setRequestedOn(e.target.value)} />
          </div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">Entra como pendiente; la decisión se toma en la lista.</p>
            <Button type="submit" size="sm" disabled={!title.trim() || minutes === null || createMut.isPending}>Apuntar</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
