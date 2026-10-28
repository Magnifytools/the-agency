import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { expect, it, vi } from "vitest"
import { LeadFunnelCard } from "./lead-funnel-card"

const funnel = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ leadsApi: { funnel } }))

const stages = [
  { status: "new", label: "Nuevo", reached: 4, moved_on: 3, conversion_pct: 75, avg_days: 4 },
  { status: "contacted", label: "Contactado", reached: 3, moved_on: 1, conversion_pct: 33.3, avg_days: null },
  { status: "discovery", label: "Descubrimiento", reached: 1, moved_on: 1, conversion_pct: 100, avg_days: 2.5 },
  { status: "proposal", label: "Propuesta", reached: 1, moved_on: 1, conversion_pct: 100, avg_days: 6 },
  { status: "negotiation", label: "Negociación", reached: 1, moved_on: 1, conversion_pct: 100, avg_days: 1 },
  { status: "won", label: "Ganado", reached: 1, moved_on: 0, conversion_pct: null, avg_days: null },
]

it("shows how many reach each stage, conversion, days and win rate, per period", async () => {
  funnel.mockResolvedValue({ days: 180, total: 4, stages, won: 1, lost: 1, win_rate_pct: 50 })
  render(<QueryClientProvider client={new QueryClient()}><LeadFunnelCard /></QueryClientProvider>)
  expect(await screen.findByText(/4 leads creados · 1 ganados · 1 perdidos · tasa de cierre 50 %/)).toBeInTheDocument()
  expect(screen.getByText("75 %")).toBeInTheDocument()
  expect(screen.getByText("33,3 %")).toBeInTheDocument()
  expect(screen.getByText("2,5 d")).toBeInTheDocument()
  expect(funnel).toHaveBeenCalledWith(180)
  fireEvent.change(screen.getByLabelText("Periodo del embudo"), { target: { value: "365" } })
  await waitFor(() => expect(funnel).toHaveBeenCalledWith(365))
})
