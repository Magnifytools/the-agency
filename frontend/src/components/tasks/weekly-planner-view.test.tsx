import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { Task } from "@/lib/types"
import { WeeklyPlannerView } from "./weekly-planner-view"

Object.defineProperty(window, "matchMedia", { writable: true, value: () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }) })

const task = { id: 7, title: "Plan semanal", status: "pending", priority: "medium", scheduled_date: null, due_date: null, client_id: null, category_id: null, assigned_to: null, project_id: null, phase_id: null, is_inbox: false, depends_on: null, created_by: null, description: null, estimated_minutes: null, actual_minutes: null, start_date: null, waiting_for: null, follow_up_date: null, is_recurring: false, recurrence_pattern: null, recurrence_day: null, recurrence_end_date: null, recurring_parent_id: null, unit_cost: null, invoiced_at: null, link_url: null, created_at: "", updated_at: "", client_name: null, category_name: null, assigned_user_name: null, project_name: null, phase_name: null, dependency_title: null, created_by_name: null, recurring_parent_title: null, checklist_count: 0 } as Task

describe("WeeklyPlannerView permissions", () => {
  it("keeps reader cards inert and writer cards draggable", () => {
    const props = { tasks: [task], weekOffset: 0, onWeekOffsetChange: vi.fn(), onScheduleChange: vi.fn(), onOpenEdit: vi.fn() }
    const { rerender } = render(<WeeklyPlannerView {...props} canWrite={false} />)
    expect(screen.getByRole("button", { name: "Ver tarea Plan semanal" })).toBeInTheDocument()
    expect(screen.getByText("Plan semanal").closest("[role='button']")).toBeNull()
    rerender(<WeeklyPlannerView {...props} canWrite />)
    expect(screen.getByRole("button", { name: "Editar tarea Plan semanal" })).toBeInTheDocument()
    expect(screen.getByText("Plan semanal").closest("[role='button']")).not.toBeNull()
  })
})
