import { useState, useMemo } from "react"
import type { Project } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { ZoomIn, ZoomOut } from "lucide-react"
import { calculateConfig, type ZoomLevel } from "./gantt-utils"
import { GanttHeader } from "./gantt-header"
import { GanttRow } from "./gantt-row"
import { GanttTodayMarker } from "./gantt-today-marker"

interface PhaseTaskData {
  phase: {
    id: number
    name: string
    order_index: number
    status: string
    phase_type?: string
    start_date?: string | null
    due_date?: string | null
  }
  tasks: {
    id: number
    title: string
    status: string
    priority?: string
    start_date?: string | null
    due_date?: string | null
    estimated_minutes?: number | null
    assigned_to?: string | null
  }[]
}

interface TasksData {
  project_id: number
  project_name: string
  phases: PhaseTaskData[]
  unassigned_tasks: PhaseTaskData["tasks"]
}

interface GanttChartProps {
  project: Project
  tasksData: TasksData
}

const ZOOM_LABELS: Record<ZoomLevel, string> = {
  week: "Sem",
  month: "Mes",
  quarter: "Trim",
}

const ZOOM_ORDER: ZoomLevel[] = ["week", "month", "quarter"]

function parseDate(d: string | null | undefined): Date | null {
  if (!d) return null
  const parsed = new Date(d)
  return isNaN(parsed.getTime()) ? null : parsed
}

export function GanttChart({ project, tasksData }: GanttChartProps) {
  const [zoom, setZoom] = useState<ZoomLevel>("month")
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())

  const projectStart = parseDate(project.start_date)
  const projectEnd = parseDate(project.target_end_date)

  const config = useMemo(
    () => calculateConfig(projectStart, projectEnd, zoom),
    [projectStart?.getTime(), projectEnd?.getTime(), zoom]
  )

  const toggleCollapse = (phaseId: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(phaseId)) next.delete(phaseId)
      else next.add(phaseId)
      return next
    })
  }

  const zoomIn = () => {
    const idx = ZOOM_ORDER.indexOf(zoom)
    if (idx > 0) setZoom(ZOOM_ORDER[idx - 1])
  }

  const zoomOut = () => {
    const idx = ZOOM_ORDER.indexOf(zoom)
    if (idx < ZOOM_ORDER.length - 1) setZoom(ZOOM_ORDER[idx + 1])
  }

  if (!projectStart && !projectEnd) {
    return (
      <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
        Establece las fechas del proyecto para ver el diagrama Gantt.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          {ZOOM_ORDER.map((z) => (
            <Button
              key={z}
              variant={zoom === z ? "default" : "outline"}
              size="sm"
              onClick={() => setZoom(z)}
              className="text-xs h-7 px-2"
            >
              {ZOOM_LABELS[z]}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={zoomIn} className="h-7 w-7 p-0" disabled={zoom === "week"}>
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={zoomOut} className="h-7 w-7 p-0" disabled={zoom === "quarter"}>
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Chart */}
      <div className="relative rounded-xl border border-border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <div style={{ minWidth: 220 + config.totalWidth }}>
            {/* Header */}
            <div className="flex">
              <div
                className="sticky left-0 z-30 bg-card border-r border-border flex items-end px-3 pb-1"
                style={{ width: 220, minWidth: 220 }}
              >
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Fases / Tareas
                </span>
              </div>
              <div className="flex-1">
                <GanttHeader config={config} />
              </div>
            </div>

            {/* Today marker */}
            <GanttTodayMarker config={config} />

            {/* Rows */}
            <div className="relative">
              {tasksData.phases.map((phaseData) => {
                const phase = phaseData.phase
                const isCollapsed = collapsed.has(phase.id)
                const phaseStart = parseDate(phase.start_date)
                const phaseEnd = parseDate(phase.due_date)

                return (
                  <div key={phase.id}>
                    {/* Phase row */}
                    <div
                      className="cursor-pointer"
                      onClick={() => toggleCollapse(phase.id)}
                    >
                      <GanttRow
                        label={`${isCollapsed ? "▶" : "▼"} ${phase.name}`}
                        startDate={phaseStart}
                        endDate={phaseEnd}
                        status={phase.status}
                        type={phase.phase_type === "milestone" ? "milestone" : "phase"}
                        phaseType={(phase.phase_type as "sprint" | "milestone" | "standard") || "standard"}
                        config={config}
                      />
                    </div>

                    {/* Task rows */}
                    {!isCollapsed &&
                      phaseData.tasks.map((task) => (
                        <GanttRow
                          key={task.id}
                          label={task.title}
                          startDate={parseDate(task.start_date)}
                          endDate={parseDate(task.due_date)}
                          status={task.status}
                          type="task"
                          config={config}
                          isChild
                          assignedTo={task.assigned_to}
                        />
                      ))}
                  </div>
                )
              })}

              {/* Unassigned tasks */}
              {tasksData.unassigned_tasks.length > 0 && (
                <div>
                  <GanttRow
                    label="Sin fase"
                    startDate={null}
                    endDate={null}
                    status="pending"
                    type="phase"
                    config={config}
                  />
                  {tasksData.unassigned_tasks.map((task) => (
                    <GanttRow
                      key={task.id}
                      label={task.title}
                      startDate={parseDate(task.start_date)}
                      endDate={parseDate(task.due_date)}
                      status={task.status}
                      type="task"
                      config={config}
                      isChild
                      assignedTo={task.assigned_to}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <div className="w-6 h-2 rounded-sm bg-[#6B7280] opacity-70" />
          <span>Pendiente</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-6 h-2 rounded-sm bg-[#FEE630] opacity-70" />
          <span>En curso</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-6 h-2 rounded-sm bg-[#22C55E] opacity-70" />
          <span>Completado</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full border-2 border-[#6B7280]" />
          <span>Solo fecha límite</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rotate-45 bg-[#FEE630]" />
          <span>Milestone</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-0 h-3 border-l-2 border-dashed border-brand/60" />
          <span>Hoy</span>
        </div>
      </div>
    </div>
  )
}
