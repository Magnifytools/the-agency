import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { inboxApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import type { InboxNote } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CornerDownLeft, Inbox as InboxIcon, X, Sparkles, FolderKanban, ArrowRight } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { Link } from "react-router-dom"

export function InboxWidget() {
    const [newNote, setNewNote] = useState("")
    const queryClient = useQueryClient()

    const { data: inboxNotes = [], isLoading } = useQuery({
        queryKey: [...inboxKeys.list("pending,classified")],
        queryFn: () => inboxApi.list({ status: "pending,classified", limit: 5 }),
    })

    const createMutation = useMutation({
        mutationFn: (raw_text: string) => inboxApi.create({ raw_text, source: "dashboard" }),
        onSuccess: () => {
            setNewNote("")
            queryClient.invalidateQueries({ queryKey: inboxKeys.all() })
            queryClient.invalidateQueries({ queryKey: inboxKeys.count() })
            toast.success("Capturado en el Inbox")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al guardar en el Inbox")),
    })

    const dismissMutation = useMutation({
        mutationFn: (id: number) => inboxApi.dismiss(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: inboxKeys.all() })
            queryClient.invalidateQueries({ queryKey: inboxKeys.count() })
        },
    })

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter" && newNote.trim()) {
            e.preventDefault()
            createMutation.mutate(newNote.trim())
        }
    }

    return (
        <Card className="flex flex-col h-full border-border/50 shadow-sm bg-card/40 backdrop-blur-sm">
            <CardHeader className="pb-3 border-b border-border/40 bg-card/40">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <div className="p-1.5 bg-brand/10 rounded-md">
                        <InboxIcon className="w-4 h-4 text-brand" />
                    </div>
                    Clasificación de Inbox
                    <span className="ml-auto text-xs font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                        {inboxNotes.length} items
                    </span>
                </CardTitle>
            </CardHeader>

            <CardContent className="flex-1 p-0 flex flex-col overflow-hidden">
                <div className="p-3 border-b border-border/40 bg-background/50">
                    <div className="relative group">
                        <Input
                            value={newNote}
                            onChange={(e) => setNewNote(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Captura una idea, llamada o tarea suelta..."
                            className="pl-3 pr-10 py-5 bg-card border-none shadow-inner text-sm placeholder:text-muted-foreground/60 focus-visible:ring-1 focus-visible:ring-brand/50 rounded-xl"
                            disabled={createMutation.isPending}
                            autoComplete="off"
                        />
                        <Button
                            size="icon"
                            variant="ghost"
                            className="absolute right-1 top-1 h-8 w-8 text-muted-foreground hover:text-brand hover:bg-brand/10 transition-colors"
                            onClick={() => newNote.trim() && createMutation.mutate(newNote.trim())}
                            disabled={!newNote.trim() || createMutation.isPending}
                        >
                            <CornerDownLeft className="h-4 w-4" />
                        </Button>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {isLoading ? (
                        <div className="p-4 text-center text-sm text-muted-foreground animate-pulse">Cargando Inbox...</div>
                    ) : inboxNotes.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-40 text-muted-foreground gap-3">
                            <div className="p-4 rounded-full bg-muted/50 border border-border border-dashed">
                                <InboxIcon className="w-6 h-6 opacity-40" />
                            </div>
                            <p className="text-sm">Inbox vacio. Pulsa ⌘J para capturar</p>
                        </div>
                    ) : (
                        inboxNotes.map((note: InboxNote) => (
                            <div
                                key={note.id}
                                className="group flex items-start gap-3 p-3 hover:bg-muted/50 rounded-xl border border-transparent hover:border-border/50 transition-all"
                            >
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-foreground truncate select-none">
                                        {note.raw_text}
                                    </p>
                                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                                        {note.status === "classified" && note.ai_suggestion ? (
                                            <>
                                                {note.ai_suggestion.suggested_project?.name && (
                                                    <span className="text-[10px] text-blue-500 flex items-center gap-1 font-medium bg-blue-500/10 px-1.5 py-0.5 rounded">
                                                        <FolderKanban className="w-3 h-3" />
                                                        {note.ai_suggestion.suggested_project.name}
                                                    </span>
                                                )}
                                                <span className="text-[10px] text-brand flex items-center gap-1 font-medium bg-brand/10 px-1.5 py-0.5 rounded">
                                                    <Sparkles className="w-3 h-3" />
                                                    IA clasifico
                                                </span>
                                            </>
                                        ) : (
                                            <span className="text-[10px] text-muted-foreground flex items-center gap-1 font-medium bg-muted px-1.5 py-0.5 rounded animate-pulse">
                                                <Sparkles className="w-3 h-3" />
                                                Clasificando...
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <button
                                    onClick={() => dismissMutation.mutate(note.id)}
                                    disabled={dismissMutation.isPending}
                                    className="mt-0.5 flex-shrink-0 text-muted-foreground/40 hover:text-destructive opacity-0 group-hover:opacity-100 transition-all"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>
                        ))
                    )}
                </div>

                {inboxNotes.length > 0 && (
                    <div className="p-2 border-t border-border/40">
                        <Link
                            to="/inbox"
                            className="flex items-center justify-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-brand transition-colors py-1.5"
                        >
                            Ver todo
                            <ArrowRight className="w-3 h-3" />
                        </Link>
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
