import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useNavigate } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import TasksPage from "./tasks-page"
const api = vi.hoisted(() => ({ list: vi.fn(), listAll: vi.fn(), empty: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1, role: "admin" } }) }))
vi.mock("@/lib/api", () => ({
  tasksApi: { list: api.list, listAll: api.listAll },
  clientsApi: { listAll: api.empty }, categoriesApi: { list: api.empty },
  usersApi: { listAll: api.empty }, projectsApi: { listAll: api.empty }, timeEntriesApi: {},
}))
function Back() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Atrás navegador</button> }

describe("tasks URL navigation", () => {
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
