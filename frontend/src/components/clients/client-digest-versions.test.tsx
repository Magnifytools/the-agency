import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, it, vi } from "vitest"
import { ClientDigestVersions } from "./client-digest-versions"
import { DigestCell } from "./client-status"

const list = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ digestsApi: { list } }))

function show(ui: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

it("lists the client's versions, each opening its editor, and links to all of them", async () => {
  list.mockResolvedValue([
    { id: 62, client_id: 1, period_start: "2026-10-19", period_end: "2026-10-25", status: "draft" },
    { id: 58, client_id: 1, period_start: "2026-09-01", period_end: "2026-09-30", status: "reviewed" },
  ])
  show(<ClientDigestVersions clientId={1} />)
  const weekly = await screen.findByRole("link", { name: /Seguimiento semanal/ })
  expect(weekly).toHaveAttribute("href", "/digests/62/edit")
  expect(weekly).toHaveTextContent("Borrador · #62")
  expect(screen.getByRole("link", { name: /Informe mensual/ })).toHaveAttribute("href", "/digests/58/edit")
  expect(screen.getByRole("link", { name: "Ver todos" })).toHaveAttribute("href", "/digests?client_id=1")
  expect(list).toHaveBeenCalledWith({ client_id: 1, limit: 8, offset: 0 })
})

it("says when there is none yet", async () => {
  list.mockResolvedValue([])
  show(<ClientDigestVersions clientId={1} />)
  expect(await screen.findByText("Todavía no hay ninguno.")).toBeInTheDocument()
})

it("the status line links to the client's summaries when given where to go", () => {
  const digests = [{ cadence: "weekly", state: "due", last_sent_period_end: null }] as never
  show(<DigestCell digests={digests} href="/digests?client_id=1" />)
  expect(screen.getByRole("link", { name: "Seguimiento semanal · Toca enviarlo" })).toHaveAttribute("href", "/digests?client_id=1")
})
