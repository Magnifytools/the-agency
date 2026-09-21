import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import ProjectsPage from "./projects-page"

const api = vi.hoisted(() => ({ list: vi.fn(), unassignedCount: vi.fn(), templates: vi.fn(), clients: vi.fn(), users: vi.fn(), create: vi.fn(), createFromTemplate: vi.fn(), extractFromPdf: vi.fn(), extractFromText: vi.fn() }))
const auth = vi.hoisted(() => ({ canWrite: true }))
vi.mock("@/lib/api", () => ({
  projectsApi: { list: api.list, unassignedCount: api.unassignedCount, templates: api.templates, create: api.create, createFromTemplate: api.createFromTemplate, extractFromPdf: api.extractFromPdf, extractFromText: api.extractFromText },
  clientsApi: { listAll: api.clients },
  usersApi: { listAll: api.users },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: () => auth.canWrite }),
}))
function Location() { return <output data-testid="location">{useLocation().pathname + useLocation().search}</output> }
function setup(url = "/projects") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><ProjectsPage /><Location /></MemoryRouter></QueryClientProvider>)
}

describe("projects filter navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.canWrite = true
    api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    api.unassignedCount.mockResolvedValue(0)
    api.templates.mockResolvedValue({})
    api.clients.mockResolvedValue([{id: 17, name: "Cliente de prueba"}])
    api.users.mockResolvedValue([{id: 8, full_name: "Persona activa", is_active: true}, {id: 9, full_name: "Persona inactiva", is_active: false}])
    api.create.mockResolvedValue({id: 91, client_id: 17})
    api.createFromTemplate.mockResolvedValue({id: 92, client_id: 17})
    api.extractFromPdf.mockResolvedValue({name: "Extraído"})
    api.extractFromText.mockResolvedValue({name: "Extraído"})
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
  it("uses the server lifecycle cohort for Archivo and keeps its status filter scoped", async () => {
    setup("/projects?view=archive")
    expect(screen.getByRole("button", { name: "Archivo" })).toHaveAttribute("aria-pressed", "true")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ lifecycle: "archive", page: 1, page_size: 25 })))
    expect(await screen.findByText("El archivo está vacío")).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Estado del proyecto"), "cancelled")
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle: "archive", status: "cancelled" })))
    await userEvent.click(screen.getByRole("button", { name: "Cartera" }))
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle: "portfolio" })))
    expect(screen.getByRole("button", { name: "Cartera" })).toHaveAttribute("aria-pressed", "true")
  })

  it("treats an archived status deep link as Archivo without fetching the full list", async () => {
    setup("/projects?status=completed")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ lifecycle: "archive", status: "completed" })))
  })
  it("surfaces unassigned projects and filters them across the server cohort", async () => {
    api.unassignedCount.mockResolvedValue(3)
    setup("/projects?status=active&type=recurring&period=month&page=2")
    expect(await screen.findByText("3 proyectos sin responsable.")).toBeInTheDocument()
    expect(screen.getByText(/Los avisos de seguimiento requieren/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Filtrar sin responsable" }))
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith({ lifecycle: "portfolio", owner: "unassigned", page: 1, page_size: 25 }))
    expect(screen.getByTestId("location")).toHaveTextContent("/projects?owner=unassigned")
    await userEvent.selectOptions(screen.getByLabelText("Responsable del proyecto"), "assigned")
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ owner: "assigned", page: 1 })))
    expect(screen.queryByText("3 proyectos sin responsable.")).not.toBeInTheDocument()
  })
  it("opens a person-specific portfolio filter even after that person is inactive", async () => {
    setup("/projects?owner=9")
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ lifecycle: "portfolio", owner: "9" })))
    await waitFor(() => expect(screen.getByLabelText("Responsable del proyecto")).toHaveDisplayValue("Persona inactiva (inactivo)"))
  })
  it("keeps the project list usable when the owner count fails and offers retry", async () => {
    api.unassignedCount.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(2)
    setup()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo comprobar si hay proyectos sin responsable")
    expect(screen.queryByText("2 proyectos sin responsable.")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("2 proyectos sin responsable.")).toBeInTheDocument()
  })
  it("creates with only name and client, preserves the draft on error and opens the created project", async () => {
    api.create.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({id: 91})
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Entrega nueva")
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    await userEvent.selectOptions(screen.getByLabelText("Responsable (opcional)"), "8")
    expect(screen.getByLabelText("Entrega prevista (opcional)")).not.toBeRequired()
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await screen.findByRole("alert")
    expect(screen.getByLabelText("Nombre *")).toHaveValue("Entrega nueva")
    expect(screen.getByLabelText("Cliente *")).toHaveValue("17")
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/projects/91?created=1"))
    expect(api.create).toHaveBeenLastCalledWith(expect.objectContaining({name: "Entrega nueva", client_id: 17, owner_id: 8, is_recurring: false, start_date: undefined, target_end_date: undefined, monthly_fee: undefined, budget_amount: undefined}))
    expect(screen.queryByRole("option", {name: "Persona inactiva"})).not.toBeInTheDocument()
  })
  it("opens an empty review form from the commercial handoff URL", async () => {
    setup("/projects?new=1")
    const dialog = await screen.findByRole("dialog", { name: "Nuevo proyecto" })
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/projects"))
    expect(screen.getByTestId("location")).not.toHaveTextContent("new=1")
    expect(within(dialog).getByLabelText("Nombre *")).toHaveValue("")
    await userEvent.click(within(dialog).getByText("Alcance, fechas y condiciones económicas"))
    expect(within(dialog).getByLabelText("Modelo de precio")).toHaveValue("")
    expect(within(dialog).getByLabelText("Presupuesto total (EUR, opcional)")).toHaveValue(null)
    expect(api.create).not.toHaveBeenCalled()
  })
  it("does not open the handoff form without project write access", async () => {
    auth.canWrite = false
    setup("/projects?new=1")
    await waitFor(() => expect(api.list).toHaveBeenCalled())
    expect(screen.queryByRole("dialog", { name: "Nuevo proyecto" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Nuevo proyecto" })).toBeDisabled()
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

  it("sends the explicitly selected owner through the template flow", async () => {
    api.templates.mockResolvedValue({seo: {name: "SEO", phase_count: 1, task_count: 1}})
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.click(screen.getByText("Partir de una plantilla o un documento"))
    await userEvent.click(screen.getByRole("button", {name: "Usar plantilla"}))
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    await userEvent.selectOptions(screen.getByLabelText("Responsable (opcional)"), "8")
    await userEvent.selectOptions(screen.getByLabelText("Plantilla *"), "seo")
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(api.createFromTemplate).toHaveBeenCalledWith(17, "seo", undefined, 8))
  })

  it("keeps an owner selected by the user when a PDF draft has no owner context", async () => {
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.click(screen.getByText("Partir de una plantilla o un documento"))
    await userEvent.click(screen.getByRole("button", {name: "Importar PDF"}))
    await userEvent.upload(screen.getByLabelText("Propuesta PDF *"), new File(["pdf"], "proposal.pdf", {type: "application/pdf"}))
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    await userEvent.selectOptions(screen.getByLabelText("Responsable (opcional)"), "8")
    await userEvent.click(screen.getByRole("button", {name: "Analizar propuesta"}))
    await waitFor(() => expect(api.extractFromPdf).toHaveBeenCalled())
    expect(await screen.findByText("Revisar datos extraídos")).toBeInTheDocument()
    const review = screen.getByRole("dialog", {name: "Revisar datos extraídos"})
    await userEvent.click(within(review).getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({name: "Extraído", client_id: 17, owner_id: 8})))
  })

  it("allows creating with no owner when there are no active users", async () => {
    api.users.mockResolvedValue([{id: 9, full_name: "Persona inactiva", is_active: false}])
    setup()
    await userEvent.click(screen.getByRole("button", {name: "Nuevo proyecto"}))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Sin contexto")
    await userEvent.selectOptions(screen.getByLabelText("Cliente *"), "17")
    expect(screen.getByLabelText("Responsable (opcional)")).toHaveDisplayValue("Sin responsable")
    expect(screen.getByText(/no recibirá avisos de seguimiento/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", {name: "Crear proyecto"}))
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({owner_id: undefined})))
  })

})
