import { useEffect, useState } from "react"
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { reportsApi } from "@/lib/api"
import type { Report } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { isEnabled } from "@/lib/hidden-modules"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

const PAGE_SIZE = 20
interface Props { clientId?: number; clientName?: string }

export function ReportArchive(props: Props) {
  const { user, hasPermission } = useAuth()
  const canRead = !!user && hasPermission("reports") && isEnabled("reports")
  const canWrite = canRead && hasPermission("reports", true)
  const identity = `${user?.id}:${user?.role}:${canRead}:${canWrite}:${props.clientId ?? "all"}`
  return canRead ? <ArchiveContents key={identity} {...props} identity={identity} canWrite={canWrite} /> : <p role="status">No tienes acceso al archivo de informes.</p>
}

function ArchiveContents({ clientId, clientName, identity, canWrite }: Props & { identity: string; canWrite: boolean }) {
  const { hasPermission } = useAuth()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Report | null>(null)
  const [toDelete, setToDelete] = useState<Report | null>(null)
  const query = useInfiniteQuery({
    queryKey: ["reports", "archive", identity],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => reportsApi.list({ client_id: clientId, limit: PAGE_SIZE, offset: pageParam }),
    getNextPageParam: (lastPage, _pages, offset) => lastPage.length === PAGE_SIZE ? offset + PAGE_SIZE : undefined,
  })
  const status = (query.error as { response?: { status?: number } } | null)?.response?.status
  const denied = status === 401 || status === 403
  const [accessRejected, setAccessRejected] = useState(false)
  useEffect(() => {
    if (denied) setAccessRejected(true)
    else if (query.isSuccess && !query.isFetching) setAccessRejected(false)
  }, [denied, query.isSuccess, query.isFetching])
  const accessBlocked = denied || accessRejected
  const reports = accessBlocked ? [] : (query.data?.pages.flat() ?? [])
  const remove = useMutation({
    mutationFn: reportsApi.delete,
    onSuccess: () => {
      setSelected(null)
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe eliminado")
    },
    onError: error => toast.error(getErrorMessage(error, "No se pudo eliminar el informe")),
  })
  const retry = () => query.isFetchNextPageError ? query.fetchNextPage() : query.refetch()
  const canOpen = !accessBlocked
  const exportPdf = async (id: number) => {
    try { await reportsApi.downloadPdf(id) }
    catch (error) { toast.error(getErrorMessage(error, "No se pudo descargar el informe")) }
  }

  return <section className="space-y-4" aria-label="Archivo de informes">
    <div>
      <h2 className="text-xl font-semibold">Informes anteriores{clientName ? ` de ${clientName}` : ""}</h2>
      <p className="mt-1 text-sm text-muted-foreground">Consulta y descarga el contenido guardado. Los nuevos resúmenes se preparan en Resúmenes de clientes.</p>
      {hasPermission("digests") && isEnabled("digests") && <Link className="mt-2 inline-block text-sm text-brand underline" to={clientId ? `/digests?client_id=${clientId}` : "/digests"}>Ir a Resúmenes de clientes</Link>}
    </div>
    {query.isPending && <p role="status">Cargando informes anteriores…</p>}
    {query.isError && <div role="alert" className="space-y-2 text-sm">
      <p>{denied ? "Tu acceso al archivo ha cambiado." : reports.length ? "Mostramos informes guardados; no se pudo actualizar el archivo." : "No se pudo cargar el archivo de informes."}</p>
      <Button variant="outline" size="sm" onClick={() => void retry()} disabled={query.isFetching}>Reintentar</Button>
    </div>}
    {!query.isPending && !query.isError && reports.length === 0 && <p className="text-sm text-muted-foreground">No hay informes anteriores.</p>}
    <ul className="space-y-2">
      {reports.map(report => <li key={report.id} className="flex min-w-0 items-start gap-2 rounded-xl border p-3">
        <button type="button" className="min-w-0 flex-1 text-left focus-visible:outline-brand" onClick={() => setSelected(report)}>
          <span className="block break-words font-medium">{report.title}</span>
          <span className="mt-1 block text-xs text-muted-foreground">{parseApiInstant(report.generated_at).toLocaleString("es-ES", { timeZone: getAgencyTimezone(), dateStyle: "medium", timeStyle: "short" })}</span>
          {report.summary && <span className="mt-2 block line-clamp-2 text-sm text-muted-foreground">{report.summary}</span>}
        </button>
        {canWrite && <Button variant="ghost" size="sm" aria-label={`Eliminar ${report.title}`} disabled={remove.isPending} onClick={() => setToDelete(report)}>Eliminar</Button>}
      </li>)}
    </ul>
    {query.hasNextPage && !query.isFetchNextPageError && <Button variant="outline" onClick={() => void query.fetchNextPage()} disabled={query.isFetching}>{query.isFetchingNextPage ? "Cargando…" : "Ver más informes"}</Button>}
    {selected && canOpen && <Dialog open onOpenChange={() => setSelected(null)}>
      <DialogHeader><DialogTitle>{selected.title}</DialogTitle></DialogHeader>
      <div className="space-y-4 break-words">
        {selected.sections.map((section, i) => <div key={i}><h3 className="font-medium">{section.title}</h3><p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{section.content}</p></div>)}
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={() => void exportPdf(selected.id)}>Descargar PDF</Button>
        <Button onClick={() => setSelected(null)}>Cerrar</Button>
      </div>
    </Dialog>}
    {canWrite && !accessBlocked && <ConfirmDialog open={!!toDelete} onOpenChange={open => { if (!open) setToDelete(null) }} title="Eliminar informe anterior" description={`Se eliminará «${toDelete?.title ?? ""}». Esta acción no se puede deshacer.`} confirmLabel="Eliminar" onConfirm={() => { if (toDelete) remove.mutate(toDelete.id) }} />}
  </section>
}
