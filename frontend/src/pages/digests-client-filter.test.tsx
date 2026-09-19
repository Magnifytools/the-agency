import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import DigestsPage from "./digests-page"

const mocks = vi.hoisted(() => ({
  listDigests: vi.fn().mockResolvedValue([]),
  listClients: vi.fn().mockResolvedValue([{ id: 5, name: "Acme" }]),
}))

vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 }, isAdmin: true, hasPermission: () => true }) }))
vi.mock("@/components/digests/digest-cohort", () => ({ DigestCohort: ({ clientId }: { clientId?: number }) => <div data-testid="cohort-client">{clientId}</div> }))
vi.mock("@/lib/api", () => ({
  digestsApi: { list: mocks.listDigests },
  clientsApi: { listAll: mocks.listClients },
  discordApi: {},
}))
vi.mock("@/components/delivery-receipts", () => ({
  DeliveryReceipts: () => null,
  deliveryToast: vi.fn(),
}))

describe("digests client filter", () => {
  it("uses the client id from the URL when opening client summaries", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/digests?client_id=5"]}>
          <DigestsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByTestId("cohort-client")).toHaveTextContent("5")
    await waitFor(() => {
      expect(mocks.listDigests).toHaveBeenCalledWith(expect.objectContaining({ client_id: 5 }))
    })
  })
})
