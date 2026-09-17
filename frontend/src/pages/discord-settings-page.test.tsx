import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import DiscordSettingsPage from "./discord-settings-page"

const mocks = vi.hoisted(() => ({ test: vi.fn(), listManual: vi.fn() }))
vi.mock("@/lib/api", () => ({
  discordApi: {
    settings: vi.fn().mockResolvedValue({
      webhook_configured: true,
      bot_token_configured: false,
      auto_daily_summary: false,
      summary_time: "18:00",
      include_ai_note: true,
      last_sent_at: null,
    }),
    testWebhook: mocks.test,
    updateSettings: vi.fn(),
    preview: vi.fn(),
    sendCustom: vi.fn(),
  },
  deliveriesApi: { listManual: mocks.listManual },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: 7 } }),
}))
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() },
}))

describe("Discord webhook test request identity", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listManual.mockResolvedValue([])
  })

  it("reuses a lost request key and renews it only after a receipt", async () => {
    mocks.test
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ delivery_id: "one", status: "pending", message: "En cola" })
      .mockResolvedValueOnce({ delivery_id: "two", status: "pending", message: "En cola" })
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002")
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><DiscordSettingsPage /></QueryClientProvider>)

    const button = await screen.findByRole("button", { name: "Probar" })
    await userEvent.click(button)
    await waitFor(() => expect(mocks.test).toHaveBeenCalledTimes(1))
    await userEvent.click(button)
    await waitFor(() => expect(mocks.test).toHaveBeenCalledTimes(2))
    expect(mocks.test.mock.calls[0][0]).toBe(mocks.test.mock.calls[1][0])

    await userEvent.click(button)
    await waitFor(() => expect(mocks.test).toHaveBeenCalledTimes(3))
    expect(mocks.test.mock.calls[2][0]).not.toBe(mocks.test.mock.calls[1][0])
  })
})
