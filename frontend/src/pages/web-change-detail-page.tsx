import { useState } from "react"
import { Link, useLocation, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Check, ChevronLeft, ExternalLink } from "lucide-react"
import { isAxiosError } from "axios"
import { webChangesApi } from "@/lib/api"
import type { WebChangeItem, WebHtmlDiff, WebTextDiff } from "@/lib/types"
import { invalidateWebReview, webKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatInstant } from "@/components/web/uptime-status"
import { KIND_LABEL, detailEntries, formatInt, htmlDiffReason, sentenceDiff } from "@/components/web/change-format"
import { DiffLine, SeverityBadge } from "@/components/web/web-change-ui"
import { WatchDrawer } from "@/components/web/watch-drawer"

/** Detalle de un cambio (`/web/cambios/{id}`, el enlace del digest de Slack). */
export default function WebChangeDetailPage() {
  const { id = "" } = useParams<{ id: string }>()
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const qc = useQueryClient()
  // La lista manda su query string: volver conserva el filtro.
  const back = (useLocation().state as { back?: string } | null)?.back ?? "/web/cambios"
  const [note, setNote] = useState("")
  const [watchOpen, setWatchOpen] = useState(false)

  const detail = useQuery({ queryKey: webKeys.change(id), queryFn: () => webChangesApi.get(id), enabled: Boolean(id) })
  const items = detail.data?.change.items ?? []
  const hasText = items.some((i) => i.kind === "content")
  // El diff de HTML es la respuesta más cara: sólo si hay un cambio de maquetación.
  const hasHtml = items.some((i) => i.kind === "html")
  const textDiff = useQuery({ queryKey: webKeys.diff(id), queryFn: () => webChangesApi.diff(id), enabled: hasText, staleTime: Infinity })
  const htmlDiff = useQuery({ queryKey: webKeys.htmlDiff(id), queryFn: () => webChangesApi.htmlDiff(id), enabled: hasHtml, staleTime: Infinity })

  const ack = useMutation({
    mutationFn: () => webChangesApi.ack(id, note.trim() || null),
    onSuccess: () => {
      toast.success("Marcado como revisado")
      void invalidateWebReview(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  if (detail.isLoading) return <p role="status" className="text-sm text-muted-foreground">Cargando cambio…</p>
  if (detail.isError || !detail.data) {
    const notFound = isAxiosError(detail.error) && detail.error.response?.status === 404
    return (
      <div role="alert" className="space-y-2 text-sm">
        <p>{notFound ? "Este cambio no existe (o se borró con su URL)." : "No se pudo cargar el cambio."}</p>
        <Link to="/web/cambios" className="text-brand hover:underline">Ir a Cambios web</Link>
      </div>
    )
  }

  const { change: c, watch: w } = detail.data
  return (
    <div className="space-y-4">
      <Link to={back} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
        <ChevronLeft className="h-4 w-4" /> Cambios web
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold break-all">{w.label || w.url}</h1>
            <SeverityBadge severity={c.max_severity} />
            {c.acknowledged_at && <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Check className="h-3 w-3" /> Revisado</span>}
          </div>
          <a href={w.url} target="_blank" rel="noopener noreferrer" className="mono text-xs text-muted-foreground hover:text-foreground break-all inline-flex items-center gap-1">
            {w.url} <ExternalLink className="h-3 w-3 shrink-0" />
          </a>
          <p className="text-xs text-muted-foreground">
            {c.client_name && <><Link to={`/clients/${c.client_id}?tab=web`} className="hover:underline">{c.client_name}</Link> · </>}
            Detectado el <span className="mono">{formatInstant(c.detected_at)}</span>
            {w.archived_at && " · la URL está archivada"}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setWatchOpen(true)}>Historial de la URL</Button>
      </header>

      <Card>
        <CardHeader><CardTitle className="text-base">Revisión</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {c.acknowledged_at ? (
            <div role="status" className="text-sm space-y-1">
              <p>
                Revisado{c.acknowledged_by_label ? <> por <strong>{c.acknowledged_by_label}</strong></> : null} el{" "}
                <span className="mono">{formatInstant(c.acknowledged_at)}</span>.
              </p>
              {c.note && <p className="text-muted-foreground whitespace-pre-wrap break-words">«{c.note}»</p>}
            </div>
          ) : canWrite ? (
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); ack.mutate() }}>
              <label className="block text-xs space-y-1">
                <span className="text-muted-foreground">Nota (opcional): qué se ha visto o hecho</span>
                <Textarea className="rounded-[10px]" rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Cambio previsto: nueva ficha de servicio." />
              </label>
              <Button type="submit" size="sm" disabled={ack.isPending}>
                <Check className="h-3.5 w-3.5 mr-1" /> {ack.isPending ? "Guardando…" : "Marcar revisado"}
              </Button>
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">Sin revisar.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Qué ha cambiado</CardTitle></CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Este cambio no tiene detalle guardado.</p>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((item) => <ItemRow key={item.id} item={item} />)}
            </ul>
          )}
        </CardContent>
      </Card>

      {hasText && (
        <Card>
          <CardHeader><CardTitle className="text-base">Texto de la página</CardTitle></CardHeader>
          <CardContent>
            {textDiff.isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando el texto…</p>
              : textDiff.isError || !textDiff.data ? <p role="alert" className="text-sm">No se pudo cargar el texto.</p>
              : <TextDiff diff={textDiff.data} items={items} />}
          </CardContent>
        </Card>
      )}

      {hasHtml && (
        <Card>
          <CardHeader><CardTitle className="text-base">HTML de la página</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              El HTML tal y como se compara: sin comentarios, sin los atributos que cambian en cada carga y ya podado por las reglas de esta URL.
              Es lo que mira el detector, no el código fuente.
            </p>
            {htmlDiff.isLoading ? <p role="status" className="text-sm text-muted-foreground">Calculando el diff…</p>
              : htmlDiff.isError || !htmlDiff.data ? <p role="alert" className="text-sm">No se pudo calcular el diff del HTML.</p>
              : <HtmlDiff diff={htmlDiff.data} />}
          </CardContent>
        </Card>
      )}

      <WatchDrawer watchId={watchOpen ? w.id : null} onClose={() => setWatchOpen(false)} />
    </div>
  )
}

