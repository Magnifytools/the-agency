import { useInfiniteQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { FileDown, FileText, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { localReportApi, localReportHref, localReportKeys, localReportListApi, type LocalReportListItem } from "@/lib/local-report"
import { saveFile, type PdfFile } from "@/lib/pdf-download"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"

const PAGE = 20
const day = (value: string) => parseApiInstant(value).toLocaleDateString("es-ES", { timeZone: getAgencyTimezone(), day: "numeric", month: "short" })
const dayTime = (value: string) => parseApiInstant(value).toLocaleString("es-ES", { timeZone: getAgencyTimezone(), day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })

function download(fn: () => Promise<PdfFile>) {
  fn().then(saveFile).catch((error) => toast.error(getErrorMessage(error, "No se pudo descargar")))
}

/** Informes SEO locales de todos los clientes en /digests: cada versión se abre en
 *  la pestaña de su cliente. Respeta el filtro de cliente del historial. */
export function LocalReportHistory({ clientId }: { clientId: number | "" }) {
  const query = useInfiniteQuery({
    queryKey: [...localReportKeys.all, "list", clientId],
    queryFn: ({ pageParam }) => localReportListApi.list({ client_id: clientId || undefined, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => last.length === PAGE ? pages.length * PAGE : undefined,
  })
  const reports = query.data?.pages.flat() ?? []
  // Sin ninguno (y sin filtro que lo explique) la sección no aporta nada.
  if (query.isSuccess && reports.length === 0 && !clientId) return null

  return <section className="space-y-3" aria-labelledby="local-report-history">
    <div>
      <h2 id="local-report-history" className="text-lg font-semibold">Informes SEO local</h2>
      <p className="text-sm text-muted-foreground">Cada versión se abre en la pestaña "Informe SEO local" del cliente.</p>
    </div>
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cliente</TableHead>
              <TableHead>Periodo</TableHead>
              <TableHead>Entrega al cliente</TableHead>
              <TableHead>Generado</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending ? <TableRow><TableCell colSpan={5} className="text-center py-6"><Loader2 className="w-6 h-6 mx-auto animate-spin opacity-40" /></TableCell></TableRow>
              : query.isError && reports.length === 0 ? <TableRow><TableCell colSpan={5}><div role="alert" className="py-4 text-center">No se pudieron cargar los informes SEO local. <Button variant="outline" size="sm" onClick={() => void query.refetch()}>Reintentar</Button></div></TableCell></TableRow>
              : reports.length === 0 ? <TableRow className="hover:bg-transparent"><TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">Este cliente no tiene informes SEO local.</TableCell></TableRow>
              : reports.map((report) => <Row key={report.id} report={report} />)}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
    {query.hasNextPage && <Button variant="outline" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
      {query.isFetchingNextPage ? <><Loader2 className="size-4 mr-2 animate-spin" />Cargando informes…</> : "Cargar informes anteriores"}
    </Button>}
  </section>
}

function Row({ report }: { report: LocalReportListItem }) {
  const href = localReportHref(report.client_id, report.id)
  return <TableRow>
    <TableCell className="font-medium">
      <Link to={href} className="hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">{report.client_name}</Link>
    </TableCell>
    <TableCell>
      <Link to={href} className="hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">{report.period_label}</Link>
    </TableCell>
    <TableCell>
      {report.delivered_at
        ? <span className="text-sm"><Badge variant="success">Entregado</Badge> <span className="text-xs text-muted-foreground">{day(report.delivered_at)}{report.delivered_by_name ? ` · ${report.delivered_by_name}` : ""}</span></span>
        : <span className="text-sm text-muted-foreground">Sin entregar</span>}
    </TableCell>
    <TableCell>{report.generated_at ? dayTime(report.generated_at) : <span className="text-sm text-muted-foreground">Sin generar</span>}</TableCell>
    <TableCell className="text-right">
      <div className="flex justify-end items-center gap-1">
        <Link to={href} className="px-2 text-sm text-primary underline underline-offset-2" aria-label={`Abrir informe SEO local de ${report.client_name}, versión #${report.id}`}>Abrir</Link>
        {report.generated_at && <>
          <Button variant="ghost" size="sm" title="Descargar PDF" aria-label={`Descargar PDF del informe de ${report.client_name}, versión #${report.id}`}
            onClick={() => download(() => localReportApi.pdf(report.client_id, report.id))}><FileDown className="w-4 h-4" /></Button>
          <Button variant="ghost" size="sm" title="Descargar HTML" aria-label={`Descargar HTML del informe de ${report.client_name}, versión #${report.id}`}
            onClick={() => download(() => localReportApi.html(report.client_id, report.id))}><FileText className="w-4 h-4" /></Button>
        </>}
      </div>
    </TableCell>
  </TableRow>
}
