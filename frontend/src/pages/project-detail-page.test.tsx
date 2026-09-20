import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { projectKeys } from "@/lib/query-keys"
import ProjectDetailPage from "./project-detail-page"

const api = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), tasks: vi.fn(), monthlyCycle: vi.fn(), burndown: vi.fn(), today: "2026-09-18", canReadTasks: true }))

vi.mock("@/lib/api", () => ({
  projectsApi: {
    get: api.get,
    tasks: api.tasks,
    monthlyCycle: api.monthlyCycle,
    burndown: api.burndown,
    update: api.update,
    updatePhase: vi.fn(),
    createTask: vi.fn(),
  },
  tasksApi: { update: vi.fn() },
  usersApi: { listAll: vi.fn().mockResolvedValue([]) },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string) => module !== "tasks" || api.canReadTasks }),
}))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => api.today }))
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
  beforeEach(() => { vi.clearAllMocks(); api.monthlyCycle.mockResolvedValue({ project_id: 42, month: "2026-09", period_start: "2026-09-01", period_end: "2026-10-01", planned_count: 0, completed_in_month_count: 0, total_minutes: 0, used_hours: 0, budget_hours: null, remaining_hours: null, tasks: [] }) })

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

it("starts the edit form from the next cached project rather than the previous draft", async () => {
  const first = { ...staleProject, is_recurring: false, owner_id: 7, owner_name: "Responsable A", requires_task_review: true }
  const second = { ...staleProject, id: 43, name: "Proyecto siguiente", is_recurring: false, owner_id: 8, owner_name: "Responsable B", requires_task_review: false }
  api.canReadTasks = true
  api.tasks.mockResolvedValue({ phases: [], unassigned_tasks: [] })
  api.get.mockImplementation((id: number) => Promise.resolve(id === 42 ? first : second))
  api.update.mockResolvedValue(second)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(projectKeys.detail(42), first)
  client.setQueryData(projectKeys.detail(43), second)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}>
    <Link to="/projects/43">Ir al siguiente proyecto</Link>
    <Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>)

  await userEvent.click(await screen.findByRole("button", { name: "Editar" }))
  expect(screen.getByLabelText("Nombre")).toHaveValue(first.name)
  expect(screen.getByRole("checkbox", { name: /Revisar tareas antes/ })).toBeChecked()
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Borrador del primero" } })
  await userEvent.click(screen.getByRole("button", { name: "Cancelar" }))
  await userEvent.click(screen.getByRole("link", { name: "Ir al siguiente proyecto" }))
  await screen.findByRole("heading", { name: second.name })
  await userEvent.click(screen.getByRole("button", { name: "Editar" }))

  expect(screen.getByLabelText("Nombre")).toHaveValue(second.name)
  expect(screen.getByLabelText("Responsable del proyecto")).toHaveValue("8")
  expect(screen.getByRole("checkbox", { name: /Revisar tareas antes/ })).not.toBeChecked()
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Guardar/ }))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith(43, expect.objectContaining({ name: second.name, requires_task_review: false })))
  expect(api.update.mock.calls.at(-1)?.[1]).not.toHaveProperty("owner_id")
})

