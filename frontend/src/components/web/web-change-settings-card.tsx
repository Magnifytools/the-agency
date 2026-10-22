import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CalendarDays, X } from "lucide-react"
import { webWatchesApi } from "@/lib/api"
import type { WebChangeSettings, WebSeverity } from "@/lib/types"
import { webKeys } from "@/lib/query-keys"
import { formatCivilDate } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Segmented } from "@/components/web/web-change-ui"

const WEEKDAYS = [
  { day: 1, short: "L", name: "lunes" },
  { day: 2, short: "M", name: "martes" },
  { day: 3, short: "X", name: "miércoles" },
  { day: 4, short: "J", name: "jueves" },
  { day: 5, short: "V", name: "viernes" },
  { day: 6, short: "S", name: "sábado" },
  { day: 7, short: "D", name: "domingo" },
]

const DIGEST_OPTIONS: Array<{ id: WebSeverity; label: string }> = [
  { id: "critical", label: "Sólo críticos" },
  { id: "warning", label: "Críticos y avisos" },
  { id: "info", label: "Todo" },
]

const SLACK_TEXT: Record<WebChangeSettings["slack"], { text: string; warn: boolean }> = {
  ready: { text: "Los avisos de cambios llegan al Slack del cliente.", warn: false },
  disabled: { text: "Slack no está activo para este cliente: los cambios se registran aquí, pero no llega ningún aviso.", warn: true },
  revoked: { text: "Slack revocó el webhook del cliente: hay que generar uno nuevo (volver a pegar el mismo no lo arregla).", warn: true },
}

const lines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean)
const numberOrNull = (text: string) => (text.trim() === "" ? null : Number(text))

/**
 * Calendario del barrido automático y reglas de captura por defecto del
 * cliente (sólo con escritura en `web`). Cada valor vacío vuelve a NULL = el
 * default del código: corregir un default en código corrige a todos los que no
 * lo personalizaron.
 */
export function WebChangeSettingsCard({ clientId }: { clientId: number }) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: webKeys.settings(clientId),
    queryFn: () => webWatchesApi.settings(clientId),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="h-4 w-4" /> Calendario y captura</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p role="status" className="text-sm text-muted-foreground">Cargando ajustes…</p>
        ) : isError || !data ? (
          <div role="alert" className="flex items-center justify-between gap-3 text-sm">
            <span>No se pudieron cargar los ajustes.</span>
            <Button size="sm" variant="outline" onClick={() => refetch()}>Reintentar</Button>
          </div>
        ) : (
          // key: al guardar, el formulario arranca de lo que devolvió el servidor.
          <SettingsForm key={data.updated_at ?? "nuevo"} clientId={clientId} settings={data} />
        )}
      </CardContent>
    </Card>
  )
}

