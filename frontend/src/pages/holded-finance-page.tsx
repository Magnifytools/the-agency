import { useState } from "react"
import { keepPreviousData, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { holdedApi } from "@/lib/api"
import { holdedKeys, isHoldedQueryKey } from "@/lib/query-keys"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { MetricCard } from "@/components/dashboard/metric-card"
import {
  RefreshCw, DollarSign, TrendingUp, TrendingDown, Receipt,
  FileText, Settings, CheckCircle, XCircle, Clock, Download,
  AlertTriangle, Wifi, WifiOff,
} from "lucide-react"
import { toast } from "sonner"
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { getErrorMessage } from "@/lib/utils"

type TabKey = "resumen" | "facturas" | "gastos" | "config"
const SYNC_LOG_LIMIT = 20

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: "resumen", label: "Resumen", icon: TrendingUp },
  { key: "facturas", label: "Facturas", icon: FileText },
  { key: "gastos", label: "Gastos", icon: Receipt },
  { key: "config", label: "Configuracion", icon: Settings },
]

function formatCurrency(v: number, currency = "EUR") {
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(v)
}

function formatDate(d: string | null) {
  if (!d) return "-"
  return new Date(d).toLocaleDateString("es-ES")
}

export default function HoldedFinancePage() {
  const [tab, setTab] = useState<TabKey>("resumen")
  const qc = useQueryClient()
  const invalidateHoldedQueries = () =>
    qc.invalidateQueries({
      predicate: (query) => isHoldedQueryKey(query.queryKey),
    })

  const { data: config } = useQuery({
    queryKey: holdedKeys.config(),
    queryFn: () => holdedApi.config(),
    retry: false,
  })

  const syncAllMutation = useMutation({
    mutationFn: () => holdedApi.syncAll(),
    onSuccess: (results) => {
      const ok = results.filter((r) => r.status === "success").length
      toast.success(`Sincronizacion completada: ${ok}/${results.length} exitosos`)
      void invalidateHoldedQueries()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al sincronizar")),
  })

  const connected = Boolean(config?.api_key_configured)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Finanzas</h2>
          <div className="flex items-center gap-2 mt-1">
            {connected ? (
              <Badge variant="success" className="flex items-center gap-1">
                <Wifi className="h-3 w-3" /> Holded conectado
              </Badge>
            ) : (
              <Badge variant="secondary" className="flex items-center gap-1">
                <WifiOff className="h-3 w-3" /> Sin conexion
              </Badge>
            )}
            {config?.last_sync_invoices?.completed_at && (
              <span className="text-xs text-muted-foreground">
                Ultimo sync: {formatDate(config.last_sync_invoices.completed_at)}
              </span>
            )}
          </div>
        </div>
        <Button
          onClick={() => syncAllMutation.mutate()}
          disabled={syncAllMutation.isPending || !connected}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${syncAllMutation.isPending ? "animate-spin" : ""}`} />
          {syncAllMutation.isPending ? "Sincronizando..." : "Sincronizar"}
        </Button>
      </div>

      {/* Tabs */}
      <div className="overflow-x-auto pb-1">
        <div className="inline-flex min-w-max gap-1 bg-muted/30 border border-border rounded-lg p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
                tab === t.key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "resumen" && <ResumenTab connected={connected} />}
      {tab === "facturas" && <FacturasTab connected={connected} />}
      {tab === "gastos" && <GastosTab connected={connected} />}
      {tab === "config" && <ConfigTab onInvalidateHolded={invalidateHoldedQueries} />}
    </div>
  )
}

// ── Resumen Tab ──────────────────────────────────────────

function ResumenTab({ connected }: { connected: boolean }) {
  const { data: dashboard, isLoading, error, refetch } = useQuery({
    queryKey: holdedKeys.dashboard(),
    queryFn: () => holdedApi.dashboard(),
    enabled: connected,
    staleTime: 60_000,
    retry: false,
  })

  if (!connected) return <div className="text-muted-foreground">Configura la conexion con Holded para ver el resumen.</div>
  if (isLoading) return <div className="text-muted-foreground">Cargando...</div>
  if (error) return <div className="text-red-500 text-sm">Error al cargar datos. <button className="underline ml-1" onClick={() => refetch()}>Reintentar</button></div>
  if (!dashboard) return null

  const chartData = dashboard.monthly_data.map((m) => ({
    name: m.month.slice(5), // "MM"
    Ingresos: m.income,
    Gastos: m.expenses,
    Beneficio: m.profit,
  }))

  return (
    <div className="space-y-6">
      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard icon={TrendingUp} label="Ingresos este mes" value={formatCurrency(dashboard.income_this_month)} />
        <MetricCard icon={TrendingDown} label="Gastos este mes" value={formatCurrency(dashboard.expenses_this_month)} />
        <MetricCard
          icon={DollarSign}
          label="Beneficio"
          value={formatCurrency(dashboard.profit_this_month)}
          subtitle={dashboard.profit_this_month >= 0 ? "Positivo" : "Negativo"}
        />
        <MetricCard icon={TrendingUp} label="Ingresos YTD" value={formatCurrency(dashboard.income_ytd)} />
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Ingresos vs Gastos (ultimos 6 meses)</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                  formatter={(val: unknown) => formatCurrency(Number(val))}
                />
                <Legend />
                <Bar dataKey="Ingresos" fill="#22c55e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Gastos" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Pending invoices */}
      {dashboard.pending_invoices.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              Facturas pendientes de cobro ({dashboard.pending_invoices.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Numero</TableHead>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Fecha</TableHead>
                    <TableHead>Vencimiento</TableHead>
                    <TableHead>Importe</TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dashboard.pending_invoices.map((inv) => (
                    <TableRow key={inv.id}>
                      <TableCell className="font-medium">{inv.invoice_number || "-"}</TableCell>
                      <TableCell>{inv.contact_name || "-"}</TableCell>
                      <TableCell className="mono">{formatDate(inv.date)}</TableCell>
                      <TableCell className="mono">{formatDate(inv.due_date)}</TableCell>
                      <TableCell className="mono font-medium">{formatCurrency(inv.total, inv.currency)}</TableCell>
                      <TableCell>
                        <InvoiceStatusBadge status={inv.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="md:hidden space-y-3">
              {dashboard.pending_invoices.map((inv) => (
                <div key={inv.id} className="rounded-lg border border-border p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium truncate">{inv.invoice_number || "-"}</p>
                    <InvoiceStatusBadge status={inv.status} />
                  </div>
                  <p className="text-sm text-muted-foreground truncate">{inv.contact_name || "-"}</p>
                  <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <p>Fecha: {formatDate(inv.date)}</p>
                    <p>Vence: {formatDate(inv.due_date)}</p>
                  </div>
                  <p className="mono text-sm font-medium">{formatCurrency(inv.total, inv.currency)}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── Facturas Tab ─────────────────────────────────────────

function FacturasTab({ connected }: { connected: boolean }) {
  const [statusFilter, setStatusFilter] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: holdedKeys.invoices(statusFilter, dateFrom, dateTo, page),
    queryFn: () =>
      holdedApi.invoices({
        status: statusFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        page_size: 50,
      }),
    enabled: connected,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const invoices = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / 50)

  // Reset page when filters change
  const updateFilter = (setter: (v: string) => void, value: string) => {
    setter(value)
    setPage(1)
  }

  const handleDownloadPdf = async (holdedId: string, invoiceNumber: string | null) => {
    try {
      const blob = await holdedApi.invoicePdf(holdedId)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `factura-${invoiceNumber || holdedId}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      toast.error("Error al descargar PDF")
    }
  }

  const hasError = !isLoading && !data

  if (!connected) return <div className="text-muted-foreground">Conecta Holded para consultar facturas.</div>

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap">
        <Select value={statusFilter} onChange={(e) => updateFilter(setStatusFilter, e.target.value)} className="w-[160px]">
          <option value="">Todos</option>
          <option value="paid">Pagada</option>
          <option value="pending">Pendiente</option>
          <option value="overdue">Vencida</option>
        </Select>
        <Input
          type="date"
          value={dateFrom}
          onChange={(e) => updateFilter(setDateFrom, e.target.value)}
          className="w-[160px]"
          placeholder="Desde"
        />
        <Input
          type="date"
          value={dateTo}
          onChange={(e) => updateFilter(setDateTo, e.target.value)}
          className="w-[160px]"
          placeholder="Hasta"
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {hasError && (
            <p className="text-sm text-red-500 mb-4">Error al cargar facturas. Reintenta sincronizar o recargar.</p>
          )}
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Numero</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Vencimiento</TableHead>
                  <TableHead>Subtotal</TableHead>
                  <TableHead>IVA</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoices.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell className="font-medium">{inv.invoice_number || "-"}</TableCell>
                    <TableCell>{inv.contact_name || "-"}</TableCell>
                    <TableCell className="mono">{formatDate(inv.date)}</TableCell>
                    <TableCell className="mono">{formatDate(inv.due_date)}</TableCell>
                    <TableCell className="mono">{formatCurrency(inv.subtotal)}</TableCell>
                    <TableCell className="mono">{formatCurrency(inv.tax)}</TableCell>
                    <TableCell className="mono font-medium">{formatCurrency(inv.total, inv.currency)}</TableCell>
                    <TableCell>
                      <InvoiceStatusBadge status={inv.status} />
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDownloadPdf(inv.holded_id, inv.invoice_number)}
                        title="Descargar PDF"
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!isLoading && invoices.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                      No hay facturas. Sincroniza con Holded primero.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="md:hidden space-y-3">
            {invoices.map((inv) => (
              <div key={inv.id} className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium truncate">{inv.invoice_number || "-"}</p>
                  <InvoiceStatusBadge status={inv.status} />
                </div>
                <p className="text-sm text-muted-foreground truncate">{inv.contact_name || "-"}</p>
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <p>Fecha: {formatDate(inv.date)}</p>
                  <p>Vence: {formatDate(inv.due_date)}</p>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <p className="mono">Sub: {formatCurrency(inv.subtotal)}</p>
                  <p className="mono">IVA: {formatCurrency(inv.tax)}</p>
                  <p className="mono font-medium">Tot: {formatCurrency(inv.total, inv.currency)}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => handleDownloadPdf(inv.holded_id, inv.invoice_number)}
                >
                  <Download className="h-4 w-4 mr-2" />
                  Descargar PDF
                </Button>
              </div>
            ))}
            {!isLoading && invoices.length === 0 && (
              <div className="rounded-lg border border-border p-4 text-center text-sm text-muted-foreground">
                No hay facturas. Sincroniza con Holded primero.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{total} facturas</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</Button>
            <span className="flex items-center px-2">Página {page} de {totalPages}</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Siguiente</Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Gastos Tab ───────────────────────────────────────────

function GastosTab({ connected }: { connected: boolean }) {
  const [categoryFilter, setCategoryFilter] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: holdedKeys.expenses(categoryFilter, dateFrom, dateTo, page),
    queryFn: () =>
      holdedApi.expenses({
        category: categoryFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        page_size: 50,
      }),
    enabled: connected,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const expenses = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / 50)

  const updateFilter = (setter: (v: string) => void, value: string) => {
    setter(value)
    setPage(1)
  }

  // Extract unique categories from current page
  const categories = [...new Set(expenses.map((e) => e.category).filter(Boolean))]
  const hasError = !isLoading && !data

  if (!connected) return <div className="text-muted-foreground">Conecta Holded para consultar gastos.</div>

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap">
        <Select value={categoryFilter} onChange={(e) => updateFilter(setCategoryFilter, e.target.value)} className="w-[200px]">
          <option value="">Todas las categorias</option>
          {categories.map((c) => (
            <option key={c!} value={c!}>{c}</option>
          ))}
        </Select>
        <Input
          type="date"
          value={dateFrom}
          onChange={(e) => updateFilter(setDateFrom, e.target.value)}
          className="w-[160px]"
        />
        <Input
          type="date"
          value={dateTo}
          onChange={(e) => updateFilter(setDateTo, e.target.value)}
          className="w-[160px]"
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {hasError && (
            <p className="text-sm text-red-500 mb-4">Error al cargar gastos. Reintenta sincronizar o recargar.</p>
          )}
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Descripcion</TableHead>
                  <TableHead>Proveedor</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Categoria</TableHead>
                  <TableHead>Subtotal</TableHead>
                  <TableHead>IVA</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {expenses.map((exp) => (
                  <TableRow key={exp.id}>
                    <TableCell className="font-medium max-w-[200px] truncate">{exp.description || "-"}</TableCell>
                    <TableCell>{exp.supplier || "-"}</TableCell>
                    <TableCell className="mono">{formatDate(exp.date)}</TableCell>
                    <TableCell>
                      {exp.category ? <Badge variant="secondary">{exp.category}</Badge> : "-"}
                    </TableCell>
                    <TableCell className="mono">{formatCurrency(exp.subtotal)}</TableCell>
                    <TableCell className="mono">{formatCurrency(exp.tax)}</TableCell>
                    <TableCell className="mono font-medium">{formatCurrency(exp.total)}</TableCell>
                    <TableCell>
                      <Badge variant={exp.status === "paid" ? "success" : "warning"}>
                        {exp.status === "paid" ? "Pagado" : "Pendiente"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {!isLoading && expenses.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                      No hay gastos. Sincroniza con Holded primero.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="md:hidden space-y-3">
            {expenses.map((exp) => (
              <div key={exp.id} className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium truncate">{exp.description || "-"}</p>
                  <Badge variant={exp.status === "paid" ? "success" : "warning"}>
                    {exp.status === "paid" ? "Pagado" : "Pendiente"}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground truncate">{exp.supplier || "-"}</p>
                <div className="flex items-center justify-between gap-2 text-xs">
                  {exp.category ? <Badge variant="secondary">{exp.category}</Badge> : <span className="text-muted-foreground">Sin categoria</span>}
                  <span className="text-muted-foreground">{formatDate(exp.date)}</span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <p className="mono">Sub: {formatCurrency(exp.subtotal)}</p>
                  <p className="mono">IVA: {formatCurrency(exp.tax)}</p>
                  <p className="mono font-medium">Tot: {formatCurrency(exp.total)}</p>
                </div>
              </div>
            ))}
            {!isLoading && expenses.length === 0 && (
              <div className="rounded-lg border border-border p-4 text-center text-sm text-muted-foreground">
                No hay gastos. Sincroniza con Holded primero.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{total} gastos</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</Button>
            <span className="flex items-center px-2">Página {page} de {totalPages}</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Siguiente</Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Config Tab ───────────────────────────────────────────

function ConfigTab({ onInvalidateHolded }: { onInvalidateHolded: () => Promise<unknown> }) {
  const { data: config } = useQuery({
    queryKey: holdedKeys.config(),
    queryFn: () => holdedApi.config(),
    staleTime: 60_000,
    retry: false,
  })

  const { data: logs } = useQuery({
    queryKey: holdedKeys.syncLogs(SYNC_LOG_LIMIT),
    queryFn: () => holdedApi.syncLogs(SYNC_LOG_LIMIT),
    retry: false,
  })

  const testMutation = useMutation({
    mutationFn: () => holdedApi.testConnection(),
    onSuccess: (result) => {
      if (result.success) {
        toast.success(result.message)
      } else {
        toast.error(result.message)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al probar conexion")),
  })

  const syncContactsMutation = useMutation({
    mutationFn: () => holdedApi.syncContacts(),
    onSuccess: (r) => {
      toast.success(`Contactos sincronizados: ${r.records_synced}`)
      void onInvalidateHolded()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al sincronizar contactos")),
  })

  return (
    <div className="space-y-6">
      {/* Connection status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Estado de conexion</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            {config?.api_key_configured ? (
              <div className="flex items-center gap-2 text-green-400">
                <CheckCircle className="h-5 w-5" />
                <span className="text-sm font-medium">API Key configurada</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-muted-foreground">
                <XCircle className="h-5 w-5" />
                <span className="text-sm">HOLDED_API_KEY no configurada en el servidor (.env)</span>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending || !config?.api_key_configured}
            >
              {testMutation.isPending ? "Probando..." : "Probar conexion"}
            </Button>
            <Button
              variant="outline"
              onClick={() => syncContactsMutation.mutate()}
              disabled={syncContactsMutation.isPending || !config?.api_key_configured}
            >
              {syncContactsMutation.isPending ? "Sincronizando..." : "Sync contactos"}
            </Button>
          </div>

          <p className="text-xs text-muted-foreground">
            La API Key se configura en el archivo .env del servidor (HOLDED_API_KEY). La sincronizacion es manual.
          </p>
        </CardContent>
      </Card>

      {/* Last sync status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Ultimo sync por tipo</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            {(["contacts", "invoices", "expenses"] as const).map((type) => {
              const label = type === "contacts" ? "Contactos" : type === "invoices" ? "Facturas" : "Gastos"
              const log =
                type === "contacts"
                  ? config?.last_sync_contacts
                  : type === "invoices"
                  ? config?.last_sync_invoices
                  : config?.last_sync_expenses

              return (
                <div key={type} className="border border-border rounded-lg p-3">
                  <div className="text-xs text-muted-foreground mb-1">{label}</div>
                  {log ? (
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5">
                        <SyncStatusIcon status={log.status} />
                        <span className="text-sm font-medium">{log.records_synced} registros</span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {log.completed_at ? formatDate(log.completed_at) : "En progreso"}
                      </div>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">Nunca sincronizado</span>
                  )}
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Sync logs */}
      {logs && logs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Historial de sincronizaciones</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Registros</TableHead>
                    <TableHead>Inicio</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell className="font-medium">{log.sync_type}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <SyncStatusIcon status={log.status} />
                          <span className="text-sm">{log.status}</span>
                        </div>
                      </TableCell>
                      <TableCell className="mono">{log.records_synced}</TableCell>
                      <TableCell className="mono text-xs">{formatDate(log.started_at)}</TableCell>
                      <TableCell className="text-xs text-red-400 max-w-[200px] truncate">
                        {log.error_message || "-"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="md:hidden space-y-3">
              {logs.map((log) => (
                <div key={log.id} className="rounded-lg border border-border p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{log.sync_type}</p>
                    <div className="flex items-center gap-1.5 text-xs">
                      <SyncStatusIcon status={log.status} />
                      <span>{log.status}</span>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">Inicio: {formatDate(log.started_at)}</p>
                  <p className="text-xs">Registros: <span className="mono">{log.records_synced}</span></p>
                  {log.error_message && <p className="text-xs text-red-400 break-words">{log.error_message}</p>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────

function InvoiceStatusBadge({ status }: { status: string | null }) {
  if (!status) return <Badge variant="secondary">-</Badge>
  const map: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "secondary" }> = {
    paid: { label: "Pagada", variant: "success" },
    pending: { label: "Pendiente", variant: "warning" },
    overdue: { label: "Vencida", variant: "destructive" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" as const }
  return <Badge variant={variant}>{label}</Badge>
}

function SyncStatusIcon({ status }: { status: string }) {
  if (status === "success") return <CheckCircle className="h-3.5 w-3.5 text-green-400" />
  if (status === "error") return <XCircle className="h-3.5 w-3.5 text-red-400" />
  return <Clock className="h-3.5 w-3.5 text-yellow-400" />
}
