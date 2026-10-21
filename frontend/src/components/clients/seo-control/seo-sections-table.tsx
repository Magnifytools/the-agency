import { FolderTree } from "lucide-react"
import type { SeoSection } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { DeltaBadge } from "@/components/clients/delta-badge"
import { formatInt, formatPosition, formatShare } from "@/lib/seo-control"

interface Props {
  sections: SeoSection[]
  selected: string | null
  onSelect: (key: string | null) => void
}

/**
 * Secciones de la web (primer tramo de la URL). El reparto es por clics: las
 * impresiones por página no suman el total de la propiedad (una búsqueda que
 * enseña dos páginas cuenta en las dos), así que sólo se enseñan en absoluto.
 */
export function SeoSectionsTable({ sections, selected, onSelect }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><FolderTree className="h-4 w-4" /> Secciones</CardTitle>
        <p className="text-xs text-muted-foreground">Pulsa una sección para ver sus páginas abajo.</p>
      </CardHeader>
      <CardContent>
        {sections.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin páginas con impresiones en la ventana.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Sección</TableHead>
                  <TableHead className="min-w-[140px]">Reparto de clics</TableHead>
                  <TableHead className="text-right">Clics</TableHead>
                  <TableHead className="text-right">Impresiones</TableHead>
                  <TableHead className="text-right">Posición</TableHead>
                  <TableHead className="text-right">Páginas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sections.map((s) => {
                  const active = selected === s.key
                  return (
                    <TableRow key={s.key} className={active ? "bg-brand/10" : undefined}>
                      <TableCell>
                        <button
                          type="button"
                          className="text-left font-medium hover:underline focus-visible:outline-2 focus-visible:outline-brand"
                          aria-pressed={active}
                          onClick={() => onSelect(active ? null : s.key)}
                        >
                          {s.label}
                        </button>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden" aria-hidden="true">
                            <div className="h-full bg-brand" style={{ width: `${Math.round((s.clicks_share ?? 0) * 100)}%` }} />
                          </div>
                          <span className="mono text-xs w-14 text-right">{formatShare(s.clicks_share)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="mono">{formatInt(s.clicks)}</span>{" "}
                        <DeltaBadge value={s.clicks_pct} digits={1} />
                      </TableCell>
                      <TableCell className="text-right mono">{formatInt(s.impressions)}</TableCell>
                      <TableCell className="text-right">
                        <span className="mono">{formatPosition(s.position)}</span>{" "}
                        <DeltaBadge value={s.position_delta} suffix="" digits={1} />
                      </TableCell>
                      <TableCell className="text-right mono">{formatInt(s.pages)}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
