import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { AlertCircle, CheckCircle2, ChevronDown, CirclePause, Clock3, Loader2, RefreshCw } from "lucide-react"

import { jobRuntimeApi } from "@/lib/api"
import type { JobRuntimeState, JobRuntimeStatus } from "@/lib/types"
import { formatTimeAgo } from "@/lib/utils"
import { Button } from "@/components/ui/button"

const stateCopy: Record<JobRuntimeState, { label: string; className: string }> = {
  running: { label: "En curso", className: "bg-brand/10 text-brand" },
  stale: { label: "Requiere revisión", className: "bg-warning/10 text-warning" },
  failed: { label: "Con incidencias", className: "bg-destructive/10 text-destructive" },
  paused: { label: "Pausada", className: "bg-muted text-muted-foreground" },
  never: { label: "Aún sin ejecutar", className: "bg-muted text-muted-foreground" },
  success: { label: "Comprobado", className: "bg-success/10 text-success" },
}

function formatDate(value: string) {
  return `${formatTimeAgo(value)} · ${new Date(value).toLocaleString("es-ES")}`
}

function stateDetail(job: JobRuntimeStatus) {
  if (job.state === "running" && job.started_at) return `En curso desde ${formatDate(job.started_at)}`
  if (job.state === "failed" && job.last_failure_at) return `Falló ${formatDate(job.last_failure_at)}`
  if (job.state === "paused") return job.paused_reason || "El proceso está pausado."
  if (job.state === "never") return "Todavía no se ha ejecutado."
  if (job.last_success_at) return `Último éxito: ${formatDate(job.last_success_at)}`
  return "No hay una ejecución correcta registrada."
}

function StateIcon({ state }: { state: JobRuntimeState }) {
  if (state === "success") return <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
  if (state === "failed") return <AlertCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
  if (state === "stale") return <AlertCircle className="h-4 w-4 text-warning" aria-hidden="true" />
  if (state === "paused") return <CirclePause className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
  if (state === "running") return <Loader2 className="h-4 w-4 animate-spin text-brand" aria-hidden="true" />
  return <Clock3 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
}

export function JobRuntimeStatusPanel({ userId }: { userId: number | null | undefined }) {
  const [open, setOpen] = useState(false)
  const runtime = useQuery({
    queryKey: ["admin", "job-runtime", userId],
    queryFn: jobRuntimeApi.list,
    enabled: open && userId != null,
    staleTime: 30_000,
  })

  return (
    <section id="scheduled-processes" className="scroll-mt-8">
      <details
        className="rounded-2xl border border-border bg-card p-6"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">Procesos programados</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">Estado operativo de los procesos del equipo.</p>
          </div>
          <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </summary>

        {open && <div className="mt-4 space-y-3">
          <div className="flex justify-end">
            <Button variant="outline" size="sm" className="gap-2" onClick={() => void runtime.refetch()} disabled={runtime.isFetching}>
              {runtime.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Actualizar estado
            </Button>
          </div>

          {runtime.isPending && <div className="space-y-2" role="status" aria-label="Cargando procesos programados">
            {[1, 2, 3].map((row) => <div key={row} className="h-16 animate-pulse rounded-lg bg-muted" />)}
          </div>}

          {runtime.isError && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            {runtime.data ? "No se pudo actualizar el estado. Se muestran los últimos datos consultados." : "No se pudo cargar el estado de los procesos."} <button type="button" className="underline" onClick={() => void runtime.refetch()}>Reintentar</button>
          </div>}

          {!runtime.isPending && !runtime.isError && runtime.data?.jobs.length === 0 && <p className="py-4 text-sm text-muted-foreground">No hay procesos programados configurados.</p>}

          {runtime.data?.jobs.map((job) => <article key={job.key} className="rounded-lg border border-border p-4 text-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <StateIcon state={job.state} />
                  <h3 className="font-medium">{job.label}</h3>
                </div>
                {job.description && <p className="mt-1 text-muted-foreground">{job.description}</p>}
              </div>
              <span className={`w-fit shrink-0 whitespace-nowrap rounded-full px-2 py-1 text-xs font-medium ${stateCopy[job.state].className}`}>{stateCopy[job.state].label}</span>
            </div>
            <p className="mt-3 text-muted-foreground">{stateDetail(job)}</p>
            {(job.state === "failed" || job.state === "stale") && job.failure_summary && <p className={job.state === "failed" ? "mt-1 text-destructive" : "mt-1 text-warning"}>{job.failure_summary}</p>}
          </article>)}
        </div>}
      </details>
    </section>
  )
}
