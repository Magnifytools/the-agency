import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ExternalLink, RefreshCw } from "lucide-react"
import { webWatchesApi } from "@/lib/api"
import type { WebWatch, WebWatchPreview, WebWatchUpdate } from "@/lib/types"
import { invalidateWebWatches, webKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { formatInstant } from "@/components/web/uptime-status"
import { formatInt, htmlOnlySummary } from "@/components/web/change-format"
import { SeverityBadge, WatchHealthBadge, WebDrawer } from "@/components/web/web-change-ui"

const FLAGS = [
  { key: "watch_seo", label: "Elementos SEO", hint: "title, description, H1/H2, canonical, robots, hreflang, schema. Siempre en la página entera." },
  { key: "watch_content", label: "Texto visible", hint: "El texto de la página (o de la sección acotada)." },
  { key: "watch_links", label: "Enlaces", hint: "Altas y bajas de enlaces internos y externos." },
  { key: "watch_html", label: "HTML", hint: "Cualquier cambio de maquetación. Hace más ruido; sólo avisa si nada más se movió." },
] as const

type FlagKey = (typeof FLAGS)[number]["key"]

const lines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean)

/** Historial y configuración de UNA URL vigilada. */
export function WatchDrawer({ watchId, onClose }: { watchId: string | null; onClose: () => void }) {
  return (
    <WebDrawer open={watchId !== null} onClose={onClose} title="URL vigilada">
      {watchId && <WatchDrawerBody watchId={watchId} />}
    </WebDrawer>
  )
}

