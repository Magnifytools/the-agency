import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useNavigate } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import TasksPage from "./tasks-page"
const api = vi.hoisted(() => ({ list: vi.fn(), listAll: vi.fn(), empty: vi.fn(), agenda: vi.fn(), canWrite: true, user: {id: 1, role: "admin"} }))
const clock = vi.hoisted(() => ({ today: "2026-10-01" }))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => clock.today }))
vi.mock("@/components/incidents/incident-inbox", () => ({ IncidentInbox: () => <div>Alertas personales</div> }))
vi.mock("@/components/tasks/next-meeting", () => ({ NextMeeting: () => <div>Próxima reunión personal</div> }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: api.user, hasPermission: () => api.canWrite }) }))
vi.mock("@/lib/api", () => ({
  tasksApi: { list: api.list, listAll: api.listAll, agenda: api.agenda },
  clientsApi: { listAll: api.empty }, categoriesApi: { list: api.empty },
  usersApi: { listAll: api.empty }, projectsApi: { listAll: api.empty }, timeEntriesApi: {},
}))
function Back() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Atrás navegador</button> }

describe("tasks URL navigation", () => {
  beforeEach(() => { vi.clearAllMocks(); api.user.role = "admin"; api.canWrite = true; api.agenda.mockResolvedValue({items:[], total:0, page:1, page_size:25}); api.list.mockResolvedValue({items:[],total:0,page:1,page_size:25}); api.listAll.mockResolvedValue([]); api.empty.mockResolvedValue([]) })
  function showAgenda(url: string) {
    const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
    const tree = <QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><TasksPage /><Back /></MemoryRouter></QueryClientProvider>
    return { ...render(tree), tree }
  }
  it("names the task selection controls in the all-tasks table", async () => {
    api.list.mockResolvedValueOnce({ items: [{ id: 8, title: "Preparar informe", status: "pending", priority: "medium", assigned_to: null, scheduled_date: null, estimated_minutes: null, due_date: null }], total: 1, page: 1, page_size: 25 })
    showAgenda("/tasks?view=all")
    expect(await screen.findByRole("checkbox", { name: "Seleccionar tarea Preparar informe" })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Seleccionar todas las tareas visibles" })).toBeInTheDocument()
  })
  it("hides task bulk controls from members without task write permission", async () => {
    api.user.role = "member"
    api.canWrite = false
    api.list.mockResolvedValueOnce({ items: [{ id: 8, title: "Preparar informe", status: "pending", priority: "medium", assigned_to: null, scheduled_date: null, estimated_minutes: null, due_date: null }], total: 1, page: 1, page_size: 25 })

    showAgenda("/tasks?view=all")

    expect(await screen.findByText("Preparar informe")).toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: "Seleccionar tarea Preparar informe" })).not.toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: "Seleccionar todas las tareas visibles" })).not.toBeInTheDocument()
    expect(screen.queryByText("Estado...")).not.toBeInTheDocument()
  })
  it("defaults an administrator to personal work and explicitly switches all cohorts to team", async () => {
    showAgenda("/tasks?view=my_day")
    await waitFor(() => expect(api.agenda).toHaveBeenCalledTimes(4))
    expect(api.agenda.mock.calls.every(([params]) => params.assigned_to === "me")).toBe(true)
    expect(screen.getByText("Alertas personales")).toBeInTheDocument()
    expect(screen.getByText("Próxima reunión personal")).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Ámbito de Hoy"), "team")
    await waitFor(() => expect(api.agenda).toHaveBeenCalledTimes(8))
    expect(api.agenda.mock.calls.slice(4).every(([params]) => params.assigned_to === "all")).toBe(true)
    expect(screen.queryByText("Alertas personales")).not.toBeInTheDocument()
    expect(screen.queryByText("Próxima reunión personal")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", {name:"Atrás navegador"}))
    expect(screen.getByLabelText("Ámbito de Hoy")).toHaveValue("mine")
  })
  it("ignores a team URL for members and always requests their own tasks", async () => {
    api.user.role = "member"
    showAgenda("/tasks?view=my_day&scope=team")
    await waitFor(() => expect(api.agenda).toHaveBeenCalledTimes(4))
    expect(screen.queryByLabelText("Ámbito de Hoy")).not.toBeInTheDocument()
    expect(api.agenda.mock.calls.every(([params]) => params.assigned_to === "me")).toBe(true)
  })
  it("removes the actual QA query on view change and restores it with browser Back", async () => {
    api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    api.listAll.mockResolvedValue([])
    api.empty.mockResolvedValue([])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={["/tasks?qaFilter=overdue"]}><TasksPage /><Back /></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ overdue: true })))
    await userEvent.click(screen.getByRole("button", { name: "Todas" }))
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ overdue: undefined, page: 1 })))
    expect(screen.queryByRole("button", { name: "Limpiar filtros QA" })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Atrás navegador" }))
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ overdue: true })))
    expect(screen.getByRole("button", { name: "Limpiar filtros QA" })).toBeInTheDocument()
  })
  it("renders recurring templates from their own query without ordinary task filters or counts", async () => {
    api.list.mockResolvedValue({ items: [], total: 99, page: 1, page_size: 25 })
    api.listAll.mockResolvedValue([{ id: 8, title: "Revisión semanal", recurrence_pattern: "weekly", recurrence_day: 0, recurrence_paused_at: null, recurrence_summary: { label: "Activa", reason: null, next_dates: ["2026-09-21"] }, client_name: "Acme", assigned_user_name: "Ana", priority: "medium" }])
    showAgenda("/tasks?view=recurring")
    expect(await screen.findByText("1 plantilla recurrente")).toBeInTheDocument()
    expect(screen.queryByPlaceholderText("Buscar tareas...")).not.toBeInTheDocument()
    expect(screen.queryByText(/99 tareas/)).not.toBeInTheDocument()
    expect(screen.getByText("Próximas: 2026-09-21")).toBeInTheDocument()
  })
  it("shows a retryable recurring-template failure instead of an empty state", async () => {
    api.listAll.mockRejectedValueOnce(new Error("offline"))
    showAgenda("/tasks?view=recurring")
    expect(await screen.findByText("No se pudieron cargar las plantillas recurrentes")).toBeInTheDocument()
    expect(screen.getByText("Plantillas no disponibles")).toBeInTheDocument()
    expect(screen.queryByText(/0 plantillas recurrentes/)).not.toBeInTheDocument()
    expect(screen.queryByText("No hay plantillas recurrentes")).not.toBeInTheDocument()
    api.listAll.mockResolvedValueOnce([])
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("No hay plantillas recurrentes")).toBeInTheDocument()
  })
  it("keeps recurring-template actions unavailable without task write permission", async () => {
    api.canWrite = false
    api.listAll.mockResolvedValue([{ id: 8, title: "Revisión semanal", recurrence_pattern: "weekly", recurrence_day: 0, recurrence_paused_at: null, recurrence_summary: { label: "Activa", reason: null, next_dates: [] }, client_name: null, assigned_user_name: null, priority: "medium" }])
    showAgenda("/tasks?view=recurring")
    expect(await screen.findByRole("button", { name: "Pausar" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Editar plantilla Revisión semanal" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Eliminar plantilla Revisión semanal" })).toBeDisabled()
  })
  it("opens the business month and keeps manual month navigation", async () => {
    clock.today = "2026-12-01"
    const view = showAgenda("/tasks?view=calendar")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ due_date_from: "2026-12-01", due_date_to: "2026-12-31" })))
    await screen.findByText(/diciembre 2026/i)
    await userEvent.click(screen.getByRole("button", { name: "Mes siguiente" }))
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ due_date_from: "2027-01-01", due_date_to: "2027-01-31" })))
    clock.today = "2027-02-01"
    view.rerender(view.tree)
    expect(screen.getByText(/enero 2027/i)).toBeInTheDocument()
  })
})
