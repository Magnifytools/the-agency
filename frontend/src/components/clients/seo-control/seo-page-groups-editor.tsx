import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ArrowDown, ArrowUp, FlaskConical, FolderTree, Plus, Save, Trash2, X } from "lucide-react"
import { clientSeoApi, clientsApi } from "@/lib/api"
import { invalidateClientChange } from "@/lib/query-keys"
import type { Client, SeoGroupRuleType, SeoGroupsResponse, SeoPageGroup } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { MAX_GROUP_RULES, MAX_PAGE_GROUPS, formatInt, pageGroupsProblem } from "@/lib/seo-control"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"

interface Props {
  client: Pick<Client, "id" | "gsc_url" | "seo_page_groups">
  canWrite: boolean
}

const RULE_LABELS: Record<SeoGroupRuleType, string> = {
  prefix: "Empieza por",
  contains: "Contiene",
  regex: "Regex",
}
const RULE_PLACEHOLDERS: Record<SeoGroupRuleType, string> = {
  prefix: "/blog/",
  contains: "producto",
  regex: "^/p/\\d+$",
}

function pagesLabel(n: number): string {
  return `${formatInt(n)} ${n === 1 ? "página" : "páginas"}`
}

function same(a: SeoPageGroup[], b: SeoPageGroup[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/**
 * Grupos de URL del Control SEO (Configuración del cliente). Una página va al
 * PRIMER grupo con alguna regla que la acepte: el orden importa. "Probar"
 * cuenta las páginas de los últimos 28 días sin guardar nada.
 */
export function SeoPageGroupsEditor({ client, canWrite }: Props) {
  const qc = useQueryClient()
  const saved = client.seo_page_groups ?? []
  const [groups, setGroups] = useState<SeoPageGroup[]>(saved)
  const [preview, setPreview] = useState<SeoGroupsResponse | null>(null)
  const dirty = !same(groups, saved)
  const problem = pageGroupsProblem(groups)

  const update = (next: SeoPageGroup[]) => {
    setGroups(next)
    setPreview(null)
  }
  const updateGroup = (index: number, patch: Partial<SeoPageGroup>) =>
    update(groups.map((g, i) => (i === index ? { ...g, ...patch } : g)))
  const move = (index: number, delta: number) => {
    const next = [...groups]
    const [item] = next.splice(index, 1)
    next.splice(index + delta, 0, item)
    update(next)
  }

  const previewMut = useMutation({
    mutationFn: () => clientSeoApi.previewGroups(client.id, groups),
    onSuccess: setPreview,
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const saveMut = useMutation({
    mutationFn: () => clientsApi.update(client.id, { seo_page_groups: groups }),
    onSuccess: (updated) => {
      setGroups(updated.seo_page_groups ?? [])
      void invalidateClientChange(qc, [client.id])
      toast.success("Grupos de URL guardados")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const counts = new Map(preview?.groups.map((g) => [g.key, g]) ?? [])
  const ungrouped = counts.get("Sin grupo")

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><FolderTree className="h-4 w-4" /> Grupos de URL</CardTitle>
        <p className="text-xs text-muted-foreground">
          Agrupa las páginas del Control SEO con reglas propias. Cada página cuenta en el PRIMER grupo que la acepta
          (el orden importa); las demás, en «Sin grupo». «Empieza por» mira la ruta (/blog/), «Contiene» cualquier
          parte de la URL y «Regex» la ruta, sin distinguir mayúsculas.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {groups.length === 0 && <p className="text-sm text-muted-foreground">Sin grupos: el Control SEO sólo enseña las secciones.</p>}
        {groups.map((group, gi) => {
          const count = counts.get(group.name.trim())
          return (
            <fieldset key={gi} className="rounded-lg border border-border p-3 space-y-2" aria-label={`Grupo ${gi + 1}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Input aria-label={`Nombre del grupo ${gi + 1}`} value={group.name} placeholder="Blog"
                  onChange={(e) => updateGroup(gi, { name: e.target.value })} className="h-8 w-48 text-sm"
                  disabled={!canWrite} maxLength={60} />
                {preview && (
                  <span className="text-xs text-muted-foreground mono">
                    {count ? `${pagesLabel(count.pages)} · ${formatInt(count.clicks)} clics` : pagesLabel(0)}
                  </span>
                )}
                {canWrite && (
                  <div className="ml-auto flex items-center gap-1">
                    <Button type="button" size="sm" variant="ghost" className="h-7 w-7 p-0" aria-label="Subir grupo"
                      disabled={gi === 0} onClick={() => move(gi, -1)}><ArrowUp className="h-3.5 w-3.5" /></Button>
                    <Button type="button" size="sm" variant="ghost" className="h-7 w-7 p-0" aria-label="Bajar grupo"
                      disabled={gi === groups.length - 1} onClick={() => move(gi, 1)}><ArrowDown className="h-3.5 w-3.5" /></Button>
                    <Button type="button" size="sm" variant="ghost" className="h-7 w-7 p-0" aria-label={`Quitar grupo ${group.name || gi + 1}`}
                      onClick={() => update(groups.filter((_, i) => i !== gi))}><Trash2 className="h-3.5 w-3.5" /></Button>
                  </div>
                )}
              </div>
              {group.rules.map((rule, ri) => (
                <div key={ri} className="flex flex-wrap items-center gap-2">
                  <Select aria-label={`Tipo de regla ${ri + 1} del grupo ${gi + 1}`} value={rule.type} className="w-auto h-8 text-xs"
                    disabled={!canWrite}
                    onChange={(e) => updateGroup(gi, { rules: group.rules.map((r, i) => i === ri ? { ...r, type: e.target.value as SeoGroupRuleType } : r) })}>
                    {(Object.keys(RULE_LABELS) as SeoGroupRuleType[]).map((type) => (
                      <option key={type} value={type}>{RULE_LABELS[type]}</option>
                    ))}
                  </Select>
                  <Input aria-label={`Valor de la regla ${ri + 1} del grupo ${gi + 1}`} value={rule.value}
                    placeholder={RULE_PLACEHOLDERS[rule.type]} className="h-8 flex-1 min-w-[160px] text-xs mono"
                    maxLength={200} disabled={!canWrite}
                    onChange={(e) => updateGroup(gi, { rules: group.rules.map((r, i) => i === ri ? { ...r, value: e.target.value } : r) })} />
                  {canWrite && group.rules.length > 1 && (
                    <Button type="button" size="sm" variant="ghost" className="h-7 w-7 p-0" aria-label="Quitar regla"
                      onClick={() => updateGroup(gi, { rules: group.rules.filter((_, i) => i !== ri) })}><X className="h-3.5 w-3.5" /></Button>
                  )}
                </div>
              ))}
              {canWrite && group.rules.length < MAX_GROUP_RULES && (
                <Button type="button" size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => updateGroup(gi, { rules: [...group.rules, { type: "prefix", value: "" }] })}>
                  <Plus className="h-3.5 w-3.5 mr-1" /> Regla
                </Button>
              )}
            </fieldset>
          )
        })}
        {preview && ungrouped && (
          <p className="text-xs text-muted-foreground">
            Sin grupo: {pagesLabel(ungrouped.pages)} · {formatInt(ungrouped.clicks)} clics (últimos {preview.window?.days ?? 28} días).
          </p>
        )}
        {preview && preview.status !== "ok" && (
          <p className="text-xs text-muted-foreground">Aún no hay páginas importadas de Search Console para probar.</p>
        )}
        {problem && groups.length > 0 && <p className="text-xs text-amber-600">{problem}</p>}
        {canWrite && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" size="sm" variant="ghost" disabled={groups.length >= MAX_PAGE_GROUPS}
              onClick={() => update([...groups, { name: "", rules: [{ type: "prefix", value: "" }] }])}>
              <Plus className="h-4 w-4 mr-1" /> Añadir grupo
            </Button>
            <div className="flex items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={!client.gsc_url || !!problem || previewMut.isPending}
                onClick={() => previewMut.mutate()}>
                <FlaskConical className="h-4 w-4 mr-1" /> {previewMut.isPending ? "Probando…" : "Probar"}
              </Button>
              <Button type="button" size="sm" disabled={!dirty || !!problem || saveMut.isPending} onClick={() => saveMut.mutate()}>
                <Save className="h-4 w-4 mr-1" /> {saveMut.isPending ? "Guardando…" : "Guardar grupos"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
