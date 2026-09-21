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
  onboard: vi.fn(),
  recoverOnboarding: vi.fn(),
  extractContext: vi.fn(),
  health: vi.fn(),
  engineConfig: vi.fn(),
}))

vi.mock("@/lib/api", () => ({
  clientsApi: {
    list: api.clients,
    create: api.createClient,
    onboard: api.onboard,
    recoverOnboarding: api.recoverOnboarding,
    update: vi.fn(),
    delete: vi.fn(),
    hardDelete: vi.fn(),
    extractContext: api.extractContext,
  },
  clientHealthApi: { list: api.health },
  engineApi: { getConfig: api.engineConfig },
}))
const auth = vi.hoisted(() => ({
  user: { id: 7 },
  canWriteClients: true,
  canWriteProjects: true,
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    isAdmin: false,
    user: auth.user,
    hasPermission: (module: string, write = false) => !write || (module === "clients" ? auth.canWriteClients : module === "projects" ? auth.canWriteProjects : false),
  }),
}))
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
    api.onboard.mockResolvedValue({ status: "confirmed", client_id: 18, contact_ids: [], project_id: null, replayed: false, undo_state: "available", change_log_id: 1 })
    api.recoverOnboarding.mockResolvedValue({ status: "not_committed", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
    auth.user = { id: 7 }
    auth.canWriteClients = true
    auth.canWriteProjects = true
    localStorage.clear()
  })

  it("names the client selection controls in the desktop table", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    show()
    expect(await screen.findByRole("checkbox", { name: "Seleccionar cliente Cliente conservado" })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Seleccionar todos los clientes visibles" })).toBeInTheDocument()
  })

  it("offers retry for an initial 503 without claiming the list is empty", async () => {
    api.clients.mockRejectedValueOnce(httpError(503))
    show()

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los clientes")
    expect(screen.queryByText("Sin resultados")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findAllByText("Sin resultados")).not.toHaveLength(0)
  })

  it("keeps prior rows cached but hidden after a recoverable refresh failure", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow], total: 1, page: 1, page_size: 25 })
    const queryClient = show()
    expect(await screen.findAllByText("Cliente conservado")).not.toHaveLength(0)
    api.clients.mockRejectedValueOnce(httpError(503))

    await act(async () => { await queryClient.invalidateQueries({ queryKey: clientKeys.all() }) })

    expect(await screen.findByText("No se pudieron cargar los clientes. Reintenta en unos momentos.")).toBeInTheDocument()
    expect(screen.queryByText("Cliente conservado")).not.toBeInTheDocument()
    expect(queryClient.getQueryData([...clientKeys.all(), "all", "all", 1, 25])).toMatchObject({ total: 1 })
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

  it("keeps cohort in both list and active-health requests", async () => {
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Externos" }))

    await waitFor(() => expect(api.clients).toHaveBeenLastCalledWith(expect.objectContaining({ cohort: "external", page: 1 })))
    expect(api.health).toHaveBeenLastCalledWith("external")
    expect(screen.getByText(/En cartera · Externos · 0 resultados/)).toBeInTheDocument()
  })

  it("shows observable risks before a high legacy score and does not evaluate inactive clients", async () => {
    api.clients.mockResolvedValueOnce({ items: [clientRow, { ...clientRow, id: 5, name: "Cliente pausado", status: "paused" }], total: 2, page: 1, page_size: 25 })
    api.health.mockResolvedValueOnce([{
      client_id: 4, client_name: clientRow.name, score: 95, risk_level: "healthy", enough_information: true,
      available_source_count: 5, available_weight: 100,
      factors: { communication: 25, tasks: 20, digests: 15, profitability: 20, followups: 15 },
      factor_max: { communication: 25, tasks: 25, digests: 15, profitability: 20, followups: 15 },
      observations: { communication: "Reciente", tasks: "Una tarea vencida a fecha de hoy", digests: "Al día", profitability: "Dentro de presupuesto", followups: "Sin pendientes" },
      risk_signals: ["Una tarea vencida a fecha de hoy"],
    }])
    show()

    expect((await screen.findAllByText("1 riesgo")).length).toBeGreaterThan(0)
    expect(screen.queryByText("95")).not.toBeInTheDocument()
    expect(screen.getAllByText("No evaluado · solo activos").length).toBeGreaterThan(0)
  })

  it("shows a long intermediary name as wrapping provenance below the client", async () => {
    const intermediary = "Asociación internacional de agencias colaboradoras"
    api.clients.mockResolvedValueOnce({ items: [{ ...clientRow, is_intermediary_deal: true, intermediary_name: intermediary }], total: 1, page: 1, page_size: 25 })
    show()

    const provenance = await screen.findByText(`Vía ${intermediary}`)
    expect(provenance).toHaveClass("break-words")
    expect(provenance).toHaveAttribute("title", `Vía ${intermediary}`)
  })

  it("creates the client, contacts and optional project in one recoverable request", async () => {
    api.extractContext.mockResolvedValue({
      name: "Cliente extraído",
      project: { name: "Proyecto sin fecha", start_date: null },
      contacts: [{ name: "Contacto IA", is_primary: true }],
    })
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Fuente sin fecha de inicio")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    expect(await screen.findByDisplayValue("Cliente extraído")).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText("Nombre", { selector: "#extracted_contact_name_0" }))
    await userEvent.type(screen.getByLabelText("Nombre", { selector: "#extracted_contact_name_0" }), "Contacto corregido")
    await userEvent.clear(screen.getByLabelText("Nombre del proyecto"))
    await userEvent.type(screen.getByLabelText("Nombre del proyecto"), "Proyecto corregido")
    await userEvent.click(screen.getByText("Campos avanzados"))
    const monthlyFee = screen.getByLabelText("Cuota mensual")
    expect(monthlyFee).toHaveAttribute("step", "0.01")
    await userEvent.type(monthlyFee, "50.5")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    expect(api.onboard).toHaveBeenCalledWith(expect.objectContaining({
      client: expect.objectContaining({ name: "Cliente extraído" }),
      contacts: [expect.objectContaining({ name: "Contacto corregido", is_primary: true })],
      project: expect.objectContaining({ name: "Proyecto corregido", start_date: null, monthly_fee: 50.5 }),
    }), expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/))
    expect(api.onboard.mock.calls[0][0].project).not.toHaveProperty("client_id")
    expect(api.createClient).not.toHaveBeenCalled()
  })

  it("allows excluding an extracted project without projects write access", async () => {
    auth.canWriteProjects = false
    api.extractContext.mockResolvedValue({ name: "Cliente sin proyecto", project: { name: "No crear" }, contacts: [] })
    show()
    await screen.findAllByText("Sin resultados")
    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Proyecto opcional")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    await userEvent.click(screen.getByRole("checkbox", { name: "Crear proyecto detectado" }))
    expect(screen.getByLabelText("Nombre del proyecto")).toBeDisabled()
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    expect(api.onboard.mock.calls[0][0].project).toBeNull()
  })

  it("shows a 422 validation message in the open dialog and recovers the cancelled attempt", async () => {
    api.onboard.mockRejectedValueOnce(Object.assign(new Error("invalid"), { response: { status: 422, data: { detail: [{ msg: "El nombre ya existe" }] } } }))
    api.recoverOnboarding.mockResolvedValueOnce({ status: "not_committed", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
    show()
    await screen.findAllByText("Sin resultados")
    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Repetido")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))
    expect(await screen.findByText("El nombre ya existe")).toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Crear" })).not.toBeDisabled()
  })

  it("lets the user choose one principal from ambiguous extracted contacts", async () => {
    api.extractContext.mockResolvedValue({
      name: "Cliente con contactos",
      contacts: [
        { name: "Ana", is_primary: true },
        { name: "Bea", is_primary: true },
      ],
    })
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Dos contactos principales")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    expect(await screen.findByText(/marcó más de un contacto principal/i)).toBeInTheDocument()

    const principals = screen.getAllByRole("radio", { name: "Principal" })
    expect(principals).toHaveLength(2)
    expect(principals[0]).not.toBeChecked()
    expect(principals[1]).not.toBeChecked()
    await userEvent.click(principals[1])
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    const contacts = api.onboard.mock.calls[0][0].contacts
    expect(contacts.filter((contact: { is_primary?: boolean }) => contact.is_primary)).toEqual([expect.objectContaining({ name: "Bea" })])
  })

  it("allows a manual primary contact after clearing a detected primary", async () => {
    api.extractContext.mockResolvedValue({
      name: "Cliente manual",
      contacts: [{ name: "Ana detectada", is_primary: true }],
    })
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Contacto manual")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    await userEvent.type(screen.getByLabelText("Nombre", { selector: "#contact_name" }), "Marta manual")
    await userEvent.click(screen.getByRole("radio", { name: "Ninguno de los contactos detectados" }))
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    const contacts = api.onboard.mock.calls[0][0].contacts
    expect(contacts.filter((contact: { is_primary?: boolean }) => contact.is_primary)).toEqual([expect.objectContaining({ name: "Marta manual" })])
  })

  it("keeps an explicitly included detected contact even when its name matches the manual contact", async () => {
    api.extractContext.mockResolvedValue({
      name: "Cliente duplicado",
      contacts: [{ name: "Ana", is_primary: false }],
    })
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.click(screen.getByRole("button", { name: "Pegar contexto" }))
    await userEvent.type(screen.getByPlaceholderText(/Pega aquí emails/), "Contacto repetido de forma explícita")
    await userEvent.click(screen.getByRole("button", { name: "Extraer datos con IA" }))
    await userEvent.type(screen.getByLabelText("Nombre", { selector: "#contact_name" }), "Ana")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    expect(api.onboard.mock.calls[0][0].contacts).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "Ana", is_primary: true }),
      expect.objectContaining({ name: "Ana", is_primary: false }),
    ]))
  })

  it("does not send an onboarding attempt when durable key storage is unavailable", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked") })
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Sin almacenamiento")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))

    expect(api.onboard).not.toHaveBeenCalled()
    storage.mockRestore()
  })

  it("recovers a timed-out attempt after reload without storing client data", async () => {
    const pendingKey = "recoverable-attempt-0000000000000001"
    localStorage.setItem(`agency:client-onboarding:7:${pendingKey}`, "pending")
    api.recoverOnboarding.mockResolvedValueOnce({
      status: "confirmed", client_id: 24, contact_ids: [5], project_id: null,
      replayed: true, undo_state: "available", change_log_id: 12,
    })
    show()

    await waitFor(() => expect(api.recoverOnboarding).toHaveBeenCalledWith(pendingKey))
    await waitFor(() => expect(localStorage.getItem(`agency:client-onboarding:7:${pendingKey}`)).toBeNull())
    expect([...Array(localStorage.length)].map((_, index) => localStorage.key(index))).not.toContain("Cliente recuperable")
    expect(api.onboard).not.toHaveBeenCalled()
  })

  it("keeps separate pending keys from two tabs and recovers each one", async () => {
    const firstKey = "first-tab-attempt-000000000000000001"
    const secondKey = "second-tab-attempt-00000000000000001"
    localStorage.setItem(`agency:client-onboarding:7:${firstKey}`, "pending")
    localStorage.setItem(`agency:client-onboarding:7:${secondKey}`, "pending")
    api.recoverOnboarding
      .mockResolvedValueOnce({ status: "not_committed", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
      .mockResolvedValueOnce({ status: "not_committed", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
    show()

    await waitFor(() => expect(api.recoverOnboarding).toHaveBeenCalledWith(firstKey))
    await waitFor(() => expect(api.recoverOnboarding).toHaveBeenCalledWith(secondKey))
    expect(localStorage.getItem(`agency:client-onboarding:7:${firstKey}`)).toBeNull()
    expect(localStorage.getItem(`agency:client-onboarding:7:${secondKey}`)).toBeNull()
  })

  it("keeps a timed-out form blocked until recovery resolves, then reuses no old key", async () => {
    api.onboard.mockRejectedValueOnce(new Error("network timeout"))
    let resolveRecovery!: (value: { status: "not_committed"; client_id: null; contact_ids: []; project_id: null; replayed: false; undo_state: "unavailable"; change_log_id: null }) => void
    api.recoverOnboarding.mockImplementationOnce(() => new Promise((resolve) => { resolveRecovery = resolve }))
    show()
    await screen.findAllByText("Sin resultados")

    await userEvent.click(screen.getByRole("button", { name: "Nuevo cliente" }))
    await userEvent.type(screen.getByLabelText("Nombre *"), "Intento incierto")
    await userEvent.click(screen.getByRole("button", { name: "Crear" }))
    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(1))
    const firstKey = api.onboard.mock.calls[0][1]
    expect(screen.getByRole("button", { name: "Crear" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Nuevo cliente" })).toBeDisabled()

    resolveRecovery({ status: "not_committed", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
    expect((await screen.findAllByText("No se confirmó el alta. Revisa los datos y vuelve a intentarlo.")).length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: "Crear" })).not.toBeDisabled()

    await userEvent.click(screen.getByRole("button", { name: "Crear" }))
    await waitFor(() => expect(api.onboard).toHaveBeenCalledTimes(2))
    expect(api.onboard.mock.calls[1][1]).not.toBe(firstKey)
  })

  it("does not recover another identity's key or let its late response remove this identity's attempt", async () => {
    const keyA = "identity-a-attempt-00000000000000001"
    const keyB = "identity-b-attempt-00000000000000001"
    localStorage.setItem(`agency:client-onboarding:7:${keyA}`, "pending")
    let resolveA!: (value: { status: "confirmed"; client_id: number; contact_ids: []; project_id: null; replayed: false; undo_state: "unavailable"; change_log_id: null }) => void
    const recoveryA = new Promise<{ status: "confirmed"; client_id: number; contact_ids: []; project_id: null; replayed: false; undo_state: "unavailable"; change_log_id: null }>((resolve) => { resolveA = resolve })
    api.recoverOnboarding.mockImplementation((key: string) => key === keyA
      ? recoveryA
      : Promise.resolve({ status: "processing", client_id: null, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null }))
    const queryClient = show()
    await waitFor(() => expect(api.recoverOnboarding).toHaveBeenCalledWith(keyA))

    auth.user = { id: 8 }
    localStorage.setItem(`agency:client-onboarding:8:${keyB}`, "pending")
    cleanup()
    show(queryClient)
    await waitFor(() => expect(api.recoverOnboarding).toHaveBeenCalledWith(keyB))

    resolveA({ status: "confirmed", client_id: 41, contact_ids: [], project_id: null, replayed: false, undo_state: "unavailable", change_log_id: null })
    await act(async () => {})
    expect(localStorage.getItem(`agency:client-onboarding:8:${keyB}`)).toBe("pending")
  })

  it("blocks a new onboarding operation if pending-key storage cannot be read", async () => {
    const pendingKey = "unreadable-attempt-00000000000000001"
    localStorage.setItem(`agency:client-onboarding:7:${pendingKey}`, "pending")
    const storage = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
    show()

    expect(await screen.findByText(/no pudo comprobar si hay un alta pendiente/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Nuevo cliente" })).toBeDisabled()
    expect(api.onboard).not.toHaveBeenCalled()
    storage.mockRestore()
  })
})
