import type { Task, TaskStatus } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
} from "@dnd-kit/core"
import type { DragEndEvent } from "@dnd-kit/core"
import {
    SortableContext,
    sortableKeyboardCoordinates,
    verticalListSortingStrategy,
    useSortable,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"

interface KanbanBoardProps {
    tasks: Task[]
    onStatusChange: (taskId: number, newStatus: TaskStatus) => void
    onOpenEdit: (task: Task) => void
}

const COLUMNS: { id: TaskStatus; title: string; color: string }[] = [
    { id: "pending", title: "Pendiente", color: "bg-slate-100/50 border-slate-200" },
    { id: "in_progress", title: "En Curso", color: "bg-amber-50/50 border-amber-200" },
    { id: "completed", title: "Completada", color: "bg-green-50/50 border-green-200" },
]

function SortableTaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: task.id.toString(),
        data: { type: "Task", task },
    })

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
    }

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            {...listeners}
            onClick={onClick}
            className={`bg-card text-card-foreground shadow-sm rounded-md p-3 mb-2 cursor-grab active:cursor-grabbing border ${isDragging ? 'border-brand/50 shadow-md' : 'border-border hover:border-brand/30'} transition-all`}
        >
            <div className="font-medium text-sm mb-1">{task.title}</div>
            {task.project_name && (
                <div className="text-xs text-muted-foreground mb-2 truncate">
                    {task.project_name}
                </div>
            )}
            <div className="flex items-center gap-2 mt-2">
                {task.category_name && (
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                        {task.category_name}
                    </Badge>
                )}
                {task.assigned_user_name && (
                    <div className="text-[10px] bg-secondary text-secondary-foreground px-1.5 rounded-sm">
                        {task.assigned_user_name.split(' ')[0]}
                    </div>
                )}
            </div>
        </div>
    )
}

function KanbanColumn({ id, title, color, tasks, onOpenEdit }: { id: string; title: string; color: string; tasks: Task[]; onOpenEdit: (t: Task) => void }) {
    return (
        <div id={id} className={`flex flex-col rounded-lg border w-full min-w-[300px] max-w-sm ${color} p-2 h-[calc(100vh-220px)] relative overflow-hidden`}>
            <div className="flex items-center justify-between mb-3 px-1 sticky top-0 z-10 backdrop-blur-sm bg-background/50 rounded-md py-1">
                <h3 className="font-semibold text-sm uppercase tracking-wider">{title}</h3>
                <span className="text-xs font-mono bg-background text-muted-foreground px-2 py-0.5 rounded-full border">
                    {tasks.length}
                </span>
            </div>

            <div className="flex-1 overflow-y-auto overflow-x-hidden pr-1 pb-4 flex flex-col pt-1">
                <SortableContext items={tasks.map((t) => t.id.toString())} strategy={verticalListSortingStrategy}>
                    {tasks.map((task) => (
                        <SortableTaskCard key={task.id} task={task} onClick={() => onOpenEdit(task)} />
                    ))}
                </SortableContext>
            </div>
        </div>
    )
}

export function KanbanBoard({ tasks, onStatusChange, onOpenEdit }: KanbanBoardProps) {
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const handleDragEnd = (event: DragEndEvent) => {
        const { active, over } = event

        if (!over) return

        const activeId = active.id
        const overId = over.id

        // Find the active task
        const activeTask = tasks.find((t) => t.id.toString() === activeId)
        if (!activeTask) return

        // Are we dropping over another task?
        const overTask = tasks.find((t) => t.id.toString() === overId)

        if (overTask && activeTask.status !== overTask.status) {
            onStatusChange(activeTask.id, overTask.status)
        }
    }

    return (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <div className="flex gap-4 overflow-x-auto pb-4 items-start w-full">
                {COLUMNS.map((col) => (
                    <KanbanColumn
                        key={col.id}
                        id={col.id}
                        title={col.title}
                        color={col.color}
                        tasks={tasks.filter((t) => t.status === col.id)}
                        onOpenEdit={onOpenEdit}
                    />
                ))}
            </div>
        </DndContext>
    )
}