function ItemRow({ item }: { item: WebChangeItem }) {
  const detail = item.detail ?? {}
  const added = detailEntries(detail.added)
  const removed = detailEntries(detail.removed)
  return (
    <li className="py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={item.severity} />
        <span className="text-sm font-medium">{item.rule_label}</span>
        <span className="text-xs text-muted-foreground">{KIND_LABEL[item.kind] ?? item.kind}</span>
      </div>
      {(item.before_val || item.after_val) && (
        <div className="mono text-xs rounded-md overflow-hidden border border-border">
          {item.before_val && <DiffLine op="-">{item.before_val}</DiffLine>}
          {item.after_val && <DiffLine op="+">{item.after_val}</DiffLine>}
        </div>
      )}
      {item.rule_code === "HTML_CHANGED" && (
        // El tamaño es lo que distingue "han tocado una clase" de "han cambiado la plantilla".
        <p className="text-sm text-muted-foreground">
          {typeof detail.added === "number" && typeof detail.removed === "number" ? (
            <>
              <span className="mono text-green-300">+{detail.added}</span>{" "}
              <span className="mono text-red-300">−{detail.removed}</span> líneas
              {typeof detail.after_lines === "number" && <> de <span className="mono">{formatInt(detail.after_lines)}</span></>}.{" "}
            </>
          ) : "No se pudo medir el tamaño del cambio. "}
          Ninguna otra dimensión se movió: ni el texto visible, ni el SEO, ni los enlaces.
        </p>
      )}
      {(removed.length > 0 || added.length > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {removed.length > 0 && <EntryList title={`Quitados (${removed.length})`} op="-" entries={removed} />}
          {added.length > 0 && <EntryList title={`Añadidos (${added.length})`} op="+" entries={added} />}
        </div>
      )}
    </li>
  )
}

function EntryList({ title, op, entries }: { title: string; op: "+" | "-"; entries: string[] }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground mb-1">{title}</p>
      <div className="mono text-xs rounded-md overflow-hidden border border-border">
        {entries.slice(0, 12).map((entry) => <DiffLine key={entry} op={op}><span className="break-all">{entry}</span></DiffLine>)}
      </div>
      {entries.length > 12 && <p className="text-xs text-muted-foreground mt-1">y {entries.length - 12} más</p>}
    </div>
  )
}

