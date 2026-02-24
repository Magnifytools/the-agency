import type { Task, TaskStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Clock, Play, CheckCircle2 } from "lucide-react"

interface MyDayViewProps {
    tasks: Task[]
    onStatusChange: (id: number, status: TaskStatus) => void
    onOpenEdit: (task: Task) => void
}

const statusColor = (status: TaskStatus) => {
    switch (status) {
        case "completed": return "bg-green-500/10 text-green-700 border-green-200"
        case "in_progress": return "bg-amber-500/10 text-amber-700 border-amber-200"
        default: return "bg-slate-100 text-slate-700 border-slate-200"
    }
}

export function MyDayView({ tasks, onStatusChange, onOpenEdit }: MyDayViewProps) {
    // Simple deterministic sorting: In Progress -> Pending -> Completed
    const sortedTasks = [...tasks].sort((a, b) => {
        const order = { in_progress: 0, pending: 1, completed: 2 }
        return order[a.status] - order[b.status]
    })

    if (sortedTasks.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
                <CheckCircle2 className="h-12 w-12 mb-4 text-green-500/50" />
                <p className="text-lg font-medium">¡Todo al día!</p>
                <p className="text-sm">No tienes tareas pendientes para hoy.</p>
            </div>
        )
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sortedTasks.map(task => (
                <Card key={task.id} className={`overflow-hidden border-l-4 ${task.status === 'in_progress' ? 'border-l-amber-500' : task.status === 'completed' ? 'border-l-green-500' : 'border-l-slate-300'}`}>
                    <CardContent className="p-4 flex flex-col h-full">
                        <div className="flex justify-between items-start mb-2">
                            <span className={`text-xs font-semibold px-2 py-1 rounded-sm border ${statusColor(task.status)} uppercase tracking-wider`}>
                                {task.status === "pending" ? "Pendiente" : task.status === "in_progress" ? "En Curso" : "Completada"}
                            </span>
                            {task.due_date && (
                                <span className="text-xs text-muted-foreground flex items-center">
                                    <Clock className="w-3 h-3 mr-1" />
                                    {new Date(task.due_date).toLocaleDateString("es-ES")}
                                </span>
                            )}
                        </div>

                        <h3 className="font-semibold text-base mb-1 cursor-pointer hover:text-brand transition-colors" onClick={() => onOpenEdit(task)}>
                            {task.title}
                        </h3>

                        <p className="text-sm text-muted-foreground line-clamp-2 flex-grow mb-4">
                            {task.project_name ? `${task.project_name} - ` : ''}
                            {task.description || "Sin descripción"}
                        </p>

                        <div className="flex items-center justify-between mt-auto pt-4 border-t border-border">
                            <div className="text-xs font-mono text-muted-foreground">
                                {task.estimated_minutes ? `${task.estimated_minutes}m est.` : '--'}
                            </div>

                            <div className="flex gap-2">
                                {task.status === "pending" && (
                                    <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => onStatusChange(task.id, "in_progress")}>
                                        <Play className="w-3 h-3 mr-1" /> Iniciar
                                    </Button>
                                )}
                                {task.status === "in_progress" && (
                                    <Button size="sm" variant="default" className="h-8 text-xs bg-green-600 hover:bg-green-700" onClick={() => onStatusChange(task.id, "completed")}>
                                        <CheckCircle2 className="w-3 h-3 mr-1" /> Completar
                                    </Button>
                                )}
                                {task.status === "completed" && (
                                    <Button size="sm" variant="ghost" className="h-8 text-xs text-muted-foreground" onClick={() => onStatusChange(task.id, "pending")}>
                                        Reabrir
                                    </Button>
                                )}
                            </div>
                        </div>
                    </CardContent>
                </Card>
            ))}
        </div>
    )
}
