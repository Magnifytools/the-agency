import { useQuery } from "@tanstack/react-query"
import { Download, Puzzle } from "lucide-react"
import { extensionApi } from "@/lib/api"
import { formatCivilDate } from "@/lib/dates"

const LONG_DATE: Intl.DateTimeFormatOptions = { day: "numeric", month: "long", year: "numeric" }

/** Descarga de la extensión de Chrome: siempre la versión desplegada ahora mismo. */
export function ExtensionSection() {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["extension-info"], queryFn: extensionApi.info })

  return (
    <div id="extension" className="bg-card border border-border rounded-2xl p-6 scroll-mt-8">
      <div className="flex items-center gap-2 mb-4">
        <Puzzle className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold text-foreground">Extensión de Chrome</h2>
      </div>
      {isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando…</p> : isError || !data ? (
        <p role="alert" className="text-sm">No se pudo consultar la extensión. <button className="underline" onClick={() => refetch()}>Reintentar</button></p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <a href={data.download_url} download={data.filename}
              className="inline-flex items-center gap-2 px-4 py-2 bg-brand text-black text-sm font-semibold rounded-xl hover:bg-brand/90 transition-colors">
              <Download className="h-4 w-4" aria-hidden="true" /> Descargar extensión
            </a>
            <span className="text-sm text-muted-foreground">
              Versión <span className="mono">{data.version}</span>
              {data.released_on && <> · actualizada el {formatCivilDate(data.released_on, LONG_DATE)}</>}
            </span>
          </div>
          {data.releases.length > 0 && (
            <div className="text-sm">
              <h3 className="font-medium text-foreground mb-1">Novedades</h3>
              <ul className="space-y-2">
                {data.releases.map((release) => (
                  <li key={release.version}>
                    <p className="text-xs text-muted-foreground">
                      <span className="mono">{release.version}</span> · {formatCivilDate(release.date, LONG_DATE)}
                      {release.version === data.version && " · la que se descarga ahora"}
                    </p>
                    <ul className="list-disc pl-5 text-muted-foreground">
                      {release.changes.map((change) => <li key={change}>{change}</li>)}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div>
              <h3 className="font-medium text-foreground mb-1">Instalar</h3>
              <ol className="list-decimal pl-5 space-y-1 text-muted-foreground">
                <li>Descomprime el zip: queda una carpeta <span className="mono">the-agency</span>.</li>
                <li>Abre <span className="mono">chrome://extensions</span> y activa el modo desarrollador.</li>
                <li>Pulsa «Cargar descomprimida» y elige esa carpeta.</li>
              </ol>
            </div>
            <div>
              <h3 className="font-medium text-foreground mb-1">Actualizar</h3>
              <ol className="list-decimal pl-5 space-y-1 text-muted-foreground">
                <li>Descomprime el zip nuevo.</li>
                <li>Sustituye el contenido de la carpeta que ya tenías cargada.</li>
                <li>En <span className="mono">chrome://extensions</span>, pulsa recargar (↻) en The Agency.</li>
              </ol>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
