import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { clientsApi, engineApi, ga4Api, gscApi, vigilApi } from "@/lib/api"
import { ga4ErrorLabel, parseLeadEvents } from "@/lib/ga4"
import { formatDay, gscErrorLabel } from "@/lib/gsc"
import type { Client } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { BarChart3, Search, Save, Globe, Radar, Target } from "lucide-react"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { invalidateClientChange } from "@/lib/query-keys"
import { ClientShareLinkCard } from "@/components/clients/client-share-link-card"
import { ClientSlackCard } from "@/components/web/client-slack-card"
import { BrandTermsEditor } from "@/components/clients/seo-control/brand-terms-editor"
import { SeoPageGroupsEditor } from "@/components/clients/seo-control/seo-page-groups-editor"

interface Props {
  client: Client
}

export function ClientSettingsTab({ client }: Props) {
  const { isAdmin, hasPermission } = useAuth()
  const canWriteClients = hasPermission("clients", true)
  const qc = useQueryClient()
  const [ga4, setGa4] = useState(client.ga4_property_id ?? "")
  const [gsc, setGsc] = useState(client.gsc_url ?? "")
  const [engineProjectId, setEngineProjectId] = useState(
    client.engine_project_id?.toString() ?? ""
  )
  const [vigilSlug, setVigilSlug] = useState(client.vigil_slug ?? "")
  const savedBrandTerms = client.brand_terms ?? []
  const [brandTerms, setBrandTerms] = useState<string[]>(savedBrandTerms)
  const brandTermsDirty = brandTerms.join("\n") !== savedBrandTerms.join("\n")
  const savedLeadEvents = (client.ga4_lead_events ?? ["generate_lead"]).join(", ")
  const [leadEvents, setLeadEvents] = useState(savedLeadEvents)
  const leadEventsDirty = leadEvents.trim() !== savedLeadEvents

  const isDirty =
    ga4 !== (client.ga4_property_id ?? "") ||
    gsc !== (client.gsc_url ?? "") ||
    engineProjectId !== (client.engine_project_id?.toString() ?? "") ||
    vigilSlug !== (client.vigil_slug ?? "") ||
    brandTermsDirty ||
    leadEventsDirty

  const { data: engineProjects = [] } = useQuery({
    queryKey: ["engine-projects"],
    queryFn: () => engineApi.listProjects(),
    staleTime: 5 * 60_000,
    retry: false,
    enabled: isAdmin,
  })

  const updateMut = useMutation({
    mutationFn: () =>
      clientsApi.update(client.id, {
        ga4_property_id: ga4.trim() || null,
        gsc_url: gsc.trim() || null,
        vigil_slug: vigilSlug.trim() || null,
        // Sólo si cambian: así guardar otro campo no pisa términos editados por otra persona.
        ...(brandTermsDirty ? { brand_terms: brandTerms } : {}),
        // Igual: sólo si cambian. El servidor valida los nombres.
        ...(leadEventsDirty ? { ga4_lead_events: parseLeadEvents(leadEvents) } : {}),
        ...(isAdmin ? { engine_project_id: engineProjectId.trim() ? parseInt(engineProjectId) : null } : {}),
      }),
    onSuccess: () => {
      void invalidateClientChange(qc, [client.id])
      toast.success("Ajustes guardados")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const { data: ga4Status } = useQuery({ queryKey: ["ga4-status"], queryFn: ga4Api.getStatus, staleTime: 60_000 })
  const savedGa4 = client.ga4_property_id?.trim().replace(/^properties\//, "")
  const ga4State = ga4Status?.properties.find((p) => p.property_id === savedGa4)
  const { data: vigil } = useQuery({ queryKey: ["vigil-clients"], queryFn: vigilApi.clients, staleTime: 5 * 60_000 })
  const vigilSaved = vigil?.clients.find((c) => c.slug === client.vigil_slug)

  // Estado de importación de la propiedad GUARDADA (no la que se está escribiendo).
  const { data: gscStatus } = useQuery({ queryKey: ["gsc-status"], queryFn: gscApi.getStatus, staleTime: 60_000 })
  const gscConnected = !!gscStatus?.connections.some((c) => c.status === "connected")
  const { data: gscSites } = useQuery({
    queryKey: ["gsc-sites"],
    queryFn: gscApi.listSites,
    enabled: isAdmin && canWriteClients && gscConnected,
    staleTime: 5 * 60_000,
  })
  const savedSite = normalizeSiteUrl(client.gsc_url)
  const siteState = gscStatus?.sites.find((s) => s.site_url === savedSite)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canWriteClients) return
    updateMut.mutate()
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" /> Analytics y Search Console
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {!canWriteClients && <p role="status" className="rounded-md bg-muted p-3 text-sm">Puedes consultar estos ajustes, pero no editarlos.</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="flex items-center gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
                  GA4 Property ID
                </Label>
                <Input
                  value={ga4}
                  onChange={(e) => setGa4(e.target.value)}
                  placeholder="123456789"
                  className="mt-1"
                  disabled={!canWriteClients}
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  ID numérico de la propiedad de Google Analytics 4
                </p>
                {savedGa4 && ga4Status && (
                  <p className="text-[11px] mt-1">
                    {ga4State?.last_data_date ? (
                      <span className="text-muted-foreground">Datos importados hasta el {formatDay(ga4State.last_data_date)}.</span>
                    ) : (
                      <span className="text-muted-foreground">Se importará en la próxima pasada diaria.</span>
                    )}
                    {ga4ErrorLabel(ga4State?.error_code) && <span className="block text-amber-600">{ga4ErrorLabel(ga4State?.error_code)}</span>}
                  </p>
                )}
                <Label htmlFor="ga4-lead-events" className="mt-3 flex items-center gap-1.5">
                  <Target className="h-3.5 w-3.5 text-muted-foreground" />
                  Eventos que cuentan como lead
                </Label>
                <Input
                  id="ga4-lead-events"
                  value={leadEvents}
                  onChange={(e) => setLeadEvents(e.target.value)}
                  placeholder="generate_lead"
                  className="mt-1"
                  disabled={!canWriteClients}
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  Nombres de evento de GA4 separados por comas. Termina en * para contar todos los que empiezan
                  así (generate_lead_*). Si cambian, los leads se vuelven a importar.
                </p>
              </div>
              <div>
                <Label className="flex items-center gap-1.5">
                  <Search className="h-3.5 w-3.5 text-muted-foreground" />
                  Google Search Console URL
                </Label>
                <Input
                  value={gsc}
                  onChange={(e) => setGsc(e.target.value)}
                  placeholder="sc-domain:ejemplo.com o https://ejemplo.com/"
                  className="mt-1"
                  disabled={!canWriteClients}
                  list="gsc-sites"
                />
                {gscSites && (
                  <datalist id="gsc-sites">
                    {gscSites.sites.map((site) => <option key={site.site_url} value={site.site_url} />)}
                  </datalist>
                )}
                <p className="text-[11px] text-muted-foreground mt-1">
                  Propiedad tal y como aparece en Search Console
                </p>
                {savedSite && gscStatus && (
                  <p className="text-[11px] mt-1">
                    {gscStatus.connections.length === 0 ? (
                      <span className="text-muted-foreground">Search Console no está conectado (Ajustes).</span>
                    ) : siteState?.last_data_date ? (
                      <span className="text-muted-foreground">Datos importados hasta el {formatDay(siteState.last_data_date)}.</span>
                    ) : (
                      <span className="text-muted-foreground">Se importará en la próxima pasada diaria.</span>
                    )}
                    {gscErrorLabel(siteState?.error_code) && <span className="block text-amber-600">{gscErrorLabel(siteState?.error_code)}</span>}
                  </p>
                )}
              </div>
            </div>

            {/* Control SEO: separa las búsquedas de marca de las demás. */}
            <BrandTermsEditor
              value={brandTerms}
              onChange={setBrandTerms}
              disabled={!canWriteClients}
              client={client}
              gscDraft={gsc}
            />

            {/* Engine Integration */}
            {isAdmin && <div>
              <Label className="flex items-center gap-1.5">
                <Globe className="h-3.5 w-3.5 text-muted-foreground" />
                Proyecto Engine
              </Label>
              {engineProjects.length > 0 ? (
                <select
                  value={engineProjectId}
                  onChange={(e) => setEngineProjectId(e.target.value)}
                  className="mt-1 w-full border border-input bg-background text-foreground rounded-md px-3 py-2 text-sm"
                  disabled={!canWriteClients}
                >
                  <option value="">Sin vincular</option>
                  {engineProjects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.domain})
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  type="number"
                  value={engineProjectId}
                  onChange={(e) => setEngineProjectId(e.target.value)}
                  placeholder="ID del proyecto en Engine"
                  className="mt-1"
                  disabled={!canWriteClients}
                />
              )}
              <p className="text-[11px] text-muted-foreground mt-1">
                Vincula este cliente con un proyecto de The Engine para ver metricas SEO
              </p>
            </div>}

            <div>
              <Label htmlFor="vigil-slug" className="flex items-center gap-1.5">
                <Radar className="h-3.5 w-3.5 text-muted-foreground" />
                Cliente en Vigil
              </Label>
              <Input
                id="vigil-slug"
                value={vigilSlug}
                onChange={(e) => setVigilSlug(e.target.value)}
                placeholder="fit-generation"
                className="mt-1"
                disabled={!canWriteClients}
                list="vigil-clients"
              />
              {vigil && (
                <datalist id="vigil-clients">
                  {vigil.clients.filter((c) => !c.linked_to || c.slug === client.vigil_slug).map((c) => (
                    <option key={c.slug} value={c.slug}>{c.name}</option>
                  ))}
                </datalist>
              )}
              <p className="text-[11px] text-muted-foreground mt-1">
                {vigil && !vigil.configured ? "Vigil no está configurado en The Agency."
                  : client.vigil_slug && !vigilSaved ? "Todavía no hay resumen de Vigil para este cliente: llega en la próxima lectura."
                  : "Slug del cliente en Vigil. Sus cambios en la web salen en la ficha y en su estado."}
              </p>
            </div>

            {canWriteClients && <div className="flex justify-end">
              <Button type="submit" disabled={!isDirty || updateMut.isPending} size="sm">
                <Save className="h-4 w-4 mr-1" />
                {updateMut.isPending ? "Guardando..." : "Guardar"}
              </Button>
            </div>}
          </form>
        </CardContent>
      </Card>

      {/* Control SEO: grupos de URL propios (se guardan aparte del formulario). */}
      <SeoPageGroupsEditor client={client} canWrite={canWriteClients} />

      <ClientShareLinkCard clientId={client.id} />

      {/* Avisos de caída de su web al Slack del cliente: sólo admin. */}
      {isAdmin && <ClientSlackCard clientId={client.id} />}
    </div>
  )
}

/** Igual que el backend: 'sc-domain:x' tal cual; URL con barra final. */
function normalizeSiteUrl(value: string | null | undefined): string | null {
  const site = value?.trim()
  if (!site) return null
  if (site.startsWith("sc-domain:")) return site
  return /^https?:\/\//.test(site) && !site.endsWith("/") ? `${site}/` : site
}
