import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Search } from "lucide-react"
import { gscApi } from "@/lib/api"
import { formatDay, gscErrorLabel } from "@/lib/gsc"

/** Conexión de la agencia con Search Console. Sólo para admins. */
export function SearchConsoleSection() {
  const queryClient = useQueryClient()
  const [param] = useState(() => new URLSearchParams(window.location.search).get("gsc"))
  const { data: status, isLoading, isError, refetch } = useQuery({
    queryKey: ["gsc-status"],
    queryFn: gscApi.getStatus,
  })

  useEffect(() => {
    if (!param) return
    if (param === "connected") toast.success("Cuenta de Google conectada. Sus propiedades nuevas traen 16 meses de datos en la primera importación.")
    else if (param === "cancelled") toast.info("Conexión con Search Console cancelada")
    else toast.error("No se pudo conectar Search Console")
    window.history.replaceState({}, "", "/settings#search-console")
    void queryClient.invalidateQueries({ queryKey: ["gsc-status"] })
  }, [param, queryClient])

  const connectMut = useMutation({
    mutationFn: async () => {
      const { url } = await gscApi.getAuthUrl()
      window.location.href = url
    },
    onError: () => toast.error("No se pudo iniciar la conexión con Google"),
  })
  const disconnectMut = useMutation({
    mutationFn: (connectionId: number) => gscApi.disconnect(connectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["gsc-status"] })
      toast.success("Cuenta desconectada. Los datos importados se conservan.")
    },
    onError: () => toast.error("Error al desconectar"),
  })
  const syncMut = useMutation({
    mutationFn: gscApi.sync,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["gsc-status"] })
      if (data.status === "reconnect_required") toast.error("Google ha rechazado alguna cuenta. Reconéctala abajo.")
      else if (data.failed) toast.warning(`Importadas ${data.synced} propiedades; ${data.failed} con errores.`)
      else toast.success(`Importadas ${data.synced} propiedades`)
    },
    onError: () => toast.error("No se pudo importar ahora"),
  })

  const connections = status?.connections ?? []
  const anyConnected = connections.some((c) => c.status === "connected")

  return (
    <div id="search-console" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
      <div className="flex items-center gap-2 mb-4">
        <Search className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold text-foreground">Search Console</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Conecta las cuentas de Google con acceso a las propiedades de los clientes. Cada propiedad se importa con la
        cuenta que la ve; cada día se guardan sus datos (más allá de los 16 meses de Google) y los resúmenes mensuales
        incluyen su evolución.
      </p>

      {isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando…</p> : isError || !status ? (
        <p role="alert" className="text-sm">No se pudo consultar Search Console. <button className="underline" onClick={() => refetch()}>Reintentar</button></p>
      ) : !status.configured ? (
        <p className="text-sm text-muted-foreground">Falta configurar Google OAuth en el servidor (GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET).</p>
      ) : (
        <div className="space-y-4">
          {connections.length > 0 && (
            <ul className="divide-y divide-border rounded-xl border border-border">
              {connections.map((connection) => (
                <li key={connection.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                  <div className="flex items-center gap-2 text-sm">
                    <div className={`h-2 w-2 rounded-full ${connection.status === "connected" ? "bg-green-500" : "bg-amber-500"}`} />
                    <span>
                      <span className="font-medium">{connection.google_email ?? "Cuenta sin email"}</span>
                      <span className="text-muted-foreground">
                        {connection.status === "connected" ? " · conectada" : " · necesita reconectar"}
                        {connection.connected_by && ` · por ${connection.connected_by}`}
                      </span>
                    </span>
                  </div>
                  <div className="flex gap-2">
                    {connection.status !== "connected" && (
                      <button onClick={() => connectMut.mutate()} disabled={connectMut.isPending}
                        className="px-3 py-1.5 text-xs bg-brand text-black font-semibold rounded-lg hover:bg-brand/90 disabled:opacity-50">
                        Reconectar
                      </button>
                    )}
                    <button onClick={() => disconnectMut.mutate(connection.id)} disabled={disconnectMut.isPending}
                      aria-label={`Desconectar ${connection.google_email ?? "cuenta"}`}
                      className="px-3 py-1.5 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50">
                      Desconectar
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => connectMut.mutate()} disabled={connectMut.isPending}
              className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50">
              {connectMut.isPending ? "Redirigiendo…" : connections.length ? "Añadir cuenta de Google" : "Conectar Search Console"}
            </button>
            {anyConnected && (
              <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending}
                className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50">
                {syncMut.isPending ? "Importando…" : "Importar ahora"}
              </button>
            )}
          </div>

          {status.sites.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún cliente activo tiene propiedad de Search Console. Se indica en la ficha de cada cliente.</p>
          ) : (
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
                  {status.sites.map((site) => {
                    const error = gscErrorLabel(site.error_code)
                    return (
                      <tr key={site.site_url} className="align-top">
                        <td className="py-2 pr-3 font-mono text-xs break-all">{site.site_url}</td>
                        <td className="py-2 pr-3">{site.clients.map((c) => c.name).join(", ")}</td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground break-all">{site.google_email ?? "—"}</td>
                        <td className="py-2">
                          {site.last_data_date ? formatDay(site.last_data_date) : <span className="text-muted-foreground">Pendiente</span>}
                          {error && <p className="text-xs text-amber-600 mt-1">{error}</p>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
