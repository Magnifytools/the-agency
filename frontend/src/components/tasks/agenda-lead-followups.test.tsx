import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, it, vi } from "vitest"
import { AgendaLeadFollowups } from "./agenda-lead-followups"

const agenda = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ leadsApi: { agenda } }))

function setup() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><AgendaLeadFollowups today="2026-10-28" userId={1} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

it("lists due lead follow-ups linking to the lead, late ones flagged", async () => {
  agenda.mockResolvedValue([
    { id: 5, company_name: "Hotel Mar", contact_name: "Luis", next_followup_date: "2026-10-26", next_followup_notes: "Llamar por el presupuesto",
      status: "proposal", assigned_user_name: "David", days_until_followup: -2 },
  ])
  setup()
  const link = await screen.findByRole("link", { name: "Hotel Mar" })
  expect(link).toHaveAttribute("href", "/leads/5")
  expect(screen.getByText("Llamar por el presupuesto")).toBeInTheDocument()
  expect(screen.getByText("26 oct")).toHaveClass("text-destructive")
  expect(agenda).toHaveBeenCalledWith("2026-10-28")
})

it("renders nothing without due follow-ups", async () => {
  agenda.mockResolvedValue([])
  const { container } = setup()
  await waitFor(() => expect(agenda).toHaveBeenCalled())
  expect(container).toBeEmptyDOMElement()
})
