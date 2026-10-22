import { useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Archive, ArchiveRestore, Bell, BellOff, Eye, Plus, RefreshCw } from "lucide-react"
import { webWatchesApi } from "@/lib/api"
import type { WebBulkResult, WebCheckProgress, WebWatch } from "@/lib/types"
import { invalidateWebWatches, webKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatInstant } from "@/components/web/uptime-status"
import { pathOf } from "@/components/web/change-format"
import { Segmented, WatchHealthBadge } from "@/components/web/web-change-ui"
import { WatchDrawer } from "@/components/web/watch-drawer"

type AddMode = "one" | "list" | "sitemap"

const busyOf = (p: WebCheckProgress | undefined) =>
  Boolean(p && p.enabled && (p.is_running || p.queued.length > 0))

/**
 * URLs vigiladas por cambios de un cliente. "Comprobar" no corre nada en la
 * petición: deja la marca y el job web_sweep la recoge en menos de un minuto;
 * mientras, el progreso se consulta cada 3 s para que se distinga "trabajando"
 * de "roto" (lección 0ter de Vigil).
 */
export function WebWatchesCard({ clientId }: { clientId: number }) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const qc = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [adding, setAdding] = useState(false)
  const [openWatch, setOpenWatch] = useState<string | null>(null)

  const progress = useQuery({
    queryKey: webKeys.progress(clientId),
    queryFn: () => webWatchesApi.progress(clientId),
    refetchInterval: (query) => (busyOf(query.state.data) ? 3_000 : false),
  })
  const busy = busyOf(progress.data)
  const watches = useQuery({
    queryKey: webKeys.watches(clientId, showArchived),
    queryFn: () => webWatchesApi.list(clientId, { include_archived: showArchived }),
    refetchInterval: busy ? 5_000 : false,
  })

  // Al terminar el barrido cambian la lista, los cambios y los barridos.
  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && !busy) void invalidateWebWatches(qc)
    wasBusy.current = busy
  }, [busy, qc])

  const onCheckAccepted = (enabled: boolean, what: string) => {
    toast.success(enabled
      ? `${what}: el barrido lo recoge en menos de un minuto.`
      : `${what}, pero el barrido está apagado: no se comprobará hasta encenderlo.`)
    void qc.invalidateQueries({ queryKey: webKeys.progress(clientId) })
    void qc.invalidateQueries({ queryKey: webKeys.watchLists() })
  }
  const checkAll = useMutation({
    mutationFn: () => webWatchesApi.checkAll(clientId),
    onSuccess: (r) => onCheckAccepted(r.enabled, `${r.watches ?? 0} URLs pedidas`),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const checkOne = useMutation({
    mutationFn: (watch: WebWatch) => webWatchesApi.check(watch.id),
    onSuccess: (r) => onCheckAccepted(r.enabled, "Comprobación pedida"),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const toggleMute = useMutation({
    mutationFn: (watch: WebWatch) => webWatchesApi.update(watch.id, { muted: !watch.muted }),
    onSuccess: (w) => {
      toast.success(w.muted ? "Silenciada: se guarda, pero no avisa" : "Vuelve a avisar")
      void invalidateWebWatches(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const archive = useMutation({
    mutationFn: (watch: WebWatch) => (watch.archived_at ? webWatchesApi.restore(watch.id) : webWatchesApi.archive(watch.id)),
    onSuccess: (w) => {
      toast.success(w.archived_at ? "Archivada, con su historial intacto" : "Recuperada")
      void invalidateWebWatches(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const data = watches.data
  const activeCount = data?.watches.filter((w) => w.is_active && !w.archived_at).length ?? 0

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Eye className="h-4 w-4" /> Cambios en la web: URLs vigiladas
        </CardTitle>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)} aria-expanded={adding}>
              <Plus className="h-4 w-4 mr-1" /> Añadir URLs
            </Button>
            <Button size="sm" onClick={() => checkAll.mutate()} disabled={checkAll.isPending || busy || activeCount === 0}>
              <RefreshCw className="h-3.5 w-3.5 mr-1" /> Comprobar todas
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {data && !data.enabled && (
          <p className="text-sm text-amber-600">
            El barrido de cambios está apagado: las URLs se guardan, pero no se comprueban (ni a mano) hasta encenderlo.
          </p>
        )}
        {data?.enabled && !data.monitored && (
          <p className="text-sm text-muted-foreground">Este cliente no está activo o es interno: sus URLs no se comprueban.</p>
        )}

        <ProgressLine progress={progress.data} />

        {adding && canWrite && <AddWatches clientId={clientId} onDone={() => void invalidateWebWatches(qc)} />}

        {watches.isLoading ? (
          <p role="status" className="text-sm text-muted-foreground">Cargando URLs…</p>
        ) : watches.isError || !data ? (
          <div role="alert" className="flex items-center justify-between gap-3 text-sm">
            <span>No se pudieron cargar las URLs vigiladas.</span>
            <Button size="sm" variant="outline" onClick={() => watches.refetch()}>Reintentar</Button>
          </div>
        ) : data.watches.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {showArchived ? "No hay URLs, tampoco archivadas." : "Todavía no se vigila ninguna URL de este cliente por cambios."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>URL</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Comprobada</TableHead>
                  <TableHead>Último cambio</TableHead>
                  {canWrite && <TableHead className="text-right">Acciones</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.watches.map((w) => (
                  <TableRow key={w.id}>
                    <TableCell className="min-w-[200px] max-w-[320px]">
                      <button
                        type="button"
                        onClick={() => setOpenWatch(w.id)}
                        className="text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm"
                        title={w.url}
                      >
                        <span className="mono text-sm hover:underline [overflow-wrap:anywhere]">{pathOf(w.url)}</span>
                        {w.label && <span className="block text-xs text-muted-foreground">{w.label}</span>}
                      </button>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1 whitespace-nowrap">
                        <WatchHealthBadge watch={w} />
                        {w.muted && <span className="text-xs text-muted-foreground" title="Se guarda, pero no avisa">Silenciada</span>}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap">
                      {formatInstant(w.state?.last_checked_at ?? null)}
                      {w.state?.last_status_code ? <span className="mono"> · {w.state.last_status_code}</span> : null}
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap">{formatInstant(w.state?.last_changed_at ?? null)}</TableCell>
                    {canWrite && (
                      <TableCell className="text-right whitespace-nowrap">
                        {!w.archived_at && (
                          <>
                            <Button size="sm" variant="ghost" aria-label={`Comprobar ahora ${w.url}`} title="Comprobar ahora"
                              disabled={!w.is_active || w.checking || checkOne.isPending} onClick={() => checkOne.mutate(w)}>
                              <RefreshCw className="h-3.5 w-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" aria-label={w.muted ? `Volver a avisar de ${w.url}` : `Silenciar ${w.url}`}
                              title={w.muted ? "Volver a avisar" : "Silenciar"} onClick={() => toggleMute.mutate(w)}>
                              {w.muted ? <Bell className="h-3.5 w-3.5" /> : <BellOff className="h-3.5 w-3.5" />}
                            </Button>
                          </>
                        )}
                        <Button size="sm" variant="ghost" aria-label={w.archived_at ? `Recuperar ${w.url}` : `Archivar ${w.url}`}
                          title={w.archived_at ? "Recuperar" : "Archivar"} onClick={() => archive.mutate(w)}>
                          {w.archived_at ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] text-muted-foreground">
            Se compara SEO, texto visible, enlaces y HTML con la última captura. Archivar la saca del barrido sin borrar su historial.
          </p>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" className="accent-[#FFD600]" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
            Ver archivadas
          </label>
        </div>

        <WatchDrawer watchId={openWatch} onClose={() => setOpenWatch(null)} />
      </CardContent>
    </Card>
  )
}

function ProgressLine({ progress: p }: { progress: WebCheckProgress | undefined }) {
  if (!p) return null
  if (!p.enabled) {
    return p.queued.length > 0 ? (
      <p role="status" className="text-xs text-amber-600">
        {p.queued.length === 1 ? "1 URL pedida espera" : `${p.queued.length} URLs pedidas esperan`} a que se encienda el barrido.
      </p>
    ) : null
  }
  if (p.is_running && p.last_run) {
    const { watches_done: done, watches_total: total } = p.last_run
    const pct = total ? Math.round((100 * done) / total) : 0
    return (
      <div role="status" className="space-y-1">
        <p className="text-xs">Comprobando <span className="mono">{done} de {total}</span>…</p>
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden" aria-hidden="true">
          <div className="h-full bg-brand transition-[width] duration-150" style={{ width: `${pct}%` }} />
        </div>
      </div>
    )
  }
  if (p.queued.length > 0) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        {p.queued.length === 1 ? "1 URL en cola" : `${p.queued.length} URLs en cola`}: el barrido las recoge en menos de un minuto.
      </p>
    )
  }
  return null
}

/** CSV o lista pegada: la primera celda de cada línea que parezca una URL. */
export function urlsFromText(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.split(/[,;\t]/)[0].trim().replace(/^"|"$/g, ""))
    .filter((cell) => /^https?:\/\//i.test(cell))
}

function AddWatches({ clientId, onDone }: { clientId: number; onDone: () => void }) {
  const [mode, setMode] = useState<AddMode>("one")
  const [url, setUrl] = useState("")
  const [label, setLabel] = useState("")
  const [list, setList] = useState("")
  const [source, setSource] = useState<"bulk" | "csv">("bulk")
  const [sitemap, setSitemap] = useState("")
  const [include, setInclude] = useState("")
  const [exclude, setExclude] = useState("")
  const [limit, setLimit] = useState(200)
  const [result, setResult] = useState<WebBulkResult | null>(null)

  const submit = useMutation({
    mutationFn: async (): Promise<WebBulkResult | null> => {
      if (mode === "one") {
        await webWatchesApi.create(clientId, { url, label: label.trim() || null })
        return null
      }
      if (mode === "list") return webWatchesApi.bulk(clientId, { urls: urlsFromText(list), source })
      return webWatchesApi.importSitemap(clientId, {
        sitemap_url: sitemap, include: include.trim() || null, exclude: exclude.trim() || null, limit,
      })
    },
    onSuccess: (r) => {
      setResult(r)
      if (!r) {
        toast.success("URL añadida")
        setUrl("")
        setLabel("")
      }
      onDone()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setResult(null)
    submit.mutate()
  }
  const listCount = urlsFromText(list).length

  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-border p-3">
      <Segmented<AddMode>
        label="Cómo añadir"
        value={mode}
        onChange={(m) => { setMode(m); setResult(null) }}
        options={[{ id: "one", label: "Una URL" }, { id: "list", label: "Lista o CSV" }, { id: "sitemap", label: "Sitemap" }]}
      />
      {mode === "one" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Input aria-label="URL a vigilar por cambios" className="mono" placeholder="https://ejemplo.com/servicios" value={url} onChange={(e) => setUrl(e.target.value)} required />
          <Input aria-label="Nombre de la URL (opcional)" placeholder="Nombre (opcional)" value={label} onChange={(e) => setLabel(e.target.value)} />
        </div>
      )}
      {mode === "list" && (
        <div className="space-y-2">
          <Textarea
            aria-label="URLs, una por línea"
            className="mono rounded-[10px]"
            rows={6}
            placeholder={"https://ejemplo.com/\nhttps://ejemplo.com/blog/"}
            value={list}
            onChange={(e) => { setList(e.target.value); setSource("bulk") }}
            required
          />
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span><span className="mono">{listCount}</span> URLs válidas a la vista (hasta 500 por vez; duplicadas e inválidas se cuentan aparte).</span>
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <span className="underline">Cargar CSV</span>
              <input
                type="file"
                accept=".csv,text/csv,text/plain"
                className="sr-only"
                aria-label="Cargar CSV de URLs"
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  setList(urlsFromText(await file.text()).join("\n"))
                  setSource("csv")
                }}
              />
            </label>
          </div>
        </div>
      )}
      {mode === "sitemap" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Input aria-label="URL del sitemap" className="mono sm:col-span-2" placeholder="https://ejemplo.com/sitemap_index.xml" value={sitemap} onChange={(e) => setSitemap(e.target.value)} required />
          <Input aria-label="Incluir sólo (regex)" className="mono" placeholder="Incluir sólo (regex), p. ej. /servicios/" value={include} onChange={(e) => setInclude(e.target.value)} />
          <Input aria-label="Excluir (regex)" className="mono" placeholder="Excluir (regex), p. ej. /tag/|/page/" value={exclude} onChange={(e) => setExclude(e.target.value)} />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Máximo
            <Input type="number" min={1} max={500} className="mono w-24" value={limit} onChange={(e) => setLimit(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} aria-label="Máximo de URLs" />
          </label>
          <p className="text-xs text-muted-foreground sm:col-span-2">Se siguen los índices anidados. La fecha de modificación se ignora: no es fiable.</p>
        </div>
      )}
      <Button type="submit" size="sm" disabled={submit.isPending || (mode === "list" && listCount === 0)}>
        {submit.isPending ? (mode === "sitemap" ? "Leyendo el sitemap…" : "Añadiendo…") : "Añadir"}
      </Button>
      {result && <BulkResult result={result} />}
    </form>
  )
}

function BulkResult({ result: r }: { result: WebBulkResult }) {
  return (
    <div role="status" className="text-sm space-y-1">
      <p>
        <span className="mono">{r.created}</span> añadidas
        {r.restored > 0 && <> · <span className="mono">{r.restored}</span> recuperadas del archivo</>}
        {r.skipped_duplicates > 0 && <> · <span className="mono">{r.skipped_duplicates}</span> ya estaban</>}
        {r.invalid.length > 0 && <> · <span className="mono">{r.invalid.length}</span> no válidas</>}
      </p>
      {r.found_in_sitemap !== undefined && (
        <p className="text-xs text-muted-foreground">
          {r.found_in_sitemap} encontradas en el sitemap
          {r.sitemap_has_more ? ` y hay más: sólo se han leído las ${r.limit_applied} primeras.` : "."}
        </p>
      )}
      {r.truncated && <p className="text-xs text-amber-600">Sólo se procesan 500 por vez: añade el resto en otra tanda.</p>}
      {r.invalid.length > 0 && (
        <ul className="mono text-xs text-muted-foreground max-h-32 overflow-y-auto">
          {r.invalid.slice(0, 20).map((i) => <li key={i.url} className="break-all">{i.url}: {i.reason}</li>)}
        </ul>
      )}
    </div>
  )
}
