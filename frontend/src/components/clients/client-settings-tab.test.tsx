import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClientSettingsTab } from "./client-settings-tab"

const mocks = vi.hoisted(() => ({
  canWrite: true,
  update: vi.fn(),
  gscStatus: vi.fn(),
  vigilClients: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: false, hasPermission: (_module: string, write = false) => write ? mocks.canWrite : true }),
}))
vi.mock("@/lib/api", () => ({
  clientsApi: { update: mocks.update },
  gscApi: { getStatus: mocks.gscStatus, listSites: vi.fn() },
  ga4Api: { getStatus: vi.fn().mockResolvedValue({ configured: true, properties: [] }), sync: vi.fn() },
  vigilApi: { clients: mocks.vigilClients },
}))
vi.mock("@/lib/query-keys", () => ({ invalidateClientChange: vi.fn() }))

const client = {
  id: 5,
  ga4_property_id: "123456",
  gsc_url: "https://example.com",
  content_engine_client_id: null,
} as never

function show() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><ClientSettingsTab client={client} /></QueryClientProvider>)
}

describe("ClientSettingsTab permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.canWrite = true
    mocks.vigilClients.mockResolvedValue({ configured: true, clients: [{ slug: "parklex", name: "Parklex", linked_to: null }] })
    mocks.update.mockResolvedValue({})
    mocks.gscStatus.mockResolvedValue({ configured: true, connections: [], sites: [] })
  })

  it("shows current analytics settings without a save action to a client reader", () => {
    mocks.canWrite = false
    show()

    expect(screen.getByRole("status")).toHaveTextContent("Puedes consultar estos ajustes")
    expect(screen.getByDisplayValue("123456")).toBeDisabled()
    expect(screen.getByDisplayValue("https://example.com")).toBeDisabled()
    expect(screen.queryByRole("button", { name: "Guardar" })).not.toBeInTheDocument()
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("keeps analytics settings editable for a client writer", async () => {
    const user = userEvent.setup()
    show()

    const ga4 = screen.getByDisplayValue("123456")
    await user.clear(ga4)
    await user.type(ga4, "654321")
    await user.click(screen.getByRole("button", { name: "Guardar" }))

    expect(mocks.update).toHaveBeenCalledWith(5, {
      ga4_property_id: "654321",
      gsc_url: "https://example.com",
      vigil_slug: null,
      content_engine_client_id: null,
    })
  })

  it("shows how far the saved Search Console property has been imported", async () => {
    mocks.gscStatus.mockResolvedValue({
      configured: true,
      connections: [{ id: 1, status: "connected", google_email: "seo@magnify.ing", connected_by: "David", connected_at: "2026-10-01T10:00:00Z" }],
      sites: [{ site_url: "https://example.com/", clients: [{ id: 5, name: "Ejemplo" }], backfilled: true,
                last_data_date: "2026-10-15", last_synced_at: "2026-10-18T06:00:00Z", error_code: "no_access" }],
    })
    show()

    expect(await screen.findByText(/Datos importados hasta el 15 de octubre de 2026/)).toBeInTheDocument()
    expect(screen.getByText("La cuenta conectada no tiene acceso a esta propiedad.")).toBeInTheDocument()
  })

  it("links the client to Vigil by its slug", async () => {
    mocks.update.mockResolvedValue({})
    show()
    const input = screen.getByLabelText("Cliente en Vigil")
    await userEvent.type(input, "parklex")
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }))
    expect(mocks.update).toHaveBeenCalledWith(5, expect.objectContaining({ vigil_slug: "parklex" }))
  })

  it("links the client to Engine only by a valid uuid", async () => {
    show()
    const input = screen.getByLabelText("Cliente en Engine")
    await userEvent.type(input, "42")
    expect(screen.getByText(/identificador del cliente en Engine \(uuid\)/)).toBeInTheDocument()
    expect(input).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled()

    await userEvent.clear(input)
    await userEvent.type(input, " 3f2b8c1e-9d4a-4f6b-8e2a-1c5d7e9f0a3b ")
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }))
    expect(mocks.update).toHaveBeenCalledWith(5, expect.objectContaining({
      content_engine_client_id: "3f2b8c1e-9d4a-4f6b-8e2a-1c5d7e9f0a3b",
    }))
  })
})
