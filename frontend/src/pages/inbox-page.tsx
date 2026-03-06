import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { inboxApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import type { InboxNote } from "@/lib/types"
import { InboxNoteCard } from "@/components/inbox/inbox-note-card"
import { QuickCaptureDialog } from "@/components/inbox/quick-capture-dialog"
import { Button } from "@/components/ui/button"
import { Inbox, Plus, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "active", label: "Activos", filter: "pending,classified" },
  { key: "all", label: "Todos", filter: undefined },
  { key: "processed", label: "Procesados", filter: "processed" },
  { key: "dismissed", label: "Descartados", filter: "dismissed" },
] as const

export default function InboxPage() {
  const [activeTab, setActiveTab] = useState<string>("active")
  const [captureOpen, setCaptureOpen] = useState(false)

  const currentFilter = TABS.find((t) => t.key === activeTab)?.filter

  const { data: notes = [], isLoading } = useQuery({
    queryKey: [...inboxKeys.list(currentFilter ?? "all")],
    queryFn: () => inboxApi.list({ status: currentFilter, limit: 100 }),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })

  const { data: countData } = useQuery({
    queryKey: inboxKeys.count(),
    queryFn: inboxApi.count,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })

  const activeCount = countData?.count ?? 0

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
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
      <div className="flex gap-1 p-1 bg-muted/50 rounded-xl w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "px-4 py-1.5 text-sm font-medium rounded-lg transition-all",
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
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
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

      <QuickCaptureDialog open={captureOpen} onOpenChange={setCaptureOpen} />
    </div>
  )
}
