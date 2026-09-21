import { Link } from "react-router-dom"
import { Clock3, FolderKanban, ListChecks } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { useAuth } from "@/context/auth-context"

interface DigestFactsProps {
  context: Record<string, unknown>
}

type UnknownRecord = Record<string, unknown>

const isRecord = (value: unknown): value is UnknownRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value)
const records = (value: unknown) => Array.isArray(value) ? value.filter(isRecord) : []
const text = (value: unknown) => typeof value === "string" ? value : null
const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : 0
const id = (value: unknown) => typeof value === "number" && Number.isInteger(value) ? value : null

function FactTasks({ label, total, tasks, canReadTasks, knownTotal = true }: {
  label: string
  total: number
  tasks: UnknownRecord[]
  canReadTasks: boolean
  knownTotal?: boolean
}) {
  if (!total && !tasks.length) return null
  return (
    <section className="space-y-2" aria-label={label}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold">{label}</h4>
        <span className="text-xs text-muted-foreground">
          {knownTotal ? `${total} en total${total > tasks.length ? ` · mostrando ${tasks.length}` : ""}` : `${tasks.length} en la muestra`}
        </span>
      </div>
      {tasks.length ? (
        <ul className="space-y-2">
          {tasks.map((task, index) => {
            const taskId = id(task.id)
            const title = text(task.title) || `Tarea ${index + 1}`
            return (
              <li key={taskId ?? `${title}-${index}`} className="rounded-lg border border-border/70 bg-background p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  {canReadTasks && taskId ? (
                    <Link className="font-medium text-brand hover:underline" to={`/tasks?task=${taskId}`}>{title}</Link>
                  ) : (
                    <span className="font-medium">{title}</span>
                  )}
                  {text(task.assigned_to) && <span className="text-xs text-muted-foreground">{text(task.assigned_to)}</span>}
                </div>
                {text(task.description) && <p className="mt-1 text-sm text-muted-foreground">{text(task.description)}</p>}
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  {text(task.due_date) && <span>Fecha: {text(task.due_date)}</span>}
                  {number(task.estimated_minutes) > 0 && <span>Estimado: {number(task.estimated_minutes)} min</span>}
                  {number(task.actual_minutes) > 0 && <span>Real acumulado: {number(task.actual_minutes)} min</span>}
                </div>
              </li>
            )
          })}
        </ul>
      ) : <p className="text-sm text-muted-foreground">Sin elementos en la muestra.</p>}
    </section>
  )
}

function ProjectFacts({ group, canReadTasks, canReadProjects }: { group: UnknownRecord; canReadTasks: boolean; canReadProjects: boolean }) {
  const projectId = id(group.project_id)
  const resolution = text(group.resolution)
  const name = text(group.project_name) || "Sin proyecto"
  const totalMinutes = number(group.total_minutes)
  const historicalTemplateMinutes = number(group.historical_template_minutes)
  const progress = typeof group.progress_percent === "number" ? group.progress_percent : null
  const completed = records(group.completed_tasks)
  const inProgress = records(group.in_progress_tasks)
  const pending = records(group.pending_tasks)
  return (
    <article className="rounded-xl border bg-card p-4 sm:p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {resolution === "resolved" && projectId && canReadProjects ? (
              <Link className="font-semibold text-brand hover:underline" to={`/projects/${projectId}`}>{name}</Link>
            ) : <h3 className="font-semibold">{name}</h3>}
            {resolution === "unresolved" && <Badge variant="secondary">Referencia histórica</Badge>}
            {resolution === "unassigned" && <Badge variant="secondary">Cliente</Badge>}
          </div>
          {progress !== null && <p className="mt-1 text-xs text-muted-foreground">Progreso al generar: {progress}% · no corresponde solo al período</p>}
        </div>
        <div className="text-right text-sm">
          <p className="font-medium">{number(group.task_total)} tareas actuales</p>
          <p className="text-muted-foreground">{totalMinutes} min en el período</p>
        </div>
      </div>
      {historicalTemplateMinutes > 0 && (
        <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          Incluye {historicalTemplateMinutes} min reales registrados históricamente sobre plantillas. Las plantillas no cuentan como tareas de progreso.
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <div><FactTasks label="Completadas en el período" total={number(group.completed_total)} tasks={completed} canReadTasks={canReadTasks} /><p className="mt-2 text-xs text-muted-foreground">Sólo incluye finalizaciones con fecha registrada dentro del período.</p></div>
        <FactTasks label="En curso al generar" total={number(group.in_progress_total)} tasks={inProgress} canReadTasks={canReadTasks} />
        <FactTasks label="Pendientes al generar" total={number(group.pending_total)} tasks={pending} canReadTasks={canReadTasks} />
      </div>
    </article>
  )
}

