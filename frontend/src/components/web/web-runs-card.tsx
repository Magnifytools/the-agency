import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { History } from "lucide-react"
import { webWatchesApi } from "@/lib/api"
import type { WebSweepRun } from "@/lib/types"
import { webKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatInstant } from "@/components/web/uptime-status"
import { RUN_STATUS_LABEL, notifyLabel, pathOf } from "@/components/web/change-format"

/** Últimos barridos del cliente: cuántas URLs, cuántos cambios y qué pasó con Slack. */
export function WebRunsCard({ clientId }: { clientId: number }) {
  const [openRun, setOpenRun] = useState<string | null>(null)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: webKeys.runs(clientId),
    queryFn: () => webWatchesApi.runs(clientId, 10),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><History className="h-4 w-4" /> Últimos barridos</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p role="status" className="text-sm text-muted-foreground">Cargando barridos…</p>
        ) : isError || !data ? (
          <div role="alert" className="flex items-center justify-between gap-3 text-sm">
            <span>No se pudieron cargar los barridos.</span>
            <Button size="sm" variant="outline" onClick={() => refetch()}>Reintentar</Button>
          </div>
        ) : data.runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no ha corrido ningún barrido para este cliente.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Inicio</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead className="text-right">URLs</TableHead>
                  <TableHead className="text-right">Cambios</TableHead>
                  <TableHead>Slack</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.runs.map((run) => (
                  <RunRow key={run.id} run={run} open={openRun === run.id} onToggle={() => setOpenRun(openRun === run.id ? null : run.id)} />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RunRow({ run, open, onToggle }: { run: WebSweepRun; open: boolean; onToggle: () => void }) {
  const notify = notifyLabel(run.notify_status)
  return (
    <>
      <TableRow>
        <TableCell className="text-xs whitespace-nowrap">{formatInstant(run.started_at)}</TableCell>
        <TableCell className="text-xs">{run.trigger === "scheduler" ? "Programado" : "A mano"}</TableCell>
        <TableCell className={cn("text-xs", run.status === "failed" && "text-red-300", run.status === "partial" && "text-amber-300")}>
          {RUN_STATUS_LABEL[run.status] ?? run.status}
        </TableCell>
        <TableCell className="text-right text-xs mono whitespace-nowrap">
          {run.watches_done}/{run.watches_total}
          {run.watches_error > 0 && (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              className="ml-1 text-red-300 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm"
            >
              {run.watches_error} con error
            </button>
          )}
        </TableCell>
        <TableCell className="text-right text-xs mono">{run.changes_found}</TableCell>
        <TableCell className={cn("text-xs", notify.warn && "text-amber-300")} title={run.notify_error ?? undefined}>{notify.text}</TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={6}><RunErrors runId={run.id} /></TableCell>
        </TableRow>
      )}
    </>
  )
}

function RunErrors({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({ queryKey: webKeys.runErrors(runId), queryFn: () => webWatchesApi.runErrors(runId) })
  if (isLoading) return <p role="status" className="text-xs text-muted-foreground">Cargando errores…</p>
  if (!data?.errors.length) return <p className="text-xs text-muted-foreground">Sin errores guardados.</p>
  return (
    <ul className="space-y-1 text-xs">
      {data.errors.map((e) => (
        <li key={e.id} className="break-words">
          <span className="mono">{e.url ? pathOf(e.url) : e.kind}</span>
          {e.status_code ? <span className="mono"> · HTTP {e.status_code}</span> : null}
          <span className="text-muted-foreground"> · {e.message}</span>
        </li>
      ))}
    </ul>
  )
}
