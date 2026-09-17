import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import ProjectsPage from "./projects-page"

const api = vi.hoisted(() => ({ list: vi.fn(), templates: vi.fn(), clients: vi.fn(), create: vi.fn() }))
vi.mock("@/lib/api", () => ({ projectsApi: { list: api.list, templates: api.templates, create: api.create }, clientsApi: { listAll: api.clients } }))
function Location() { return <output data-testid="location">{useLocation().pathname + useLocation().search}</output> }
function setup(url = "/projects") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><ProjectsPage /><Location /></MemoryRouter></QueryClientProvider>)
}

describe("projects filter navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    api.templates.mockResolvedValue({})
    api.clients.mockResolvedValue([{id: 17, name: "Cliente de prueba"}])
    api.create.mockResolvedValue({id: 91})
  })
  it("restores URL filters and resets pagination when the type changes", async () => {
    setup("/projects?status=active&type=recurring&period=month&page=2")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ status: "active", is_recurring: true, page: 2, period_from: expect.any(String), period_to: expect.any(String) })))
    await userEvent.selectOptions(screen.getByLabelText("Tipo de proyecto"), "one_time")
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ is_recurring: false, page: 1 })))
    expect(screen.getByTestId("location").textContent).toBe("/projects?status=active&type=one_time&period=month")
  })
  it("offers retry on failure without claiming the project list is empty", async () => {
    api.list.mockRejectedValueOnce(new Error("offline"))
    setup()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar")
    expect(screen.queryByText("Sin proyectos todavía")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await screen.findByText("Sin proyectos todavía")
  })
  it("creates with only name and client, preserves the draft on error and opens the created project", async () => {
    api.create.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({id: 91})
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Entrega nueva")
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    expect(screen.getByLabelText("Entrega prevista (opcional)")).not.toBeRequired()
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await screen.findByRole("alert")
    expect(screen.getByLabelText("Nombre *")).toHaveValue("Entrega nueva")
    expect(screen.getByLabelText("Cliente *")).toHaveValue("17")
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/projects/91?created=1"))
    expect(api.create).toHaveBeenLastCalledWith(expect.objectContaining({name: "Entrega nueva", client_id: 17, is_recurring: false, start_date: undefined, target_end_date: undefined, monthly_fee: undefined, budget_amount: undefined}))
  })
  it("separates monthly pricing and total budget without requiring guessed hours", async () => {
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Servicio mensual")
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    await userEvent.selectOptions(screen.getByLabelText("Tipo de trabajo"), "recurring")
    expect(screen.getByLabelText("Horas acordadas por mes (opcional)")).not.toBeRequired()
    await userEvent.click(screen.getByText("Alcance, fechas y condiciones económicas"))
    await userEvent.selectOptions(screen.getByLabelText("Modelo de precio"), "monthly")
    await userEvent.type(screen.getByLabelText("Tarifa mensual (EUR)"), "450")
    await userEvent.type(screen.getByLabelText("Presupuesto total (EUR, opcional)"), "5400")
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({is_recurring: true, monthly_fee: 450, budget_amount: 5400, monthly_hours_budget: undefined})))
  })
  it("offers template and document options within the single new-project flow", async () => {
    setup()
    expect(screen.queryByRole("button", {name: "Importar PDF"})).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.click(screen.getByText("Partir de una plantilla o un documento"))
    await userEvent.click(screen.getByRole("button", {name: "Usar plantilla"}))
    expect(screen.getByRole("dialog", {name: "Crear desde plantilla"})).toBeInTheDocument()
  })

})
