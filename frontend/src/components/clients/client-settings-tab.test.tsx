import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClientSettingsTab } from "./client-settings-tab"

const mocks = vi.hoisted(() => ({
  canWrite: true,
  update: vi.fn(),
  engineProjects: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: false, hasPermission: (_module: string, write = false) => write ? mocks.canWrite : true }),
}))
vi.mock("@/lib/api", () => ({
  clientsApi: { update: mocks.update },
  engineApi: { listProjects: mocks.engineProjects },
}))
vi.mock("@/lib/query-keys", () => ({ invalidateClientChange: vi.fn() }))

const client = {
  id: 5,
  ga4_property_id: "123456",
  gsc_url: "https://example.com",
  engine_project_id: null,
} as never

function show() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><ClientSettingsTab client={client} /></QueryClientProvider>)
}

describe("ClientSettingsTab permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.canWrite = true
    mocks.update.mockResolvedValue({})
    mocks.engineProjects.mockResolvedValue([])
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
    })
  })
})
