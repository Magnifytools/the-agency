import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { Ga4Section } from "./ga4-section"

vi.mock("@/lib/api", () => ({ ga4Api: {
  getStatus: vi.fn().mockResolvedValue({ configured: true, properties: [
    { property_id: "311111111", clients: [{ id: 1, name: "Fit Generation" }], last_data_date: null,
      last_synced_at: null, error_code: "missing_scope", google_email: null },
  ] }),
  sync: vi.fn(),
} }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

describe("Ga4Section", () => {
  it("lists properties and says when the account needs the Analytics permission", async () => {
    render(<QueryClientProvider client={new QueryClient()}><Ga4Section /></QueryClientProvider>)
    expect(await screen.findByText("311111111")).toBeInTheDocument()
    expect(screen.getByText("Fit Generation")).toBeInTheDocument()
    expect(screen.getByText(/reconéctala en Ajustes/)).toBeInTheDocument()
  })
})