function Followups({ value }: { value: unknown }) {
  const items = records(value)
  if (!items.length) return null
  return (
    <section className="space-y-2">
      <h3 className="font-semibold">Seguimientos pendientes</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((item, index) => (
          <li key={id(item.id) ?? index} className="rounded-lg border p-3 text-sm">
            <p className="font-medium">{text(item.subject) || "Sin asunto"}</p>
            {text(item.summary) && <p className="mt-1 text-muted-foreground">{text(item.summary)}</p>}
            <p className="mt-1 text-xs text-muted-foreground">
              {[text(item.contact_name), text(item.followup_date)].filter(Boolean).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function V2Facts({ context, canReadTasks, canReadProjects }: { context: UnknownRecord; canReadTasks: boolean; canReadProjects: boolean }) {
  const totals = isRecord(context.totals) ? context.totals : {}
  const unassigned = isRecord(context.unassigned) ? context.unassigned : null
  const groups = [
    ...records(context.projects),
    ...records(context.unresolved_projects),
    ...(unassigned && ["task_total", "completed_total", "in_progress_total", "pending_total", "total_minutes"].some(key => number(unassigned[key]) > 0) ? [unassigned] : []),
  ]
  return (
    <div className="mt-4 space-y-5">
      <p className="text-sm text-muted-foreground">Hechos guardados al generar el resumen para apoyar la revisión. Los estados actuales son una instantánea de ese momento y el tiempo de cada tarea es acumulado. El texto generado puede necesitar ajustes.</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-muted p-3"><FolderKanban className="mb-2 h-4 w-4" /><strong className="block text-lg">{number(totals.project_count)}</strong><span className="text-xs text-muted-foreground">proyectos incluidos</span></div>
        <div className="rounded-lg bg-muted p-3"><ListChecks className="mb-2 h-4 w-4" /><strong className="block text-lg">{number(totals.completed_total)}</strong><span className="text-xs text-muted-foreground">completadas en período</span></div>
        <div className="rounded-lg bg-muted p-3"><ListChecks className="mb-2 h-4 w-4" /><strong className="block text-lg">{number(totals.pending_total) + number(totals.in_progress_total)}</strong><span className="text-xs text-muted-foreground">activas al generar</span></div>
        <div className="rounded-lg bg-muted p-3"><Clock3 className="mb-2 h-4 w-4" /><strong className="block text-lg">{number(totals.total_minutes)} min</strong><span className="text-xs text-muted-foreground">registrados en período</span></div>
      </div>
      {number(totals.unresolved_project_count) > 0 && <p className="text-xs text-muted-foreground">{number(totals.unresolved_project_count)} referencia de proyecto no pudo resolverse; se mantiene separada para evitar atribuciones incorrectas.</p>}
      <div className="space-y-3">{groups.map((group, index) => <ProjectFacts key={`${id(group.project_id) ?? "none"}-${index}`} group={group} canReadTasks={canReadTasks} canReadProjects={canReadProjects} />)}</div>
      <Followups value={context.pending_followups} />
    </div>
  )
}

function LegacyFacts({ context, canReadTasks }: { context: UnknownRecord; canReadTasks: boolean }) {
  const projectName = text(context.project_name)
  const progress = typeof context.project_progress === "number" ? context.project_progress : null
  const sections = [
    { label: "Completadas en la muestra guardada", tasks: records(context.completed_tasks) },
    { label: "En curso en la muestra guardada", tasks: records(context.in_progress_tasks) },
    { label: "Pendientes en la muestra guardada", tasks: records(context.pending_tasks) },
  ]
  const sampleSize = sections.reduce((total, section) => total + section.tasks.length, 0)
  return (
    <div className="mt-4 space-y-4">
      <p className="text-sm text-muted-foreground">Contexto guardado con el formato anterior. Las listas son muestras sin totales conocidos y no se atribuyen al proyecto mostrado.</p>
      {projectName && (
        <section className="rounded-xl border bg-card p-4 sm:p-5">
          <h3 className="font-semibold">Progreso histórico de {projectName}</h3>
          {progress !== null && <p className="mt-1 text-sm text-muted-foreground">Progreso guardado: {progress}%</p>}
        </section>
      )}
      <section className="rounded-xl border bg-card p-4 sm:p-5 space-y-4">
        <div><h3 className="font-semibold">Tareas del contexto guardado</h3><p className="text-xs text-muted-foreground">{sampleSize} tareas en la muestra guardada</p></div>
        <div className="grid gap-4 lg:grid-cols-3">
          {sections.map(section => <FactTasks key={section.label} label={section.label} total={section.tasks.length} tasks={section.tasks} canReadTasks={canReadTasks} knownTotal={false} />)}
        </div>
        {number(context.total_minutes) > 0 && <p className="text-sm text-muted-foreground">Tiempo registrado en el contexto: {number(context.total_minutes)} min</p>}
      </section>
      <Followups value={context.pending_followups} />
    </div>
  )
}

export function DigestFacts({ context }: DigestFactsProps) {
  const { hasPermission } = useAuth()
  const canReadTasks = hasPermission("tasks")
  const canReadProjects = hasPermission("projects")
  const isV2 = context.context_version === 2 && Array.isArray(context.projects)
  const isLegacy = !context.context_version && ["completed_tasks", "in_progress_tasks", "pending_tasks", "project_name"].some(key => key in context)
  return (
    <details className="rounded-xl border p-4">
      <summary className="cursor-pointer font-medium">Hechos fuente del resumen</summary>
      {isV2 ? <V2Facts context={context} canReadTasks={canReadTasks} canReadProjects={canReadProjects} /> : isLegacy ? <LegacyFacts context={context} canReadTasks={canReadTasks} /> : (
        <details className="mt-4 rounded-lg bg-muted p-3"><summary className="cursor-pointer text-sm font-medium">Ver datos técnicos no reconocidos</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(context, null, 2)}</pre></details>
      )}
    </details>
  )
}
