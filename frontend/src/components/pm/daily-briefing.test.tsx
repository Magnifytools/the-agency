import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { DailyBriefingDialog } from "./daily-briefing"

const mocks = vi.hoisted(() => ({ briefing: vi.fn(), share: vi.fn(), info: vi.fn() }))
vi.mock("@/lib/api", () => ({
  pmApi: { dailyBriefing: mocks.briefing, shareBriefingToDiscord: mocks.share },
  deliveriesApi: { listManual: vi.fn().mockResolvedValue([]) },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: 7, role: "admin" }, hasPermission: () => true }),
}))
vi.mock("sonner", () => ({
  toast: { info: mocks.info, success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}))

describe("DailyBriefingDialog manual delivery", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.briefing.mockResolvedValue({
      date: "2026-09-17",
      greeting: "Buenos días",
      priorities: [],
      alerts: [],
      followups: [],
      suggestion: null,
      discord_content: "Snapshot exacto mostrado",
    })
    mocks.share.mockResolvedValue({
      delivery_id: "receipt-1",
      status: "pending",
      success: false,
      message: "En cola",
    })
  })

  it("queues the displayed snapshot with its scope and civil date", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DailyBriefingDialog open onOpenChange={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await screen.findByText("Buenos días")
    await userEvent.selectOptions(screen.getByLabelText("Ámbito del resumen"), "team")
    await userEvent.click(screen.getByRole("button", { name: "Compartir en Discord" }))

    await waitFor(() => expect(mocks.share).toHaveBeenCalledWith(
      "team",
      "Snapshot exacto mostrado",
      "2026-09-17",
    ))
    expect(mocks.info).toHaveBeenCalledWith("En cola")
  })
})
