import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { CheckSquare, Globe, PenLine, Trash2, TriangleAlert } from "lucide-react"
import { toast } from "sonner"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type { SeoAnnotation, SeoAnnotations } from "@/lib/types"
import { formatDay } from "@/lib/gsc"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

const KIND: Record<SeoAnnotation["kind"], { label: string; icon: typeof Globe; className: string }> = {
  manual: { label: "Nota", icon: PenLine, className: "text-brand" },
  google: { label: "Google", icon: Globe, className: "text-sky-500" },
  web_change: { label: "Web", icon: TriangleAlert, className: "text-destructive" },
  task: { label: "Tarea", icon: CheckSquare, className: "text-emerald-500" },
}

interface Props {
  clientId: number
  from: string
  to: string
  data: SeoAnnotations | undefined
  isError: boolean
  onRetry: () => void
  canWrite: boolean
  /** Pide el antes/después de una fecha (rellena la tarjeta de impacto). */
  onCompare?: (date: string) => void
}

/** "Qué ha pasado": lo que explica las subidas y bajadas del periodo de la gráfica. */
export function SeoAnnotationsCard({ clientId, from, to, data, isError, onRetry, canWrite, onCompare }: Props) {
  const queryClient = useQueryClient()
  const [date, setDate] = useState(to)
  const [text, setText] = useState("")
  const refresh = () => queryClient.invalidateQueries({ queryKey: clientSeoKeys.annotations(clientId, from, to) })
  const create = useMutation({
    mutationFn: () => clientSeoApi.createAnnotation(clientId, { date, text: text.trim() }),
    onSuccess: () => { setText(""); void refresh(); toast.success("Nota añadida a la gráfica") },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo guardar la nota")),
  })
  const remove = useMutation({
    mutationFn: (id: number) => clientSeoApi.deleteAnnotation(clientId, id),
    onSuccess: () => void refresh(),
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo borrar la nota")),
  })
  const items = [...(data?.items ?? [])].reverse()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Qué ha pasado</CardTitle>
        <p className="text-xs text-muted-foreground">
          Del {formatDay(from)} al {formatDay(to)}: notas del equipo, actualizaciones de Google, cambios críticos de la web y tareas publicadas. Las semanas con algo salen marcadas en la gráfica.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {canWrite && (
          <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); if (text.trim()) create.mutate() }}>
            <Input type="date" aria-label="Fecha de la nota" value={date} max={to} onChange={(event) => setDate(event.target.value)} className="sm:w-40" />
            <Input aria-label="Nota" placeholder="Qué cambió (p. ej. «nuevos títulos en el blog»)" maxLength={160} value={text}
              onChange={(event) => setText(event.target.value)} className="flex-1" />
            <Button type="submit" size="sm" disabled={!text.trim() || !date || create.isPending}>Añadir nota</Button>
          </form>
        )}
        {isError ? (
          <div role="alert" className="text-sm">No se pudo cargar lo que ha pasado. <Button size="sm" variant="outline" onClick={onRetry}>Reintentar</Button></div>
        ) : !data ? (
          <p role="status" className="text-sm text-muted-foreground">Cargando…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nada anotado en este periodo.</p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => {
              const kind = KIND[item.kind]
              const Icon = kind.icon
              const external = item.href?.startsWith("http")
              return (
                <li key={`${item.kind}-${item.id ?? item.title}-${item.date}`} className="flex items-start gap-3 py-2 text-sm">
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${kind.className}`} aria-label={kind.label} />
                  <div className="min-w-0 flex-1">
                    <p className="break-words">
                      {item.href ? (external
                        ? <a href={item.href} target="_blank" rel="noreferrer" className="hover:underline">{item.title}</a>
                        : <Link to={item.href} className="hover:underline">{item.title}</Link>) : item.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatDay(item.date)}{item.end_date && item.end_date !== item.date ? ` – ${formatDay(item.end_date)}` : ""}
                      {item.author ? ` · ${item.author}` : ""}
                    </p>
                  </div>
                  {onCompare && <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onCompare(item.date)}>Antes y después</Button>}
                  {canWrite && item.kind === "manual" && typeof item.id === "number" && (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" aria-label={`Borrar la nota ${item.title}`}
                      disabled={remove.isPending} onClick={() => remove.mutate(item.id as number)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        {data && !data.google_available && (
          <p className="text-[11px] text-muted-foreground">No se pudo consultar el panel de estado de Google: faltan sus actualizaciones.</p>
        )}
      </CardContent>
    </Card>
  )
}
