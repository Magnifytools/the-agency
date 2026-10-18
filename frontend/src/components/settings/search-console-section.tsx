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
    if (param === "connected") toast.success("Search Console conectado. La primera importación trae 16 meses de datos.")
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
    mutationFn: gscApi.disconnect,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["gsc-status"] })
      toast.success("Search Console desconectado. Los datos importados se conservan.")
    },
    onError: () => toast.error("Error al desconectar"),
  })
  const syncMut = useMutation({
    mutationFn: gscApi.sync,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["gsc-status"] })
      if (data.status === "reconnect_required") toast.error("Google ha rechazado la autorización. Reconecta Search Console.")
      else if (data.failed) toast.warning(`Importadas ${data.synced} propiedades; ${data.failed} con errores.`)
      else toast.success(`Importadas ${data.synced} propiedades`)
    },
    onError: () => toast.error("No se pudo importar ahora"),
  })

  const connection = status?.connection

  return (
    <div id="search-console" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
      <div className="flex items-center gap-2 mb-4">
        <Search className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold text-foreground">Search Console</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Conecta una cuenta de Google con acceso a las propiedades de los clientes. Cada día se guardan sus datos
        (más allá de los 16 meses de Google) y los resúmenes mensuales incluyen su evolución.
      </p>

      {isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando…</p> : isError || !status ? (
        <p role="alert" className="text-sm">No se pudo consultar Search Console. <button className="underline" onClick={() => refetch()}>Reintentar</button></p>
      ) : !status.configured ? (
        <p className="text-sm text-muted-foreground">Falta configurar Google OAuth en el servidor (GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET).</p>
      ) : (
        <div className="space-y-4">
          {connection ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm">
                <div className={`h-2 w-2 rounded-full ${connection.status === "connected" ? "bg-green-500" : "bg-amber-500"}`} />
                <span>
                  {connection.status === "connected" ? "Conectado" : "Necesita reconectar"}
                  {connection.google_email && <> con <span className="font-medium">{connection.google_email}</span></>}
                  {connection.connected_by && <span className="text-muted-foreground"> · por {connection.connected_by}</span>}
                </span>
              </div>
              <div className="flex gap-2">
                {connection.status === "connected" ? (
                  <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending}
                    className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50">
                    {syncMut.isPending ? "Importando…" : "Importar ahora"}
                  </button>
                ) : (
                  <button onClick={() => connectMut.mutate()} disabled={connectMut.isPending}
                    className="px-3 py-1.5 text-xs bg-brand text-black font-semibold rounded-lg hover:bg-brand/90 disabled:opacity-50">
                    {connectMut.isPending ? "Redirigiendo…" : "Reconectar"}
                  </button>
                )}
                <button onClick={() => disconnectMut.mutate()} disabled={disconnectMut.isPending}
                  className="px-3 py-1.5 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50">
                  Desconectar
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => connectMut.mutate()} disabled={connectMut.isPending}
              className="px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors disabled:opacity-50">
              {connectMut.isPending ? "Redirigiendo…" : "Conectar Search Console"}
            </button>
          )}

          {status.sites.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún cliente activo tiene propiedad de Search Console. Se indica en la ficha de cada cliente.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Propiedad</th>
                    <th className="py-2 pr-3 font-medium">Clientes</th>
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
