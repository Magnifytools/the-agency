import { useMemo } from "react"
import { Button } from "@/components/ui/button"
import { ChevronLeft, ChevronRight } from "lucide-react"
import type { Task } from "@/lib/types"

const DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
const MONTHS = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

const STATUS_COLORS: Record<string, string> = {
  backlog: "bg-gray-500 text-white",
  pending: "bg-yellow-500 text-white",
  in_progress: "bg-blue-500 text-white",
  waiting: "bg-orange-500 text-white",
  in_review: "bg-purple-500 text-white",
  completed: "bg-green-500 text-white line-through opacity-60",
}

interface TaskCalendarViewProps {
  tasks: Task[]
  year: number
  month: number
  onPrev: () => void
  onNext: () => void
  onOpenEdit: (task: Task) => void
}

export function TaskCalendarView({ tasks, year, month, onPrev, onNext, onOpenEdit }: TaskCalendarViewProps) {
  const days = useMemo(() => {
    const firstDay = new Date(year, month, 1)
    // Monday-based: 0=Mon ... 6=Sun
    const startOffset = (firstDay.getDay() + 6) % 7
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const cells: (number | null)[] = []
    for (let i = 0; i < startOffset; i++) cells.push(null)
    for (let d = 1; d <= daysInMonth; d++) cells.push(d)
    // Pad to complete last row
    while (cells.length % 7 !== 0) cells.push(null)
    return cells
  }, [year, month])

  const tasksByDay = useMemo(() => {
    const map: Record<number, Task[]> = {}
    for (const t of tasks) {
      if (!t.due_date) continue
      const d = new Date(t.due_date)
      if (d.getFullYear() === year && d.getMonth() === month) {
        const day = d.getDate()
        if (!map[day]) map[day] = []
        map[day].push(t)
      }
    }
    return map
  }, [tasks, year, month])

  const today = new Date()
  const isToday = (d: number) => today.getFullYear() === year && today.getMonth() === month && today.getDate() === d

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">{MONTHS[month]} {year}</h3>
        <div className="flex gap-1">
          <Button variant="outline" size="icon" aria-label="Mes anterior" className="h-8 w-8" onClick={onPrev}><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" size="icon" aria-label="Mes siguiente" className="h-8 w-8" onClick={onNext}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden border border-border">
        {/* Day headers */}
        {DAYS.map(d => (
          <div key={d} className="bg-muted/50 text-center text-xs font-medium text-muted-foreground py-2">{d}</div>
        ))}

        {/* Cells */}
        {days.map((d, i) => (
          <div
            key={i}
            className={`min-h-[90px] bg-background p-1.5 ${!d ? "bg-muted/20" : ""}`}
          >
            {d && (
              <>
                <span className={`text-xs font-medium mb-1 block w-5 h-5 flex items-center justify-center rounded-full ${isToday(d) ? "bg-brand text-primary-foreground" : "text-muted-foreground"}`}>
                  {d}
                </span>
                <div className="space-y-0.5">
                  {(tasksByDay[d] || []).slice(0, 3).map(t => (
                    <button
                      key={t.id}
                      onClick={() => onOpenEdit(t)}
                      className={`w-full text-left text-[10px] rounded px-1 py-0.5 truncate leading-tight ${STATUS_COLORS[t.status] || "bg-secondary"} hover:opacity-80 transition-opacity`}
                    >
                      {t.title}
                    </button>
                  ))}
                  {(tasksByDay[d] || []).length > 3 && (
                    <span className="text-[10px] text-muted-foreground pl-1">+{(tasksByDay[d] || []).length - 3} más</span>
                  )}
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Empty state when no tasks have a due_date in this month */}
      {Object.keys(tasksByDay).length === 0 && (
        <p className="text-center text-sm text-muted-foreground py-4">
          No hay tareas con fecha en {MONTHS[month]}. Asigna una fecha de entrega a tus tareas para verlas aquí.
        </p>
      )}
    </div>
  )
}
