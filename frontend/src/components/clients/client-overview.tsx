import { useQuery } from "@tanstack/react-query"
import { Briefcase, Heart, LineChart, Users } from "lucide-react"
import { contactsApi } from "@/lib/api"
import { ga4Change, ga4Number } from "@/lib/ga4"
import type { Client, ClientStatusRow, Task } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ClientStatusBadge, ClientStatusReasons, DigestCell, SeoCell } from "@/components/clients/client-status"

type Section = "tareas" | "resumenes" | "control_seo" | "contexto" | "contactos"

const OPEN = new Set(["backlog", "pending", "in_progress", "advanced", "in_review", "waiting"])
const day = (value: string) => new Date(value.length > 10 ? value : `${value}T12:00:00`)
  .toLocaleDateString("es-ES", { day: "numeric", month: "short" })

function BlockTitle({ icon: Icon, children }: { icon: typeof Heart; children: React.ReactNode }) {
  return (
    <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
      <Icon className="h-3.5 w-3.5" /> {children}
    </h3>
  )
}

function GoTo({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className="text-xs text-brand hover:underline" onClick={onClick}>{children}</button>
}

interface Props {
  client: Client
  status: ClientStatusRow | undefined
  statusFailed: boolean
  onRetryStatus: () => void
  /** null = quien mira no puede leer tareas. */
  tasks: Task[] | null
  canReadDigests: boolean
  canReadContacts: boolean
  onNavigate: (section: Section) => void
}

/** Vista general de la ficha: estado arriba y Trabajo · Resultados · Relación debajo. */
export function ClientOverview({ client, status, statusFailed, onRetryStatus, tasks, canReadDigests, canReadContacts, onNavigate }: Props) {
  const { data: contacts = [] } = useQuery({
    queryKey: ["client-contacts", client.id],
    queryFn: () => contactsApi.list(client.id),
    enabled: canReadContacts,
  })
  const primary = contacts.find((c) => c.is_primary) ?? contacts[0] ?? null

  const open = (tasks ?? []).filter((t) => OPEN.has(t.status))
  const next = open
    .filter((t) => t.status !== "waiting" && t.status !== "in_review")
    .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"))
    .slice(0, 5)
  const inReview = open.filter((t) => t.status === "in_review")
  const waiting = open
    .filter((t) => t.status === "waiting")
    .sort((a, b) => (a.follow_up_date ?? "9999").localeCompare(b.follow_up_date ?? "9999"))
  const today = new Date().toISOString().slice(0, 10)
  const context = client.context?.trim()

  return (
    <div className="space-y-4">
      {/* 1. Estado */}
      {statusFailed ? (
        <Card><CardContent className="flex flex-wrap items-center justify-between gap-2 p-4" role="alert">
          <p className="text-sm">No se pudo calcular el estado del cliente.</p>
          <Button variant="outline" size="sm" onClick={onRetryStatus}>Reintentar</Button>
        </CardContent></Card>
      ) : status && (
        <Card className={status.status === "act" ? "border-red-500/40" : undefined}>
          <CardContent className="flex flex-wrap items-start justify-between gap-3 p-4">
            <div className="space-y-1.5">
              <BlockTitle icon={Heart}>Estado del cliente</BlockTitle>
              <ClientStatusReasons row={status} />
            </div>
            <ClientStatusBadge status={status.status} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* 2. Trabajo */}
        <Card><CardContent className="space-y-3 p-4">
          <BlockTitle icon={Briefcase}>Trabajo</BlockTitle>
          {tasks === null ? <p className="text-xs text-muted-foreground">Sin acceso a las tareas.</p> : (
            <>
              <div>
                <p className="text-xs text-muted-foreground">{open.length} abiertas{status?.month ? ` · ${status.month.hours.toLocaleString("es-ES")} h este mes` : ""}</p>
                {next.length === 0 ? <p className="text-sm">Nada pendiente.</p> : (
                  <ul className="mt-1 space-y-1 text-sm">
                    {next.map((t) => (
                      <li key={t.id} className="flex justify-between gap-2">
                        <span className="truncate">{t.title}</span>
                        {t.due_date && <span className={`shrink-0 text-xs ${t.due_date.slice(0, 10) < today ? "font-medium text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>{day(t.due_date)}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {inReview.length > 0 && (
                <div>
                  <p className="text-xs font-medium">Por revisar ({inReview.length})</p>
                  <ul className="text-sm">{inReview.slice(0, 3).map((t) => <li key={t.id} className="truncate">{t.title}</li>)}</ul>
                </div>
              )}
              {status?.ready && (
                <div>
                  <p className="text-xs font-medium">Listo para entregar ({status.ready.count})</p>
                  <p className="text-xs text-muted-foreground">Terminado desde el {day(status.ready.since)} y sin resumen entregado</p>
                  {status.ready.count === 0 ? <p className="text-sm text-muted-foreground">Nada pendiente de contar.</p> : (
                    <ul className="space-y-0.5 text-sm">
                      {status.ready.items.map((t) => (
                        <li key={t.id} className="flex justify-between gap-2">
                          <span className="truncate">{t.title}</span>
                          <span className="shrink-0 text-xs text-muted-foreground">{day(t.completed_on)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <GoTo onClick={() => onNavigate("tareas")}>Ver tareas</GoTo>
            </>
          )}
        </CardContent></Card>

        {/* 3. Resultados */}
        <Card><CardContent className="space-y-3 p-4">
          <BlockTitle icon={LineChart}>Resultados</BlockTitle>
          <div>
            <p className="mb-0.5 text-xs font-medium">Tráfico de Google</p>
            <SeoCell seo={status?.seo ?? null} />
            {client.gsc_url && <GoTo onClick={() => onNavigate("control_seo")}>Ver Control SEO</GoTo>}
          </div>
          {canReadDigests && (
            <div>
              <p className="mb-0.5 text-xs font-medium">Resumen al cliente</p>
              <DigestCell digests={status?.digests} />
              <GoTo onClick={() => onNavigate("resumenes")}>Abrir resúmenes</GoTo>
            </div>
          )}
          {status?.ga4 && (
            <div>
              <p className="mb-0.5 text-xs font-medium">Visitas y conversiones (GA4, 28 días)</p>
              <p className="text-sm">
                {ga4Number(status.ga4.current.sessions)} visitas · {ga4Number(status.ga4.current.key_events)} conversiones
                {ga4Change(status.ga4.vs_previous?.key_events_pct) && (
                  <span className="text-xs text-muted-foreground"> ({ga4Change(status.ga4.vs_previous?.key_events_pct)} conversiones)</span>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                Desde IA: {ga4Number(status.ga4.current.ai_sessions)} visitas · {ga4Number(status.ga4.current.ai_key_events)} conversiones
                {` · hasta el ${day(status.ga4.as_of)}`}
              </p>
            </div>
          )}
        </CardContent></Card>

        {/* 4. Relación */}
        <Card><CardContent className="space-y-3 p-4">
          <BlockTitle icon={Users}>Relación</BlockTitle>
          {canReadContacts && (
            <div>
              <p className="text-xs font-medium">Interlocutor</p>
              {primary ? (
                <p className="text-sm">{primary.name}{primary.position ? <span className="text-muted-foreground"> · {primary.position}</span> : null}
                  {primary.email && <><br /><a className="text-xs text-brand hover:underline" href={`mailto:${primary.email}`}>{primary.email}</a></>}
                </p>
              ) : <p className="text-sm text-muted-foreground">Sin contactos. <GoTo onClick={() => onNavigate("contactos")}>Añadir</GoTo></p>}
            </div>
          )}
          {tasks !== null && (
            <div>
              <p className="text-xs font-medium">Esperando al cliente ({waiting.length})</p>
              {waiting.length === 0 ? <p className="text-sm text-muted-foreground">Nada en espera.</p> : (
                <ul className="space-y-0.5 text-sm">
                  {waiting.slice(0, 4).map((t) => (
                    <li key={t.id} className="flex justify-between gap-2">
                      <span className="truncate">{t.title}{t.waiting_for ? <span className="text-muted-foreground"> · {t.waiting_for}</span> : null}</span>
                      {t.follow_up_date && <span className={`shrink-0 text-xs ${t.follow_up_date < today ? "font-medium text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>{day(t.follow_up_date)}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div>
            <p className="text-xs font-medium">Contexto</p>
            {context ? <p className="line-clamp-3 text-sm text-muted-foreground">{context}</p> : <p className="text-sm text-muted-foreground">Sin contexto escrito.</p>}
            <GoTo onClick={() => onNavigate("contexto")}>{context ? "Ver contexto" : "Escribir contexto"}</GoTo>
          </div>
        </CardContent></Card>
      </div>
    </div>
  )
}
