import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { SearchConsoleSection } from "./search-console-section"

const mocks = vi.hoisted(() => ({ getStatus: vi.fn(), disconnect: vi.fn(), getAuthUrl: vi.fn(), sync: vi.fn() }))
vi.mock("@/lib/api", () => ({ gscApi: mocks }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><SearchConsoleSection /></QueryClientProvider>)
}

describe("SearchConsoleSection with several Google accounts", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.disconnect.mockResolvedValue({ status: "disconnected" })
    mocks.getStatus.mockResolvedValue({
      configured: true,
      connections: [
        { id: 1, status: "connected", google_email: "digital@magnify.ing", connected_by: "David", connected_at: "2026-10-18T10:00:00Z" },
        { id: 2, status: "reconnect_required", google_email: "david@magnify.ing", connected_by: "David", connected_at: "2026-10-19T10:00:00Z" },
      ],
      sites: [{
        site_url: "sc-domain:fitgeneration.es", clients: [{ id: 1, name: "Fit Generation" }], backfilled: true,
        last_data_date: "2026-10-17", last_synced_at: "2026-10-18T05:00:00Z", error_code: null, google_email: "digital@magnify.ing",
      }],
    })
  })

  it("lists each account with its state and lets you add another", async () => {
    show()
    expect(await screen.findByText("digital@magnify.ing", { selector: "span.font-medium" })).toBeInTheDocument()
    expect(screen.getByText(/necesita reconectar/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reconectar" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Añadir cuenta de Google" })).toBeInTheDocument()
    const row = screen.getByText("sc-domain:fitgeneration.es").closest("tr") as HTMLElement
    expect(within(row).getByText("digital@magnify.ing")).toBeInTheDocument()
  })

  it("disconnects only the chosen account", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Desconectar david@magnify.ing" }))
    expect(mocks.disconnect).toHaveBeenCalledWith(2)
  })
})
