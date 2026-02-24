import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { tasksApi } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CornerDownLeft, Inbox as InboxIcon, CheckCircle2, GripVertical, AlertCircle } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export function InboxWidget() {
    const [newTask, setNewTask] = useState("")
    const queryClient = useQueryClient()

    const { data: inboxTasks = [], isLoading } = useQuery({
        queryKey: ["inbox-tasks"],
        // Query functions would go here, assuming tasksApi supports fetching inbox/unassigned items
        queryFn: () => tasksApi.listAll({ status: "pending" } as any),
    })

    // We map a quick capture mutation here, assuming the backend can handle creating a minimal task.
    const createMutation = useMutation({
        mutationFn: (title: string) => tasksApi.create({ title, is_inbox: true, status: "pending" } as any),
        onSuccess: () => {
            setNewTask("")
            queryClient.invalidateQueries({ queryKey: ["inbox-tasks"] })
            toast.success("Capturado en el Inbox")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al guardar en el Inbox")),
    })

    const completeMutation = useMutation({
        mutationFn: (id: number) => tasksApi.update(id, { status: "completed" } as any),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["inbox-tasks"] })
            toast.success("Tarea completada")
        },
    })

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter" && newTask.trim()) {
            e.preventDefault()
            createMutation.mutate(newTask.trim())
        }
    }

    return (
        <Card className="flex flex-col h-full border-border/50 shadow-sm bg-card/40 backdrop-blur-sm">
            <CardHeader className="pb-3 border-b border-border/40 bg-card/40">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <div className="p-1.5 bg-brand/10 rounded-md">
                        <InboxIcon className="w-4 h-4 text-brand" />
                    </div>
                    Inbox Triage
                    <span className="ml-auto text-xs font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                        {inboxTasks.length} items
                    </span>
                </CardTitle>
            </CardHeader>

            <CardContent className="flex-1 p-0 flex flex-col overflow-hidden">
                <div className="p-3 border-b border-border/40 bg-background/50">
                    <div className="relative group">
                        <Input
                            value={newTask}
                            onChange={(e) => setNewTask(e.target.value)}
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
                            onClick={() => newTask.trim() && createMutation.mutate(newTask.trim())}
                            disabled={!newTask.trim() || createMutation.isPending}
                        >
                            <CornerDownLeft className="h-4 w-4" />
                        </Button>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {isLoading ? (
                        <div className="p-4 text-center text-sm text-muted-foreground animate-pulse">Cargando Inbox...</div>
                    ) : inboxTasks.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-40 text-muted-foreground gap-3">
                            <div className="p-4 rounded-full bg-muted/50 border border-border border-dashed">
                                <InboxIcon className="w-6 h-6 opacity-40" />
                            </div>
                            <p className="text-sm">Inbox vacío. ¡Gran trabajo!</p>
                        </div>
                    ) : (
                        inboxTasks.map((task: any) => (
                            <div
                                key={task.id}
                                className="group flex items-start gap-3 p-3 hover:bg-muted/50 rounded-xl border border-transparent hover:border-border/50 transition-all"
                            >
                                <div className="mt-0.5 cursor-grab active:cursor-grabbing opacity-0 group-hover:opacity-100 transition-opacity">
                                    <GripVertical className="h-4 w-4 text-muted-foreground/40" />
                                </div>

                                <button
                                    onClick={() => completeMutation.mutate(task.id)}
                                    disabled={completeMutation.isPending}
                                    className="mt-0.5 flex-shrink-0 text-muted-foreground hover:text-success transition-colors"
                                >
                                    <CheckCircle2 className="w-5 h-5" />
                                </button>

                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-foreground truncate select-none">
                                        {task.title}
                                    </p>
                                    <div className="flex items-center gap-2 mt-1">
                                        <span className="text-[10px] text-warning flex items-center gap-1 font-medium bg-warning/10 px-1.5 py-0.5 rounded cursor-pointer hover:bg-warning/20 transition-colors">
                                            <AlertCircle className="w-3 h-3" />
                                            Sin clasificar
                                        </span>
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </CardContent>
        </Card>
    )
}
