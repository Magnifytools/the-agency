import { useState } from "react"
import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { clientShareLinkApi, type PublicDigest, type PublicTrafficMonth } from "@/lib/client-share-link-api"
import { formatCompact } from "@/lib/format"
import { parseApiInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
const number = new Intl.NumberFormat("es-ES")

function monthLabel(month: string) {
  const [year, m] = month.split("-")
  return `${MONTHS[Number(m) - 1]} ${year.slice(2)}`
}

function deliveredOn(value: string) {
  return parseApiInstant(value).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Madrid" })
}

function statusOf(error: unknown) {
  return (error as { response?: { status?: number } } | null)?.response?.status
}

/**
 * Página pública del cliente (sin login, fuera del shell de la app): sus
 * resúmenes ya entregados y sus clics de Google por mes. Sólo lectura.
 */
export default function PublicClientPage() {
  const { token = "" } = useParams()
  const { data, error, isLoading } = useQuery({
    queryKey: ["public-client", token],
    queryFn: () => clientShareLinkApi.publicView(token),
    retry: false,
    staleTime: 5 * 60_000,
  })

  return (
    <div className="min-h-screen bg-background text-foreground">
      <title>{data ? `${data.client_name} · Magnify` : "Magnify"}</title>
      <meta name="robots" content="noindex, nofollow, noarchive" />
      <meta name="referrer" content="no-referrer" />
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-4">
          <a href="https://www.magnify.ing" target="_blank" rel="noreferrer" className="text-lg font-bold tracking-tight">
            Magnify<span className="text-brand">.</span>
          </a>
          {data && <span className="truncate text-sm text-muted-foreground">{data.client_name}</span>}
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-8 px-4 py-8">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : error ? (
          <div role="alert" className="rounded-lg border border-border bg-card p-6">
            <h1 className="text-lg font-semibold">
              {statusOf(error) === 429 ? "Demasiadas visitas seguidas" : "Este enlace no está disponible"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {statusOf(error) === 429
                ? "Espera un minuto y vuelve a cargar la página."
                : "Puede que lo hayamos renovado. Pide el enlace actual a tu contacto en Magnify."}
            </p>
          </div>
        ) : data ? (
          <>
            <div>
              <h1 className="text-2xl font-bold">{data.client_name}</h1>
              <p className="mt-1 text-sm text-muted-foreground">Tus resúmenes y la evolución de tu tráfico en Google.</p>
            </div>
            <TrafficSection traffic={data.traffic} />
            <DigestsSection digests={data.digests} />
          </>
        ) : null}
      </main>
    </div>
  )
}

function TrafficSection({ traffic }: { traffic: { months: PublicTrafficMonth[]; complete_through: string } | null }) {
  return (
    <section aria-labelledby="traffic-title" className="rounded-lg border border-border bg-card p-4 sm:p-6">
      <h2 id="traffic-title" className="text-base font-semibold">Clics desde Google, por mes</h2>
      {!traffic ? (
        <p className="mt-2 text-sm text-muted-foreground">Todavía no hay datos de Search Console para mostrar.</p>
      ) : (
        <>
          <p className="mt-1 text-xs text-muted-foreground">Meses completos. Fuente: Google Search Console.</p>
          <div className="mt-4 h-64" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={traffic.months.map((m) => ({ ...m, label: monthLabel(m.month) }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="label" fontSize={11} tick={{ fill: "#A3A3A3" }} interval="preserveStartEnd" />
                <YAxis fontSize={11} tick={{ fill: "#A3A3A3" }} tickFormatter={formatCompact} width={44} />
                <Tooltip
                  cursor={{ fill: "rgba(255,214,0,0.08)" }}
                  formatter={(value) => [number.format(Number(value)), "Clics"]}
                  contentStyle={{ backgroundColor: "#1C1C1C", border: "1px solid #2E2E2E", color: "#FFFFFF", fontSize: 12, borderRadius: 8 }}
                  labelStyle={{ color: "#FFD600" }}
                />
                <Bar dataKey="clicks" fill="#FFD600" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Clics, impresiones y posición media por mes</caption>
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="py-1 pr-4 font-medium">Mes</th>
                  <th scope="col" className="py-1 pr-4 text-right font-medium">Clics</th>
                  <th scope="col" className="py-1 pr-4 text-right font-medium">Impresiones</th>
                  <th scope="col" className="py-1 text-right font-medium">Posición media</th>
                </tr>
              </thead>
              <tbody>
                {[...traffic.months].reverse().map((m) => (
                  <tr key={m.month} className="border-t border-border">
                    <th scope="row" className="py-1.5 pr-4 text-left font-normal">{monthLabel(m.month)}</th>
                    <td className="mono py-1.5 pr-4 text-right">{number.format(m.clicks)}</td>
                    <td className="mono py-1.5 pr-4 text-right">{number.format(m.impressions)}</td>
                    <td className="mono py-1.5 text-right">{m.position == null ? "—" : m.position.toLocaleString("es-ES")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function DigestsSection({ digests }: { digests: PublicDigest[] }) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  const keyOf = (d: PublicDigest) => `${d.period_start}:${d.period_end}`
  const open = digests.find((d) => keyOf(d) === openKey) ?? digests[0]

  return (
    <section aria-labelledby="digests-title" className="rounded-lg border border-border bg-card p-4 sm:p-6">
      <h2 id="digests-title" className="text-base font-semibold">Resúmenes</h2>
      {digests.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">Aún no hay resúmenes entregados.</p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[14rem_1fr]">
          <ul className="flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible">
            {digests.map((d) => (
              <li key={keyOf(d)} className="shrink-0">
                <button
                  type="button"
                  aria-pressed={open === d}
                  onClick={() => setOpenKey(keyOf(d))}
                  className={cn(
                    "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors duration-150",
                    open === d ? "border-brand bg-brand/10" : "border-border hover:bg-muted",
                  )}
                >
                  <span className="block font-medium">{d.period_label}</span>
                  {d.delivered_at && <span className="block text-xs text-muted-foreground">Enviado el {deliveredOn(d.delivered_at)}</span>}
                </button>
              </li>
            ))}
          </ul>
          {open && (
            <iframe
              key={keyOf(open)}
              title={`Resumen ${open.period_label}`}
              srcDoc={open.html}
              // Sin scripts ni mismo origen: el HTML del resumen no puede tocar la página.
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              className="h-[75vh] w-full rounded-md border border-border bg-white"
            />
          )}
        </div>
      )}
    </section>
  )
}
