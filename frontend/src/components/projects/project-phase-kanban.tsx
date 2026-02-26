import { useState } from "react"
import {
  DndContext,
  DragOverlay,
  closestCenter,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core"
import { useSortable, SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { GripVertical } from "lucide-react"

interface PhaseData {
  phase: {
    id: number
    name: string
    order_index: number
    status: string
    start_date?: string | null
    due_date?: string | null
  }
  tasks: { id: number; title: string; status: string }[]
}

interface ProjectPhaseKanbanProps {
  phases: PhaseData[]
  onPhaseStatusChange: (phaseId: number, newStatus: string) => void
}

const COLUMNS: { status: string; label: string; color: string }[] = [
  { status: "pending", label: "Pendiente", color: "text-muted-foreground" },
  { status: "in_progress", label: "En curso", color: "text-brand" },
  { status: "completed", label: "Completada", color: "text-success" },
]

function PhaseCard({ phase, taskCount }: { phase: PhaseData["phase"]; taskCount: number }) {
  const formatDate = (d: string | null | undefined) =>
    d ? new Date(d).toLocaleDateString("es-ES", { day: "numeric", month: "short" }) : ""

  return (
    <Card className="cursor-grab active:cursor-grabbing hover:ring-1 hover:ring-brand/20 transition-all">
      <CardContent className="p-3">
        <div className="flex items-start gap-2">
          <GripVertical className="h-4 w-4 text-muted-foreground/40 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{phase.name}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-muted-foreground">{taskCount} tareas</span>
              {phase.due_date && (
                <span className="text-xs text-muted-foreground">
                  · {formatDate(phase.due_date)}
                </span>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function SortablePhaseCard({ phase, taskCount }: { phase: PhaseData["phase"]; taskCount: number }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `phase-${phase.id}`,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <PhaseCard phase={phase} taskCount={taskCount} />
    </div>
  )
}

export function ProjectPhaseKanban({ phases, onPhaseStatusChange }: ProjectPhaseKanbanProps) {
  const [activePhase, setActivePhase] = useState<PhaseData | null>(null)

  const phasesByStatus = COLUMNS.reduce(
    (acc, col) => {
      acc[col.status] = phases.filter((p) => p.phase.status === col.status)
      return acc
    },
    {} as Record<string, PhaseData[]>
  )

  const handleDragStart = (event: DragStartEvent) => {
    const phaseId = Number(String(event.active.id).replace("phase-", ""))
    const found = phases.find((p) => p.phase.id === phaseId)
    setActivePhase(found || null)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActivePhase(null)
    const { active, over } = event
    if (!over) return

    const phaseId = Number(String(active.id).replace("phase-", ""))
    const overId = String(over.id)

    // Check if dropped on a column
    const targetColumn = COLUMNS.find((col) => col.status === overId)
    if (targetColumn) {
      const currentPhase = phases.find((p) => p.phase.id === phaseId)
      if (currentPhase && currentPhase.phase.status !== targetColumn.status) {
        onPhaseStatusChange(phaseId, targetColumn.status)
      }
      return
    }

    // Check if dropped on another phase card — find that phase's column
    const targetPhaseId = Number(overId.replace("phase-", ""))
    const targetPhase = phases.find((p) => p.phase.id === targetPhaseId)
    if (targetPhase) {
      const currentPhase = phases.find((p) => p.phase.id === phaseId)
      if (currentPhase && currentPhase.phase.status !== targetPhase.phase.status) {
        onPhaseStatusChange(phaseId, targetPhase.phase.status)
      }
    }
  }

  return (
    <DndContext
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-3 gap-4">
        {COLUMNS.map((col) => {
          const columnPhases = phasesByStatus[col.status] || []
          return (
            <div key={col.status} className="space-y-3">
              <div className="flex items-center gap-2">
                <h3 className={`text-sm font-semibold ${col.color}`}>{col.label}</h3>
                <Badge variant="secondary" className="text-xs">{columnPhases.length}</Badge>
              </div>
              <div
                className="min-h-[120px] space-y-2 p-2 rounded-xl border border-dashed border-border/50 bg-card/30"
                id={col.status}
              >
                <SortableContext
                  items={columnPhases.map((p) => `phase-${p.phase.id}`)}
                  strategy={verticalListSortingStrategy}
                >
                  {columnPhases.map((phaseData) => (
                    <SortablePhaseCard
                      key={phaseData.phase.id}
                      phase={phaseData.phase}
                      taskCount={phaseData.tasks.length}
                    />
                  ))}
                </SortableContext>
                {columnPhases.length === 0 && (
                  <p className="text-xs text-muted-foreground/50 text-center py-6">
                    Arrastra fases aquí
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <DragOverlay>
        {activePhase && (
          <div className="w-[280px]">
            <PhaseCard phase={activePhase.phase} taskCount={activePhase.tasks.length} />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  )
}
