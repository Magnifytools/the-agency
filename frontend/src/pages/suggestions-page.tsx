import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Lightbulb, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { suggestionsApi, type SuggestionStatus } from "@/lib/api"
import { suggestionKeys } from "@/lib/query-keys"
import type { AppSuggestion } from "@/lib/types"
import { formatTimeAgo, getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { SuggestionDialog } from "@/components/layout/suggestion-button"

const FILTERS: { value: SuggestionStatus; label: string }[] = [
  { value: "open", label: "Pendientes" },
  { value: "done", label: "Hechas" },
  { value: "all", label: "Todas" },
]

export default function SuggestionsPage() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<SuggestionStatus>("open")
  const [dialogOpen, setDialogOpen] = useState(false)

  const query = useQuery({
    queryKey: suggestionKeys.list(status),
    queryFn: () => suggestionsApi.list(status),
  })

  const update = useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) => suggestionsApi.update(id, { done }),
    onSuccess: (_row, { done }) => {
      void queryClient.invalidateQueries({ queryKey: suggestionKeys.all })
      toast.success(done ? "Marcada como hecha" : "Vuelve a pendientes")
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo actualizar la sugerencia")),
  })

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Sugerencias</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isAdmin
              ? "Ideas y fallos que deja el equipo. Márcalas como hechas y quien la envió se entera."
              : "Las ideas y fallos que has enviado y en qué han quedado."}
          </p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <Lightbulb className="h-4 w-4 mr-1" />
          Nueva sugerencia
        </Button>
      </div>

      <div className="flex gap-1" role="group" aria-label="Filtrar sugerencias">
        {FILTERS.map((filter) => (
          <Button
            key={filter.value}
            size="sm"
            variant={status === filter.value ? "secondary" : "ghost"}
            aria-pressed={status === filter.value}
            onClick={() => setStatus(filter.value)}
          >
            {filter.label}
          </Button>
        ))}
      </div>

      {query.isLoading && <p className="text-sm text-muted-foreground">Cargando sugerencias…</p>}
      {query.isError && (
        <p className="text-sm text-destructive">
          {getErrorMessage(query.error, "No se pudieron cargar las sugerencias")}
        </p>
      )}
      {query.data && query.data.length === 0 && (
        <EmptyState
          icon={Lightbulb}
          title={status === "done" ? "Nada hecho todavía" : "No hay sugerencias pendientes"}
          description="Usa «Sugerencias o fallos» en la barra lateral para dejar una."
        />
      )}
      <ul className="space-y-3">
        {query.data?.map((item) => (
          <SuggestionRow
            key={item.id}
            item={item}
            canResolve={isAdmin}
            pending={update.isPending && update.variables?.id === item.id}
            onToggle={() => update.mutate({ id: item.id, done: !item.done_at })}
          />
        ))}
      </ul>

      <SuggestionDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  )
}

function SuggestionRow({
  item, canResolve, pending, onToggle,
}: { item: AppSuggestion; canResolve: boolean; pending: boolean; onToggle: () => void }) {
  const done = !!item.done_at
  return (
    <li className="rounded-xl border border-border bg-card p-4 space-y-2">
      <p className={`text-sm whitespace-pre-wrap break-words ${done ? "text-muted-foreground" : ""}`}>{item.text}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          {item.author_name ?? "Usuario eliminado"} · {formatTimeAgo(item.created_at)}
        </span>
        {item.page_path && (
          <span>
            desde <Link to={item.page_path} className="underline hover:text-foreground">{item.page_path}</Link>
          </span>
        )}
        {done && (
          <span className="inline-flex items-center gap-1 text-success">
            <Check className="h-3 w-3" />
            Hecha{item.done_by_name ? ` por ${item.done_by_name}` : ""} · {formatTimeAgo(item.done_at!)}
          </span>
        )}
        {canResolve && (
          <Button size="sm" variant={done ? "ghost" : "outline"} className="ml-auto" disabled={pending} onClick={onToggle}>
            {done ? <RotateCcw className="h-3.5 w-3.5 mr-1" /> : <Check className="h-3.5 w-3.5 mr-1" />}
            {done ? "Reabrir" : "Marcar como hecha"}
          </Button>
        )}
      </div>
    </li>
  )
}
