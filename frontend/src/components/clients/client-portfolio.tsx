import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { clientStatusApi } from "@/lib/api"
import type { ClientCohort, ClientStatusLevel } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ClientStatusBadge, ClientStatusReasons, DigestCell, SeoCell, WorkCell } from "@/components/clients/client-status"

const SUMMARY: { level: ClientStatusLevel; label: string }[] = [
  { level: "act", label: "Actuar" },
  { level: "watch", label: "Vigilar" },
  { level: "ok", label: "Bien" },
  { level: "no_data", label: "Sin datos" },
]

/** Cartera: cómo va cada cliente activo, lo que pide actuar primero. */
export function ClientPortfolio({ cohort }: { cohort: ClientCohort }) {
  const query = useQuery({
    queryKey: ["client-portfolio", cohort],
    queryFn: () => clientStatusApi.portfolio(cohort),
    staleTime: 60_000,
  })

  if (query.isLoading) return <p role="status" className="py-8 text-center text-sm text-muted-foreground">Calculando el estado de los clientes…</p>
  if (query.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm text-muted-foreground">
        <span>No se pudo calcular el estado de los clientes.</span>
        <Button variant="outline" size="sm" onClick={() => void query.refetch()}>Reintentar</Button>
      </div>
    )
  }
  const rows = query.data ?? []
  if (rows.length === 0) return <p className="py-8 text-center text-sm text-muted-foreground">No hay clientes activos en esta cohorte.</p>

  const counts = Object.fromEntries(SUMMARY.map(({ level }) => [level, rows.filter((r) => r.status === level).length]))

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {SUMMARY.filter(({ level }) => counts[level]).map(({ level, label }) => `${counts[level]} ${label.toLowerCase()}`).join(" · ")}
      </p>

      {/* Móvil */}
      <div className="space-y-3 sm:hidden">
        {rows.map((row) => (
          <div key={row.client_id} className="space-y-2 rounded-xl border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-2">
              <Link to={`/clients/${row.client_id}`} className="font-medium text-brand hover:underline">{row.client_name}</Link>
              <ClientStatusBadge status={row.status} />
            </div>
            <ClientStatusReasons row={row} />
            <div className="grid grid-cols-2 gap-2 border-t pt-2">
              <SeoCell seo={row.seo} />
              <DigestCell digest={row.digest} />
            </div>
            <WorkCell tasks={row.tasks} month={row.month} />
          </div>
        ))}
      </div>

      {/* Escritorio */}
      <div className="hidden overflow-x-auto sm:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cliente</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Tráfico de Google</TableHead>
              <TableHead>Resumen</TableHead>
              <TableHead>Trabajo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.client_id} className="align-top">
                <TableCell><Link to={`/clients/${row.client_id}`} className="font-medium text-brand hover:underline">{row.client_name}</Link></TableCell>
                <TableCell className="min-w-56 space-y-1"><ClientStatusBadge status={row.status} /><ClientStatusReasons row={row} limit={3} /></TableCell>
                <TableCell><SeoCell seo={row.seo} /></TableCell>
                <TableCell><DigestCell digest={row.digest} /></TableCell>
                <TableCell><WorkCell tasks={row.tasks} month={row.month} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
