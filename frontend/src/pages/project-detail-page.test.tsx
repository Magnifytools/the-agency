import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { projectKeys } from "@/lib/query-keys"
import ProjectDetailPage from "./project-detail-page"

const api = vi.hoisted(() => ({ get: vi.fn(), tasks: vi.fn() }))

vi.mock("@/lib/api", () => ({
  projectsApi: {
    get: api.get,
    tasks: api.tasks,
    burndown: vi.fn(),
    update: vi.fn(),
    updatePhase: vi.fn(),
    createTask: vi.fn(),
  },
  tasksApi: { update: vi.fn() },
  usersApi: { listAll: vi.fn().mockResolvedValue([]) },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: () => true }),
}))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => "2026-09-18" }))
vi.mock("@/components/projects/project-work-summary", () => ({ ProjectWorkSummary: () => null }))
vi.mock("@/components/projects/project-task-list", () => ({ ProjectTaskList: () => <div>Lista de tareas</div> }))
vi.mock("@/components/projects/project-phase-kanban", () => ({ ProjectPhaseKanban: () => null }))
vi.mock("@/components/projects/evidence-list", () => ({ EvidenceList: () => null }))
vi.mock("@/components/projects/project-billing-tab", () => ({ ProjectBillingTab: () => null }))
vi.mock("@/components/projects/project-ideas-tab", () => ({ ProjectIdeasTab: () => null }))
vi.mock("@/components/gantt/gantt-chart", () => ({ GanttChart: () => null }))
vi.mock("@/components/tasks/task-panel", () => ({ TaskPanel: () => null }))
vi.mock("@/components/timer/time-log-dialog", () => ({ TimeLogDialog: () => null }))
vi.mock("recharts", () => ({
  LineChart: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => children,
}))

const staleProject = {
  id: 42,
  name: "Proyecto deshecho",
  client_id: 7,
  client_name: "Cliente",
  owner_name: null,
  status: "active",
  is_recurring: true,
  task_count: 0,
  phases: [],
  start_date: null,
  target_end_date: null,
}

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>
}

function responseError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } })
}

function setup(error: unknown) {
  api.get.mockRejectedValue(error)
  api.tasks.mockResolvedValue({ phases: [], unassigned_tasks: [] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(projectKeys.detail(42), staleProject)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/42"]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/projects" element={<><div>Listado de proyectos</div><Location /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("project detail stale data after access changes", () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    [404, "Este proyecto ya no existe"],
    [410, "Este proyecto ya no existe"],
    [403, "Ya no tienes acceso a este proyecto"],
  ])("hides stale controls after HTTP %s", async (status, message) => {
    setup(responseError(status))

    expect(await screen.findByRole("heading", { name: message })).toBeInTheDocument()
    expect(screen.queryByText("Proyecto deshecho")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Añadir tarea" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "Volver a proyectos" }))
    expect(await screen.findByTestId("location")).toHaveTextContent("/projects")
  })

  it("keeps the last project and retry action for a transient failure", async () => {
    setup(responseError(503))

    expect(await screen.findByRole("alert")).toHaveTextContent("Se muestran los últimos datos recibidos")
    expect(screen.getByRole("heading", { name: "Proyecto deshecho" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Editar" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Añadir tarea" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument()
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(42))
  })
})
