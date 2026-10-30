import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { BarChart3 } from "lucide-react"
import { ga4Api } from "@/lib/api"
import { formatDay } from "@/lib/gsc"
import { ga4ErrorLabel } from "@/lib/ga4"

/** Importación de GA4 con las mismas cuentas de Google que Search Console. Sólo admins. */
export function Ga4Section() {
  const queryClient = useQueryClient()
  const { data: status, isLoading, isError, refetch } = useQuery({ queryKey: ["ga4-status"], queryFn: ga4Api.getStatus })
  const syncMut = useMutation({
    mutationFn: ga4Api.sync,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["ga4-status"] })
      if (data.status === "not_connected") toast.error("Conecta antes una cuenta de Google en Search Console.")
      else if (data.failed) toast.warning(`Importadas ${data.synced} propiedades; ${data.failed} con errores.`)
      else toast.success(`Importadas ${data.synced} propiedades`)
    },
    onError: () => toast.error("No se pudo importar ahora"),
  })

  return (
    <div id="ga4" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold text-foreground">Google Analytics 4</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Visitas, conversiones (eventos clave) y tráfico desde asistentes de IA de cada cliente. Usa las cuentas de
        Google conectadas arriba; una cuenta conectada antes de existir esta sección tiene que reconectarse para dar
        permiso de Analytics. La propiedad se indica en los ajustes de cada cliente.
      </p>
      {isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando…</p> : isError || !status ? (
        <p role="alert" className="text-sm">No se pudo consultar GA4. <button className="underline" onClick={() => refetch()}>Reintentar</button></p>
      ) : status.properties.length === 0 ? (
        <p className="text-sm text-muted-foreground">Ningún cliente activo tiene propiedad de GA4.</p>
      ) : (
        <div className="space-y-3">
          <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending}
            className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50">
            {syncMut.isPending ? "Importando…" : "Importar ahora"}
          </button>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Propiedad</th>
                  <th className="py-2 pr-3 font-medium">Clientes</th>
                  <th className="py-2 pr-3 font-medium">Cuenta</th>
                  <th className="py-2 font-medium">Datos hasta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {status.properties.map((p) => {
                  const error = ga4ErrorLabel(p.error_code)
                  return (
                    <tr key={p.property_id} className="align-top">
                      <td className="py-2 pr-3 font-mono text-xs">{p.property_id}</td>
                      <td className="py-2 pr-3">{p.clients.map((c) => c.name).join(", ")}</td>
                      <td className="py-2 pr-3 text-xs text-muted-foreground break-all">{p.google_email ?? "—"}</td>
                      <td className="py-2">
                        {p.last_data_date ? formatDay(p.last_data_date) : <span className="text-muted-foreground">Pendiente</span>}
                        {error && <p className="text-xs text-amber-600 mt-1">{error}</p>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
