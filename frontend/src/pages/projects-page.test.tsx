import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import ProjectsPage from "./projects-page"

const api = vi.hoisted(() => ({ list: vi.fn(), templates: vi.fn(), clients: vi.fn() }))
vi.mock("@/lib/api", () => ({ projectsApi: { list: api.list, templates: api.templates }, clientsApi: { listAll: api.clients } }))
function Location() { return <output data-testid="location">{useLocation().search}</output> }
function setup(url = "/projects") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><ProjectsPage /><Location /></MemoryRouter></QueryClientProvider>)
}

describe("projects filter navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    api.templates.mockResolvedValue({})
    api.clients.mockResolvedValue([])
  })
  it("restores URL filters and resets pagination when the type changes", async () => {
    setup("/projects?status=active&type=recurring&period=month&page=2")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ status: "active", is_recurring: true, page: 2, period_from: expect.any(String), period_to: expect.any(String) })))
    await userEvent.selectOptions(screen.getByLabelText("Tipo de proyecto"), "one_time")
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ is_recurring: false, page: 1 })))
    expect(screen.getByTestId("location").textContent).toBe("?status=active&type=one_time&period=month")
  })
  it("offers retry on failure without claiming the project list is empty", async () => {
    api.list.mockRejectedValueOnce(new Error("offline"))
    setup()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar")
    expect(screen.queryByText("Sin proyectos todavía")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await screen.findByText("Sin proyectos todavía")
  })
})
