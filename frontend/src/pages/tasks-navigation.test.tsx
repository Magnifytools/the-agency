import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useNavigate } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import TasksPage from "./tasks-page"
const api = vi.hoisted(() => ({ list: vi.fn(), listAll: vi.fn(), empty: vi.fn(), agenda: vi.fn(), user: {id: 1, role: "admin"} }))
vi.mock("@/components/incidents/incident-inbox", () => ({ IncidentInbox: () => <div>Alertas personales</div> }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: api.user }) }))
vi.mock("@/lib/api", () => ({
  tasksApi: { list: api.list, listAll: api.listAll, agenda: api.agenda },
  clientsApi: { listAll: api.empty }, categoriesApi: { list: api.empty },
  usersApi: { listAll: api.empty }, projectsApi: { listAll: api.empty }, timeEntriesApi: {},
}))
function Back() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Atrás navegador</button> }

describe("tasks URL navigation", () => {
  beforeEach(() => { vi.clearAllMocks(); api.user.role = "admin"; api.agenda.mockResolvedValue({items:[], total:0, page:1, page_size:25}); api.list.mockResolvedValue({items:[],total:0,page:1,page_size:25}); api.listAll.mockResolvedValue([]); api.empty.mockResolvedValue([]) })
  function showAgenda(url: string) {
    const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><TasksPage /><Back /></MemoryRouter></QueryClientProvider>)
  }
  it("defaults an administrator to personal work and explicitly switches all cohorts to team", async () => {
    showAgenda("/tasks?view=my_day")
    await waitFor(() => expect(api.agenda).toHaveBeenCalledTimes(4))
    expect(api.agenda.mock.calls.every(([params]) => params.assigned_to === "me")).toBe(true)
    expect(screen.getByText("Alertas personales")).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Ámbito de Hoy"), "team")
    await waitFor(() => expect(api.agenda).toHaveBeenCalledTimes(8))
    expect(api.agenda.mock.calls.slice(4).every(([params]) => params.assigned_to === undefined)).toBe(true)
    expect(screen.queryByText("Alertas personales")).not.toBeInTheDocument()
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
})