function SettingsForm({ clientId, settings }: { clientId: number; settings: WebChangeSettings }) {
  const qc = useQueryClient()
  const { stored, effective, code_defaults: defaults } = settings
  const [weekdays, setWeekdays] = useState<number[]>(effective.sweep_weekdays)
  const [skipDates, setSkipDates] = useState<string[]>(effective.sweep_skip_dates)
  const [newDate, setNewDate] = useState("")
  const [summaryToSlack, setSummaryToSlack] = useState(Boolean(effective.sweep_summary_to_slack))
  const [digest, setDigest] = useState<WebSeverity | null>(stored.digest_min_severity)
  const [selector, setSelector] = useState(stored.default_content_selector ?? "")
  const [ignoreSelectors, setIgnoreSelectors] = useState((stored.default_ignore_selectors ?? []).join("\n"))
  const [ignoreRegexes, setIgnoreRegexes] = useState((stored.default_ignore_regexes ?? []).join("\n"))
  const [concurrency, setConcurrency] = useState(stored.max_concurrency?.toString() ?? "")
  const [timeout, setTimeoutS] = useState(stored.request_timeout_s?.toString() ?? "")
  const [delay, setDelay] = useState(stored.crawl_delay_ms?.toString() ?? "")

  const onSaved = (fresh: WebChangeSettings) => {
    qc.setQueryData(webKeys.settings(clientId), fresh)
    toast.success("Ajustes guardados")
  }
  const saveCalendar = useMutation({
    mutationFn: () => webWatchesApi.saveCalendar(clientId, {
      sweep_weekdays: weekdays, sweep_skip_dates: skipDates, sweep_summary_to_slack: summaryToSlack,
    }),
    onSuccess: onSaved,
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const saveCapture = useMutation({
    mutationFn: () => webWatchesApi.saveCapture(clientId, {
      default_content_selector: selector.trim() || null,
      // Vacío = los de por defecto (null), no "ninguno".
      default_ignore_selectors: lines(ignoreSelectors).length ? lines(ignoreSelectors) : null,
      default_ignore_regexes: lines(ignoreRegexes).length ? lines(ignoreRegexes) : null,
      max_concurrency: numberOrNull(concurrency),
      request_timeout_s: numberOrNull(timeout),
      crawl_delay_ms: numberOrNull(delay),
      digest_min_severity: digest,
    }),
    onSuccess: onSaved,
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const year = new Date().getFullYear()
  const addHolidays = useMutation({
    mutationFn: () => webWatchesApi.holidays(year),
    onSuccess: (r) => {
      setSkipDates((prev) => [...new Set([...prev, ...r.holidays])].sort())
      toast.success(`${r.holidays.length} festivos nacionales de ${r.year} añadidos. Guarda para aplicarlos.`)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const slack = SLACK_TEXT[settings.slack]
  const toggleDay = (day: number) =>
    setWeekdays((prev) => (prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort()))

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <form
        className="space-y-3"
        aria-label="Calendario del barrido"
        onSubmit={(e) => { e.preventDefault(); saveCalendar.mutate() }}
      >
        <p className="text-xs text-muted-foreground">
          El barrido automático empieza a partir de las <span className="mono">{settings.sweep_local_time}</span> (hora de Madrid) los días marcados.
          «Comprobar todas» a mano no mira el calendario.
          {!settings.enabled && <span className="text-amber-600"> Ahora mismo el barrido está apagado.</span>}
        </p>
        <fieldset>
          <legend className="text-xs text-muted-foreground mb-1">Días</legend>
          <div className="flex flex-wrap gap-1">
            {WEEKDAYS.map(({ day, short, name }) => {
              const on = weekdays.includes(day)
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={on}
                  aria-label={name}
                  title={name}
                  onClick={() => toggleDay(day)}
                  className={`h-8 w-8 rounded-[8px] border text-xs font-semibold transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${on ? "border-brand bg-brand/15 text-brand" : "border-border text-muted-foreground hover:text-foreground"}`}
                >
                  {short}
                </button>
              )
            })}
          </div>
        </fieldset>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Días sin barrido (festivos)</p>
          <ul className="flex flex-wrap gap-1" aria-label="Días sin barrido">
            {skipDates.length === 0 && <li className="text-xs text-muted-foreground">Ninguno.</li>}
            {skipDates.map((d) => (
              <li key={d} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs">
                <span className="mono">{formatCivilDate(d, { day: "numeric", month: "short", year: "numeric" })}</span>
                <button type="button" aria-label={`Quitar ${d}`} onClick={() => setSkipDates((prev) => prev.filter((x) => x !== d))}
                  className="text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <Input type="date" aria-label="Fecha sin barrido" className="w-auto" value={newDate} onChange={(e) => setNewDate(e.target.value)} />
            <Button type="button" size="sm" variant="outline" disabled={!newDate}
              onClick={() => { setSkipDates((prev) => [...new Set([...prev, newDate])].sort()); setNewDate("") }}>
              Añadir fecha
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={addHolidays.isPending} onClick={() => addHolidays.mutate()}>
              Festivos nacionales {year}
            </Button>
          </div>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1 accent-[#FFD600]" checked={summaryToSlack} onChange={(e) => setSummaryToSlack(e.target.checked)} />
          <span>
            Mandar el resumen del barrido completo a Slack
            <span className="block text-xs text-muted-foreground">«He mirado 6, ninguna cambió»: convierte el silencio en una señal fiable.</span>
          </span>
        </label>
        <Button type="submit" size="sm" disabled={saveCalendar.isPending || weekdays.length === 0}>
          {saveCalendar.isPending ? "Guardando…" : "Guardar calendario"}
        </Button>
      </form>

      <form
        className="space-y-3"
        aria-label="Captura por defecto"
        onSubmit={(e) => { e.preventDefault(); saveCapture.mutate() }}
      >
        <p className={`text-xs ${slack.warn ? "text-amber-600" : "text-muted-foreground"}`}>{slack.text}</p>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Qué se avisa en Slack</p>
          <Segmented<WebSeverity>
            label="Severidad mínima del aviso a Slack"
            value={digest ?? defaults.digest_min_severity}
            onChange={setDigest}
            options={DIGEST_OPTIONS.map((o) => ({ ...o, label: o.id === defaults.digest_min_severity && digest === null ? `${o.label} (por defecto)` : o.label }))}
          />
        </div>
        <label className="block text-xs space-y-1">
          <span className="text-muted-foreground">Sección vigilada por defecto (CSS; vacío = main, article o body)</span>
          <Input className="mono" value={selector} onChange={(e) => setSelector(e.target.value)} placeholder="main .contenido" />
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-xs space-y-1">
            <span className="text-muted-foreground">Ignorar selectores (vacío = los de por defecto)</span>
            <Textarea className="mono rounded-[10px]" rows={4} value={ignoreSelectors} onChange={(e) => setIgnoreSelectors(e.target.value)}
              placeholder={defaults.default_ignore_selectors.join("\n")} />
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-muted-foreground">Ignorar patrones de texto (vacío = los de por defecto)</span>
            <Textarea className="mono rounded-[10px]" rows={4} value={ignoreRegexes} onChange={(e) => setIgnoreRegexes(e.target.value)}
              placeholder={defaults.default_ignore_regexes.join("\n")} />
          </label>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Un selector de poda mal elegido no hace ruido, hace silencio: mide antes con «Probar esta configuración» en la ficha de una URL.
        </p>
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Ritmo de las peticiones</summary>
          <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
            <label className="space-y-1"><span className="text-muted-foreground">A la vez (1-12)</span>
              <Input type="number" min={1} max={12} className="mono" value={concurrency} onChange={(e) => setConcurrency(e.target.value)} placeholder={String(defaults.max_concurrency)} /></label>
            <label className="space-y-1"><span className="text-muted-foreground">Timeout (5-60 s)</span>
              <Input type="number" min={5} max={60} className="mono" value={timeout} onChange={(e) => setTimeoutS(e.target.value)} placeholder={String(defaults.request_timeout_s)} /></label>
            <label className="space-y-1"><span className="text-muted-foreground">Pausa (ms)</span>
              <Input type="number" min={0} max={10000} className="mono" value={delay} onChange={(e) => setDelay(e.target.value)} placeholder={String(defaults.crawl_delay_ms)} /></label>
          </div>
        </details>
        <Button type="submit" size="sm" disabled={saveCapture.isPending}>
          {saveCapture.isPending ? "Guardando…" : "Guardar captura"}
        </Button>
      </form>
    </div>
  )
}
