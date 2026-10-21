import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Activity } from "lucide-react"
import { webApi } from "@/lib/api"
import type { UptimeOverviewRow } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { UptimeStatusPill, formatInstant, formatPct } from "@/components/web/uptime-status"

const PROBLEM = new Set(["down", "blocked", "suspect"])

function since(row: UptimeOverviewRow) {
  const open = row.targets.find((t) => t.open_outage)?.open_outage
  if (open) return `${open.kind === "down" ? "Caída" : "Bloqueo"} desde el ${formatInstant(open.started_at)}`
  const checked = row.targets.map((t) => t.last_checked_at).filter(Boolean).sort().pop()
  return checked ? `Mirada el ${formatInstant(checked)}` : "—"
}

/** Disponibilidad: si responde la web de cada cliente activo, lo que falla primero. */
export default function WebPage() {
  const [onlyProblems, setOnlyProblems] = useState(false)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["web-uptime-overview"],
    queryFn: webApi.overview,
    refetchInterval: 60_000,
  })

  const counts = useMemo(() => {
    const rows = data?.clients ?? []
    return {
      down: rows.filter((r) => r.status === "down").length,
      blocked: rows.filter((r) => r.status === "blocked").length,
      up: rows.filter((r) => r.status === "up").length,
      none: rows.filter((r) => r.targets.length === 0).length,
    }
  }, [data])
  const rows = (data?.clients ?? []).filter((r) => !onlyProblems || (r.status && PROBLEM.has(r.status)))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Activity className="h-6 w-6" /> Disponibilidad</h1>
          <p className="text-sm text-muted-foreground">
            Si responde la web de cada cliente activo. Se mira cada {Math.round((data?.interval_seconds ?? 300) / 60)} minutos;
            un bloqueo (401/403/429) no es una caída.
          </p>
        </div>
        <Button variant={onlyProblems ? "secondary" : "outline"} size="sm" aria-pressed={onlyProblems} onClick={() => setOnlyProblems((v) => !v)}>
          Sólo con problemas
        </Button>
      </div>

      {data && !data.enabled && (
        <p role="note" className="text-sm text-amber-600">
          El monitor está apagado: no se comprueba ninguna web hasta encenderlo (UPTIME_ENABLED).
        </p>
      )}

      {data && (
        <p className="text-sm" aria-label="Resumen">
          <span className="text-red-400">{counts.down} caída{counts.down === 1 ? "" : "s"}</span> ·{" "}
          <span className="text-amber-500">{counts.blocked} bloqueada{counts.blocked === 1 ? "" : "s"}</span> ·{" "}
          <span className="text-green-500">{counts.up} responde{counts.up === 1 ? "" : "n"}</span> ·{" "}
          <span className="text-muted-foreground">{counts.none} sin URLs</span>
        </p>
      )}

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {isLoading ? (
            <p role="status" className="p-6 text-sm text-muted-foreground">Cargando…</p>
          ) : isError ? (
            <div role="alert" className="p-6 flex items-center justify-between gap-3 text-sm">
              <span>No se pudo cargar la disponibilidad.</span>
              <Button size="sm" variant="outline" onClick={() => refetch()}>Reintentar</Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>URLs</TableHead>
                  <TableHead>24 h</TableHead>
                  <TableHead>30 días</TableHead>
                  <TableHead>Detalle</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const active = row.targets.filter((t) => t.is_active)
                  const worst24 = active.map((t) => t.uptime_24h).filter((v): v is number => v !== null)
                  const worst30 = active.map((t) => t.uptime_30d).filter((v): v is number => v !== null)
                  return (
                    <TableRow key={row.client_id}>
                      <TableCell>
                        <Link to={`/clients/${row.client_id}?tab=web`} className="font-medium hover:underline">{row.client_name}</Link>
                      </TableCell>
                      <TableCell><UptimeStatusPill status={row.status} /></TableCell>
                      <TableCell className="text-xs">
                        {row.targets.length === 0
                          ? <span className="text-muted-foreground">{row.website ? `Sin URLs (web: ${row.website})` : "Sin URLs"}</span>
                          : row.targets.map((t) => <div key={t.id} className="truncate max-w-[280px]" title={t.url}>{t.label ? `${t.label} · ` : ""}{t.url}</div>)}
                      </TableCell>
                      <TableCell className="mono">{formatPct(worst24.length ? Math.min(...worst24) : null)}</TableCell>
                      <TableCell className="mono">{formatPct(worst30.length ? Math.min(...worst30) : null)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{since(row)}</TableCell>
                    </TableRow>
                  )
                })}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                      {onlyProblems ? "Ninguna web con problemas ahora mismo." : "No hay clientes activos."}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
