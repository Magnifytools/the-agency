import { useState, type FormEvent } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ExternalLink, FileText, Search, X } from "lucide-react"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type {
  SeoBrandFilter,
  SeoMoversParams,
  SeoMoversResponse,
  SeoPageRow,
  SeoQueryRow,
  SeoWindowDays,
} from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { DeltaBadge } from "@/components/clients/delta-badge"
import { formatInt, formatPosition } from "@/lib/seo-control"

type Kind = "queries" | "pages"
type Row = SeoQueryRow | SeoPageRow
type Direction = "gain" | "loss"
type Metric = "clicks" | "position"

// Lo mismo que trae el resumen: con estos filtros no hace falta otra petición.
const SUMMARY_LIMIT = 5
const DEFAULT_MIN_IMPRESSIONS = 30
const LIMIT_STEPS = [SUMMARY_LIMIT, 25, 50, 100]
const MIN_IMPRESSION_OPTIONS = [0, 10, 30, 100, 500]

interface Props {
  clientId: number
  kind: Kind
  days: SeoWindowDays
  summaryRows: { gainers: Row[]; losers: Row[] } | null
  section?: string | null
  sectionLabel?: string | null
  onClearSection?: () => void
}

function rowKey(row: Row): string {
  return "query" in row ? row.query : row.page
}

function pagePath(url: string): string {
  try {
    const parsed = new URL(url)
    return `${parsed.pathname}${parsed.search}` || "/"
  } catch {
    return url
  }
}