describe("recurring project monthly cycle", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.today = "2026-09-18"
    api.canReadTasks = true
    api.get.mockResolvedValue({
      ...staleProject,
      id: 42,
      name: "Retainer SEO",
      budget_hours: 10,
      effective_monthly_hours_budget: 10,
      hours_used_month: 1.5,
    })
    api.tasks.mockResolvedValue({ phases: [], unassigned_tasks: [] })
    api.monthlyCycle.mockImplementation((_id: number, month: string) => Promise.resolve({
      project_id: 42,
      month,
      period_start: `${month}-01`,
      period_end: "2026-10-01",
      planned_count: 1,
      completed_in_month_count: 2,
      total_minutes: 90,
      used_hours: 1.5,
      budget_hours: 10,
      remaining_hours: 8.5,
      tasks: [{ id: 8, title: "Informe mensual", status: "completed", scheduled_date: `${month}-10`, completed_at: `${month}-15T09:00:00` }],
    }))
  })

  it("shows the current civil month and keeps history secondary", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText("Ciclo de septiembre 2026")).toBeInTheDocument()
    expect((await screen.findByText("Planificadas en el mes")).nextSibling).toHaveTextContent("1")
    expect(screen.getByText("Finalizadas en el mes").nextSibling).toHaveTextContent("2")
    expect(screen.getByText(/Finalizadas en el mes sólo cuenta/)).toBeInTheDocument()
    expect(screen.getByText("Informe mensual")).toBeInTheDocument()
    expect(screen.getByText("Horas restantes")).toBeInTheDocument()
    expect(screen.getByText("Este mes")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Informe mensual" })).toHaveAttribute("href", "/tasks?task=8")
    expect(screen.queryByLabelText("Mes del ciclo")).not.toBeVisible()

    await userEvent.click(screen.getByText("Consultar otro mes"))
    fireEvent.change(screen.getByLabelText("Mes del ciclo"), { target: { value: "2026-08" } })
    await waitFor(() => expect(api.monthlyCycle).toHaveBeenCalledWith(42, "2026-08"))
    expect(await screen.findByText("Diferencia con presupuesto actual")).toBeInTheDocument()
    expect(screen.getByText("Presupuesto actual de referencia")).toBeInTheDocument()
  })

  it("keeps recurrence templates out of operational work with a global edit path", async () => {
    api.tasks.mockResolvedValue({
      phases: [],
      unassigned_tasks: [{
        id: 48, title: "Revisión quincenal", status: "pending", priority: "medium",
        assigned_to: null, assigned_user_name: null, scheduled_date: null,
        start_date: null, due_date: null, estimated_minutes: null,
        waiting_for: null, follow_up_date: null, is_recurring: true,
      }],
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText("Aún no hay tareas. Añade la primera cuando tengas claro el próximo paso.")).toBeInTheDocument()
    expect(screen.queryByText("Revisión quincenal")).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ver plantillas recurrentes" })).toHaveAttribute("href", "/tasks?view=recurring")
  })

  it("keeps task links permission-aware and retries a failed cycle", async () => {
    api.canReadTasks = false
    api.monthlyCycle.mockRejectedValueOnce(new Error("network"))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar este ciclo")
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("Informe mensual")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Informe mensual" })).not.toBeInTheDocument()
    expect(api.monthlyCycle).toHaveBeenCalledTimes(2)
  })

  it("advances the default cycle when the business month changes", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText("Ciclo de septiembre 2026")).toBeInTheDocument()

    api.today = "2026-10-01"
    view.rerender(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText("Ciclo de octubre 2026")).toBeInTheDocument()
    await waitFor(() => expect(api.monthlyCycle).toHaveBeenCalledWith(42, "2026-10"))
  })
})


describe("project progress recovery", () => {
  const points = { total_tasks: 2, points: [{ date: "2026-09-19", remaining: 2, ideal: 2 }, { date: "2026-09-20", remaining: 1, ideal: 0 }] }
  async function openProgress() {
    api.get.mockResolvedValue({ ...staleProject, is_recurring: false })
    api.tasks.mockResolvedValue({ phases: [], unassigned_tasks: [] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/42"]}><Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
    await screen.findByRole("heading", { name: "Proyecto deshecho" })
    await userEvent.click(screen.getByText(/Plazos, horas y progreso/))
    return client
  }

  beforeEach(() => { vi.clearAllMocks(); api.canReadTasks = true })

  it("distinguishes failure from empty progress and retries", async () => {
    api.burndown.mockRejectedValueOnce(responseError(503)).mockResolvedValueOnce({ total_tasks: 0, points: [] })
    await openProgress()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo actualizar el progreso de tareas")
    expect(screen.queryByText("Añade tareas al proyecto para ver el burndown.")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar progreso" }))
    expect(await screen.findByText("Añade tareas al proyecto para ver el burndown.")).toBeInTheDocument()
  })

  it("keeps previous chart hidden after denial and later errors until fresh success", async () => {
    api.burndown.mockResolvedValueOnce(points)
    const client = await openProgress()
    await screen.findByText("Burndown de tareas")
    api.burndown.mockRejectedValueOnce(responseError(403)).mockRejectedValueOnce(responseError(503))
    await act(async () => { await client.invalidateQueries({ queryKey: projectKeys.burndown(42) }) })
    await screen.findByText("No se pudo actualizar el progreso de tareas.")
    expect(screen.queryByText("Burndown de tareas")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar progreso" }))
    await waitFor(() => expect(api.burndown).toHaveBeenCalledTimes(3))
    expect(screen.queryByText("Burndown de tareas")).not.toBeInTheDocument()
    let resolve!: (value: typeof points) => void
    api.burndown.mockImplementationOnce(() => new Promise(r => { resolve = r }))
    await userEvent.click(screen.getByRole("button", { name: "Reintentar progreso" }))
    expect(screen.queryByText("Burndown de tareas")).not.toBeInTheDocument()
    await act(async () => { resolve(points) })
    expect(await screen.findByText("Burndown de tareas")).toBeInTheDocument()
    expect(screen.getByText(/finalizaciones sin fecha registrada/)).toBeInTheDocument()
  })
})