function WatchDrawerBody({ watchId }: { watchId: string }) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const qc = useQueryClient()
  const detail = useQuery({ queryKey: webKeys.watch(watchId), queryFn: () => webWatchesApi.get(watchId) })
  const history = useQuery({ queryKey: webKeys.watchHistory(watchId), queryFn: () => webWatchesApi.history(watchId) })

  const update = useMutation({
    mutationFn: (data: WebWatchUpdate) => webWatchesApi.update(watchId, data),
    onSuccess: () => {
      toast.success("Guardado")
      void invalidateWebWatches(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const check = useMutation({
    mutationFn: () => webWatchesApi.check(watchId),
    onSuccess: (result) => {
      toast.success(result.enabled
        ? "Comprobación pedida: el barrido la recoge en menos de un minuto."
        : "Pedida, pero el barrido está apagado: no se comprobará hasta encenderlo.")
      void invalidateWebWatches(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  if (detail.isLoading) return <p role="status" className="text-sm text-muted-foreground">Cargando…</p>
  if (detail.isError || !detail.data) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 text-sm">
        <span>No se pudo cargar la URL.</span>
        <Button size="sm" variant="outline" onClick={() => detail.refetch()}>Reintentar</Button>
      </div>
    )
  }

  const { watch: w, changes } = detail.data
  const s = w.state
  const archived = Boolean(w.archived_at)

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <WatchHealthBadge watch={w} />
          {w.muted && <span className="text-xs text-muted-foreground">Silenciada: se guarda, no avisa</span>}
        </div>
        {w.label && <p className="font-medium">{w.label}</p>}
        <a href={w.url} target="_blank" rel="noopener noreferrer" className="mono text-xs text-muted-foreground hover:text-foreground break-all inline-flex items-center gap-1">
          {w.url} <ExternalLink className="h-3 w-3 shrink-0" />
        </a>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div><dt className="text-muted-foreground">Última comprobación</dt><dd>{formatInstant(s?.last_checked_at ?? null)}{s?.last_status_code ? <span className="mono"> · HTTP {s.last_status_code}</span> : null}</dd></div>
          <div><dt className="text-muted-foreground">Último cambio</dt><dd>{formatInstant(s?.last_changed_at ?? null)}</dd></div>
          {s?.title && <div className="sm:col-span-2"><dt className="text-muted-foreground">Title</dt><dd className="break-words">{s.title}</dd></div>}
          {s?.word_count !== null && s?.word_count !== undefined && (
            <div><dt className="text-muted-foreground">Palabras</dt><dd className="mono">{formatInt(s.word_count)}</dd></div>
          )}
          {s?.last_final_url && s.last_final_url !== w.url && (
            <div className="sm:col-span-2"><dt className="text-muted-foreground">Redirige a</dt><dd className="mono break-all">{s.last_final_url}</dd></div>
          )}
        </dl>
        {s?.last_error && (
          <p role="alert" className="text-sm text-red-300">
            Último error: {s.last_error}
            {s.consecutive_errors > 1 && <span className="mono"> ({s.consecutive_errors} seguidos)</span>}
          </p>
        )}
        {s?.needs_js_render && (
          <p className="text-sm text-amber-300">Apenas se extrae texto: la página parece necesitar JavaScript, y no se renderiza.</p>
        )}
        {s?.scope_missed && w.content_selector && (
          <p className="text-sm text-amber-300">
            La sección <code className="mono">{w.content_selector}</code> ya no existe en la página: se está vigilando la página entera.
          </p>
        )}
        {canWrite && !archived && (
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" onClick={() => check.mutate()} disabled={check.isPending || !w.is_active || w.checking}>
              <RefreshCw className="h-3.5 w-3.5 mr-1" /> {w.checking ? "Comprobando…" : "Comprobar ahora"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => update.mutate({ muted: !w.muted })} disabled={update.isPending}>
              {w.muted ? "Volver a avisar" : "Silenciar"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => update.mutate({ is_active: !w.is_active })} disabled={update.isPending}>
              {w.is_active ? "Pausar" : "Reanudar"}
            </Button>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Cambios de esta URL</h3>
        {changes.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ninguno todavía. Es lo normal hasta que alguien toque la página.</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {changes.map((c) => {
              const summary = htmlOnlySummary(c)
              return (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
                  <div className="min-w-0 flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={c.max_severity} />
                    <span className="mono text-xs text-muted-foreground">{formatInstant(c.detected_at)}</span>
                    <span className="text-xs">{summary ? summary.headline : c.items.map((i) => i.rule_label).join(" · ")}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {c.acknowledged_at && <span className="text-xs text-muted-foreground">Revisado</span>}
                    <Link to={`/web/cambios/${c.id}`} className="text-xs text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
                      Ver detalle
                    </Link>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {canWrite && !archived && (
        <WatchConfig watch={w} saving={update.isPending} onSave={(data) => update.mutate(data)} />
      )}

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Capturas guardadas</h3>
        <p className="text-xs text-muted-foreground">
          Sólo se guarda una copia cuando algo cambia: si nada cambió, la última ya es la de hoy.
        </p>
        {history.isLoading ? (
          <p role="status" className="text-xs text-muted-foreground">Cargando…</p>
        ) : (history.data?.snapshots.length ?? 0) === 0 ? (
          <p className="text-xs text-muted-foreground">Todavía ninguna.</p>
        ) : (
          <ul className="mono text-xs divide-y divide-border">
            {history.data!.snapshots.map((snap) => (
              <li key={snap.id} className="flex justify-between gap-3 py-1">
                <span>{formatInstant(snap.captured_at)}</span>
                <span className="text-muted-foreground">
                  {snap.status_code ? `HTTP ${snap.status_code}` : "—"}
                  {snap.byte_size ? ` · ${Math.round(snap.byte_size / 1024)} KB` : ""}
                  {snap.has_html ? " · HTML" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/**
 * Qué se vigila de esta URL. Antes de fiarse de un selector, "Probar esta
 * configuración" descarga la página y dice cuántas palabras se lleva cada
 * uno: un selector de poda mal elegido no hace ruido, hace SILENCIO (lección
 * 0quater de Vigil). Se prueba lo escrito en el formulario, no lo guardado.
 */
function WatchConfig({ watch: w, saving, onSave }: { watch: WebWatch; saving: boolean; onSave: (data: WebWatchUpdate) => void }) {
  const [label, setLabel] = useState(w.label ?? "")
  const [flags, setFlags] = useState<Record<FlagKey, boolean>>({
    watch_seo: w.watch_seo, watch_content: w.watch_content, watch_links: w.watch_links, watch_html: w.watch_html,
  })
  const [selector, setSelector] = useState(w.content_selector ?? "")
  const [ignoreSelectors, setIgnoreSelectors] = useState((w.ignore_selectors ?? []).join("\n"))
  const [ignoreRegexes, setIgnoreRegexes] = useState((w.ignore_regexes ?? []).join("\n"))
  const [preview, setPreview] = useState<WebWatchPreview | null>(null)

  useEffect(() => setPreview(null), [selector, ignoreSelectors, ignoreRegexes])

  // Lista vacía = vuelve a heredar del cliente (null).
  const listOrNull = (text: string) => (lines(text).length ? lines(text) : null)
  const probe = useMutation({
    mutationFn: () => webWatchesApi.preview(w.id, {
      content_selector: selector.trim() || null,
      ignore_selectors: listOrNull(ignoreSelectors),
      ignore_regexes: listOrNull(ignoreRegexes),
    }),
    onSuccess: setPreview,
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">Qué se vigila</h3>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          onSave({
            label: label.trim() || null,
            ...flags,
            content_selector: selector.trim() || null,
            ignore_selectors: listOrNull(ignoreSelectors),
            ignore_regexes: listOrNull(ignoreRegexes),
          })
        }}
      >
        <label className="block text-xs space-y-1">
          <span className="text-muted-foreground">Nombre</span>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Home, ficha de producto…" />
        </label>
        <fieldset className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <legend className="sr-only">Dimensiones vigiladas</legend>
          {FLAGS.map((flag) => (
            <label key={flag.key} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1 accent-[#FFD600] focus-visible:ring-2 focus-visible:ring-brand"
                checked={flags[flag.key]}
                onChange={(e) => setFlags((prev) => ({ ...prev, [flag.key]: e.target.checked }))}
              />
              <span>{flag.label}<span className="block text-xs text-muted-foreground">{flag.hint}</span></span>
            </label>
          ))}
        </fieldset>
        <label className="block text-xs space-y-1">
          <span className="text-muted-foreground">Sección vigilada (CSS). Acota texto, enlaces y HTML; el SEO se mide siempre en la página entera. Vacío = la del cliente o main/article/body.</span>
          <Input className="mono" value={selector} onChange={(e) => setSelector(e.target.value)} placeholder=".contenido, #claustro" />
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-xs space-y-1">
            <span className="text-muted-foreground">Ignorar selectores (uno por línea; vacío = los del cliente)</span>
            <Textarea className="mono rounded-[10px]" rows={3} value={ignoreSelectors} onChange={(e) => setIgnoreSelectors(e.target.value)} placeholder=".cookie-banner" />
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-muted-foreground">Ignorar patrones de texto (regex, uno por línea)</span>
            <Textarea className="mono rounded-[10px]" rows={3} value={ignoreRegexes} onChange={(e) => setIgnoreRegexes(e.target.value)} placeholder="\d{1,2}/\d{1,2}/\d{4}" />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={saving}>{saving ? "Guardando…" : "Guardar"}</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => probe.mutate()} disabled={probe.isPending}>
            {probe.isPending ? "Descargando la página…" : "Probar esta configuración"}
          </Button>
        </div>
      </form>
      {preview && <PreviewResult preview={preview} />}
    </section>
  )
}

function PreviewResult({ preview: p }: { preview: WebWatchPreview }) {
  const outside = p.page_words - p.watched_words
  return (
    <div role="status" className="rounded-lg border border-border p-3 text-sm space-y-2">
      <p>
        <span className="mono">HTTP {p.status_code}</span> · se vigilan <strong className="mono">{formatInt(p.watched_words)}</strong> de{" "}
        <span className="mono">{formatInt(p.page_words)}</span> palabras
        {outside > 0 && <span className="text-muted-foreground"> ({formatInt(outside)} fuera)</span>}
      </p>
      {p.selector && (p.selector_matches ? (
        <p>La sección <code className="mono">{p.selector}</code> casa {p.section_nodes} {p.section_nodes === 1 ? "elemento" : "elementos"}.</p>
      ) : (
        <p className="text-amber-300"><code className="mono">{p.selector}</code> no casa nada: se vigilaría la página entera.</p>
      ))}
      {p.ignored.length > 0 && (
        <ul className="text-xs divide-y divide-border">
          {p.ignored.map((i) => (
            <li key={i.selector} className="flex justify-between gap-3 py-1">
              <code className="mono break-all">{i.selector}</code>
              <span className={i.words > 0 ? "text-amber-300 whitespace-nowrap" : "text-muted-foreground whitespace-nowrap"}>
                {i.valid ? `${i.nodes} nodos · ${i.words} palabras` : "selector no válido"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {p.sample && <p className="text-xs text-muted-foreground break-words">«{p.sample}…»</p>}
    </div>
  )
}