/** Consultas o páginas que más suben o bajan, por clics o por posición. */
export function SeoMoversTable({ clientId, kind, days, summaryRows, section, sectionLabel, onClearSection }: Props) {
  const [direction, setDirection] = useState<Direction>("gain")
  const [metric, setMetric] = useState<Metric>("clicks")
  const [brand, setBrand] = useState<SeoBrandFilter>("all")
  const [search, setSearch] = useState("")
  const [q, setQ] = useState("")
  const [minImpressions, setMinImpressions] = useState(DEFAULT_MIN_IMPRESSIONS)
  const [limit, setLimit] = useState(SUMMARY_LIMIT)

  const params: SeoMoversParams = {
    days,
    sort: `${metric}_${direction}`,
    min_impressions: minImpressions,
    limit,
    ...(kind === "queries" && brand !== "all" ? { brand } : {}),
    ...(kind === "pages" && section ? { section } : {}),
    ...(q ? { q } : {}),
  }
  const fromSummary =
    summaryRows != null && metric === "clicks" && limit === SUMMARY_LIMIT && minImpressions === DEFAULT_MIN_IMPRESSIONS
    && brand === "all" && !q && !section

  const listQuery = useQuery<SeoMoversResponse<Row>>({
    queryKey: clientSeoKeys.list(clientId, kind, params),
    queryFn: (): Promise<SeoMoversResponse<Row>> =>
      kind === "queries" ? clientSeoApi.queries(clientId, params) : clientSeoApi.pages(clientId, params),
    enabled: !fromSummary,
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
  })

  const rows: Row[] = fromSummary
    ? (direction === "gain" ? summaryRows.gainers : summaryRows.losers)
    : listQuery.data?.rows ?? []
  const total = fromSummary ? null : listQuery.data?.total ?? null
  const nextLimit = LIMIT_STEPS.find((step) => step > limit)
  const canShowMore = nextLimit != null && (total == null ? rows.length >= limit : total > rows.length)

  const resetPaging = () => setLimit(SUMMARY_LIMIT)
  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    setQ(search.trim())
    resetPaging()
  }

  const title = kind === "queries" ? "Consultas" : "Páginas"
  const Icon = kind === "queries" ? Search : FileText

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base"><Icon className="h-4 w-4" /> {title}</CardTitle>
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label={`${title}: qué enseñar`}>
            {(["gain", "loss"] as const).map((value) => (
              <Button key={value} size="sm" variant={direction === value ? "secondary" : "ghost"} className="h-7 text-xs"
                aria-pressed={direction === value} onClick={() => { setDirection(value); resetPaging() }}>
                {value === "gain" ? "Suben" : "Bajan"}
              </Button>
            ))}
            <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
            {(["clicks", "position"] as const).map((value) => (
              <Button key={value} size="sm" variant={metric === value ? "secondary" : "ghost"} className="h-7 text-xs"
                aria-pressed={metric === value} onClick={() => { setMetric(value); resetPaging() }}>
                {value === "clicks" ? "Clics" : "Posición"}
              </Button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {kind === "queries" && (
            <Select aria-label="Filtrar por marca" value={brand} className="w-auto h-8 text-xs"
              onChange={(e) => { setBrand(e.target.value as SeoBrandFilter); resetPaging() }}>
              <option value="all">Todas</option>
              <option value="brand">Marca</option>
              <option value="non_brand">Sin marca</option>
            </Select>
          )}
          <form onSubmit={submitSearch} className="flex items-center gap-1">
            <Input aria-label={`Buscar ${title.toLowerCase()}`} placeholder="Buscar…" value={search}
              onChange={(e) => setSearch(e.target.value)} className="h-8 w-44 text-xs" />
            <Button type="submit" size="sm" variant="ghost" className="h-8 text-xs">Buscar</Button>
          </form>
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            Mín. impresiones
            <Select aria-label="Mínimo de impresiones" value={String(minImpressions)} className="w-auto h-8 text-xs"
              onChange={(e) => { setMinImpressions(Number(e.target.value)); resetPaging() }}>
              {MIN_IMPRESSION_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
            </Select>
          </label>
          {kind === "pages" && section && (
            <Badge variant="secondary" className="gap-1">
              Sección {sectionLabel ?? section}
              {onClearSection && (
                <button type="button" aria-label="Quitar filtro de sección" onClick={onClearSection}><X className="h-3 w-3" /></button>
              )}
            </Badge>
          )}
        </div>
        {metric === "position" && (
          <p className="text-[11px] text-muted-foreground">
            Por posición sólo cuentan las que tienen el mínimo de impresiones en las dos ventanas.
          </p>
        )}
      </CardHeader>
      <CardContent>
        {listQuery.isError && !fromSummary ? (
          <p className="text-sm text-muted-foreground">No se pudo cargar la lista.</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {listQuery.isLoading && !fromSummary ? "Cargando…" : "Nada que enseñar con estos filtros."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{kind === "queries" ? "Consulta" : "Página"}</TableHead>
                  <TableHead className="text-right">Clics</TableHead>
                  <TableHead className="text-right">Δ clics</TableHead>
                  <TableHead className="text-right">Impresiones</TableHead>
                  <TableHead className="text-right">Posición</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={rowKey(row)}>
                    <TableCell className="max-w-[320px]">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {"query" in row ? (
                          <span className="break-words">{row.query}</span>
                        ) : (
                          <a href={row.page} target="_blank" rel="noopener noreferrer"
                            className="break-all hover:underline inline-flex items-center gap-1" title={row.page}>
                            {pagePath(row.page)} <ExternalLink className="h-3 w-3 shrink-0" />
                          </a>
                        )}
                        {row.state === "new" && <Badge variant="success">Nueva</Badge>}
                        {row.state === "lost" && <Badge variant="destructive">Perdida</Badge>}
                        {"is_brand" in row && row.is_brand && <Badge variant="outline">Marca</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="text-right mono whitespace-nowrap">
                      {formatInt(row.previous_clicks)} → {formatInt(row.clicks)}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <span className={`mono ${row.clicks_delta > 0 ? "text-green-600" : row.clicks_delta < 0 ? "text-red-500" : ""}`}>
                        {row.clicks_delta > 0 ? "+" : ""}{formatInt(row.clicks_delta)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right mono">{formatInt(row.impressions)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <span className="mono">{formatPosition(row.previous_position)} → {formatPosition(row.position)}</span>{" "}
                      <DeltaBadge value={row.position_delta} suffix="" digits={1} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {canShowMore && rows.length > 0 && (
          <div className="mt-3 flex justify-center">
            <Button size="sm" variant="ghost" onClick={() => setLimit(nextLimit)} disabled={listQuery.isFetching}>
              Ver más
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
