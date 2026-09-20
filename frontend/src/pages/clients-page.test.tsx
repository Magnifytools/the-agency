import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { clientKeys } from "@/lib/query-keys"
import ClientsPage from "./clients-page"

const api = vi.hoisted(() => ({
  clients: vi.fn(),
  createClient: vi.fn(),
  createContact: vi.fn(),
  createProject: vi.fn(),
  extractContext: vi.fn(),
  health: vi.fn(),
  engineConfig: vi.fn(),
}))

vi.mock("@/lib/api", () => ({
  clientsApi: {
    list: api.clients,
    create: api.createClient,
    update: vi.fn(),
    delete: vi.fn(),
    hardDelete: vi.fn(),
    extractContext: api.extractContext,
  },
  clientHealthApi: { list: api.health },
  contactsApi: { create: api.createContact },
  projectsApi: { create: api.createProject },
  engineApi: { getConfig: api.engineConfig },
}))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: false }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

const clientRow = {
  id: 4,
  name: "Cliente conservado",
  company: "Empresa",
  email: "client@example.test",
  contract_type: "retainer",
  status: "active",
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } })
}

function show(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><ClientsPage /></MemoryRouter>
    </QueryClientProvider>,
  )
  return queryClient
}

describe("ClientsPage recovery states", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.clients.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    api.health.mockResolvedValue([])
    api.engineConfig.mockResolvedValue({ engine_frontend_url: null })
  })

  it("offers retry for an initial 503 without claiming the list is empty", async () => {
    api.clients.mockRejectedValueOnce(httpError(503))
    show()

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los clientes")
    expect(screen.queryByText("Sin clientes todavía")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findAllByText("Sin clientes todavía")).not.toHaveLength(0)
  })

  it("keeps prior rows cached but hidden after a recoverable refresh failure", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    const queryClient = show()
    expect(await screen.findAllByText("Cliente conservado")).not.toHaveLength(0)
    api.clients.mockRejectedValueOnce(httpError(503))

    await act(async () => { await queryClient.invalidateQueries({ queryKey: clientKeys.all() }) })

    expect(await screen.findByText("No se pudieron cargar los clientes. Reintenta en unos momentos.")).toBeInTheDocument()
    expect(screen.queryByText("Cliente conservado")).not.toBeInTheDocument()
    expect(queryClient.getQueryData([...clientKeys.all(), "all", 1, 25])).toMatchObject({ total: 1 })
  })

  it("hides cached rows when refreshed access is denied", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    const queryClient = show()
    expect(await screen.findAllByText("Cliente conservado")).not.toHaveLength(0)
    api.clients.mockRejectedValueOnce(httpError(403))

    await act(async () => { await queryClient.invalidateQueries({ queryKey: clientKeys.all() }) })

    expect(await screen.findByText("No tienes acceso a la lista de clientes.")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("Cliente conservado")).not.toBeInTheDocument())
  })

  it("does not reveal denied cache across 503, remount and a pending retry", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    const queryClient = show()
    expect(await screen.findAllByText("Cliente conservado")).not.toHaveLength(0)
    api.clients.mockRejectedValueOnce(httpError(403))
    await act(async () => { await queryClient.invalidateQueries({ queryKey: clientKeys.all() }) })
    expect(await screen.findByText("No tienes acceso a la lista de clientes.")).toBeInTheDocument()

    api.clients.mockRejectedValueOnce(httpError(503))
    cleanup()
    show(queryClient)
    expect(await screen.findByText("No se pudieron cargar los clientes. Reintenta en unos momentos.")).toBeInTheDocument()
    expect(screen.queryByText("Cliente conservado")).not.toBeInTheDocument()

    let release!: (value: { items: Array<typeof clientRow>; total: number; page: number; page_size: number }) => void
    api.clients.mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
    cleanup()
    show(queryClient)
    expect(screen.queryByText("Cliente conservado")).not.toBeInTheDocument()

    release({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    expect(await screen.findAllByText("Cliente conservado")).not.toHaveLength(0)
  })

  it("reports an unavailable health source without turning it into healthy data", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    api.health.mockRejectedValueOnce(httpError(503))
    show()

    expect(await screen.findByText("No se pudo actualizar la salud de clientes.")).toBeInTheDocument()
    expect(screen.getAllByText("Cliente conservado")).not.toHaveLength(0)
    expect(screen.queryByText(/Saludable/)).not.toBeInTheDocument()
  })

  it("refreshes client consumers when a later contact request fails", async () => {
    api.createClient.mockResolvedValue({ ...clientRow, id: 18 })
    api.createContact.mockRejectedValue(httpError(503))
    show()
    await screen.findAllByText("Sin clientes todavía")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Cliente parcial")
    await userEvent.type(document.querySelector<HTMLInputElement>("#contact_name")!, "Contacto")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.createClient).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(api.createContact).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(api.clients.mock.calls.length).toBeGreaterThan(1))
  })

  it("preserves an unknown project start date from extracted context", async () => {
    api.extractContext.mockResolvedValue({
      name: "Cliente extraído",
      project: { name: "Proyecto sin fecha", start_date: null },
      contacts: [],
    })
    api.createClient.mockResolvedValue({ ...clientRow, id: 22, name: "Cliente extraído" })
    api.createProject.mockResolvedValue({ id: 31 })
    show()
    await screen.findAllByText("Sin clientes todavía")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Fuente sin fecha de inicio")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    expect(await screen.findByDisplayValue("Cliente extraído")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.createProject).toHaveBeenCalledWith(expect.objectContaining({
      name: "Proyecto sin fecha",
      client_id: 22,
      start_date: null,
    })))
  })
})
