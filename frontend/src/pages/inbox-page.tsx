import { useState } from "react"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { inboxApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import type { InboxNote } from "@/lib/types"
import { InboxNoteCard } from "@/components/inbox/inbox-note-card"
import { QuickCaptureDialog } from "@/components/inbox/quick-capture-dialog"
import { Button } from "@/components/ui/button"
import { Inbox, Plus, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"

const TABS = [
  { key: "active", label: "Activos", filter: "pending,classified" },
  { key: "all", label: "Todos", filter: undefined },
  { key: "processed", label: "Procesados", filter: "processed" },
  { key: "dismissed", label: "Descartados", filter: "dismissed" },
] as const

export default function InboxPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<string>("active")
  const [captureOpen, setCaptureOpen] = useState(false)

  const currentFilter = TABS.find((t) => t.key === activeTab)?.filter

  const notesQuery = useInfiniteQuery({
    queryKey: inboxKeys.list(user?.id ?? 0, currentFilter ?? "all", 50),
    queryFn: ({ pageParam }) => inboxApi.list({ status: currentFilter, limit: 50, offset: pageParam }),
    enabled: !!user,
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === 50 ? pages.flat().length : undefined,
    refetchInterval: (query) => query.state.data?.pages.some((page) => page.some((note) => note.status === "pending")) ? 10_000 : false,
    refetchIntervalInBackground: false,
  })
  const notes = Array.from(new Map((notesQuery.data?.pages.flat() ?? []).map((note) => [note.id, note])).values())

  const { data: countData } = useQuery({
    queryKey: inboxKeys.count(user?.id ?? 0),
    queryFn: inboxApi.count,
    enabled: !!user,
    refetchIntervalInBackground: false,
  })

  const activeCount = countData?.count ?? 0

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-brand/10 rounded-xl">
            <Inbox className="w-5 h-5 text-brand" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">Inbox</h1>
            <p className="text-sm text-muted-foreground">
              {activeCount > 0 ? `${activeCount} por procesar` : "Todo al día"}
            </p>
          </div>
        </div>
        <Button onClick={() => setCaptureOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" />
          Capturar
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex max-w-full gap-1 overflow-x-auto rounded-xl bg-muted/50 p-1 scrollbar-none">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "shrink-0 px-4 py-1.5 text-sm font-medium rounded-lg transition-all",
              activeTab === tab.key
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Notes list */}
      {notesQuery.isError && notes.length > 0 && (
        <div role="alert" className="rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm">
          <p>La última actualización del Inbox falló. Se muestran las notas ya cargadas.</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => void notesQuery.refetch()}>Reintentar</Button>
        </div>
      )}

      {notesQuery.isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : notesQuery.isError && notes.length === 0 ? (
        <div role="alert" className="rounded-xl border border-destructive/40 p-5 text-sm">
          <p className="font-medium">No se pudo cargar el Inbox.</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void notesQuery.refetch()}>Reintentar</Button>
        </div>
      ) : notes.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-4">
          <div className="p-6 rounded-2xl bg-muted/30 border border-border border-dashed">
            <Inbox className="w-10 h-10 opacity-30" />
          </div>
          <div className="text-center">
            <p className="font-medium">
              {activeTab === "active" ? "Inbox vacío" : "Sin notas"}
            </p>
            <p className="text-sm mt-1">
              {activeTab === "active"
                ? "Pulsa ⌘J para capturar algo rápido"
                : "No hay notas en este filtro"}
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {notes.map((note: InboxNote) => (
            <InboxNoteCard key={note.id} note={note} />
          ))}
        </div>
      )}

      {notesQuery.hasNextPage && (
        <Button variant="outline" className="w-full" onClick={() => void notesQuery.fetchNextPage()} isLoading={notesQuery.isFetchingNextPage}>
          Cargar más
        </Button>
      )}
      {notesQuery.isFetchNextPageError && (
        <p role="alert" className="text-sm text-destructive">No se pudieron cargar más notas. <button type="button" className="underline" onClick={() => void notesQuery.fetchNextPage()}>Reintentar</button></p>
      )}

      <QuickCaptureDialog open={captureOpen} onOpenChange={setCaptureOpen} />
    </div>
  )
}