/** Hunks guardados en el barrido (`detail.diff` del item de contenido). */
function storedHunks(items: WebChangeItem[]) {
  const diff = items.find((i) => i.kind === "content")?.detail?.diff as
    { hunks?: Array<{ op: string; before: string[]; after: string[] }> } | undefined
  return diff?.hunks ?? []
}

function TextDiff({ diff, items }: { diff: WebTextDiff; items: WebChangeItem[] }) {
  if (diff.before === null || diff.after === null) {
    return <p className="text-sm text-muted-foreground">No se guardó el texto anterior de esta página, así que no hay con qué compararlo.</p>
  }
  const ops = sentenceDiff(diff.before, diff.after)
  if (ops === null) {
    // Demasiado largo para compararlo en el navegador: lo que se guardó al detectarlo.
    const hunks = storedHunks(items)
    return (
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">El texto es demasiado largo para compararlo aquí; estos son los trozos que se guardaron al detectarlo.</p>
        <div className="mono text-xs rounded-md overflow-hidden border border-border">
          {hunks.flatMap((h, idx) => [
            ...h.before.map((s, j) => <DiffLine key={`${idx}-b${j}`} op="-">{s}</DiffLine>),
            ...h.after.map((s, j) => <DiffLine key={`${idx}-a${j}`} op="+">{s}</DiffLine>),
          ])}
        </div>
      </div>
    )
  }
  const removed = ops.filter((o) => o.op === "-").length
  const added = ops.filter((o) => o.op === "+").length
  if (!removed && !added) return <p className="text-sm text-muted-foreground">El texto visible no ha cambiado.</p>
  return (
    <div className="space-y-2">
      <p className="text-xs">
        {removed > 0 && <span className="mono text-red-300 mr-3">−{removed} frases</span>}
        {added > 0 && <span className="mono text-green-300">+{added} frases</span>}
      </p>
      <div className="mono text-xs rounded-md overflow-hidden border border-border overflow-x-auto">
        {ops.map((o, idx) => <DiffLine key={idx} op={o.op}>{o.text}</DiffLine>)}
      </div>
    </div>
  )
}

function HtmlDiff({ diff: d }: { diff: WebHtmlDiff }) {
  if (!d.available) {
    // Un panel en blanco se lee como "está roto": siempre se dice por qué no hay diff.
    return (
      <div role="note" className="text-sm text-muted-foreground space-y-1">
        <p>{htmlDiffReason(d.reason)}</p>
        {d.reason === "demasiado_grande" && d.stats && (
          <p className="mono text-xs">{formatInt(d.stats.before_lines)} → {formatInt(d.stats.after_lines)} líneas</p>
        )}
      </div>
    )
  }
  if (!d.hunks?.length) return <p className="text-sm text-muted-foreground">El HTML guardado de las dos capturas es idéntico.</p>
  return (
    <div className="space-y-3">
      <p className="text-xs">
        <span className="mono text-red-300 mr-3">−{d.stats?.removed ?? 0} líneas</span>
        <span className="mono text-green-300 mr-3">+{d.stats?.added ?? 0} líneas</span>
        <span className="text-muted-foreground">{d.hunks_total === 1 ? "1 zona con cambios" : `${d.hunks_total} zonas con cambios`}</span>
      </p>
      {d.hunks.map((h, idx) => (
        <div key={idx} className="rounded-md border border-border overflow-hidden">
          <p className="mono text-[11px] text-muted-foreground px-3 py-1 border-b border-border">línea {h.before_start} → {h.after_start}</p>
          <div className="mono text-xs overflow-x-auto">
            {h.lines.map((line, j) => <DiffLine key={j} op={line.t} pre>{line.s}</DiffLine>)}
          </div>
          {h.lines_total > h.lines.length && (
            <p className="text-xs text-muted-foreground px-3 py-1 border-t border-border">y {h.lines_total - h.lines.length} líneas más en esta zona</p>
          )}
        </div>
      ))}
      {d.truncated && (
        <p className="text-xs text-muted-foreground">
          Se enseñan las {d.hunks.length} primeras zonas de {d.hunks_total}. Cuando cambian tantos sitios a la vez suele ser un cambio de plantilla.
        </p>
      )}
    </div>
  )
}
