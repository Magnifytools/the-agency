import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { it, expect, vi } from "vitest"
import { InboxWidget } from "./inbox-widget"

vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1 } }) }))
vi.mock("@/lib/api", () => ({ inboxApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), dismiss: vi.fn() } }))

it("offers a named note entry and action without English count copy", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><InboxWidget /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText("0 notas")).toBeInTheDocument()
  expect(screen.getByRole("textbox", { name: "Capturar una nota" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Guardar nota en Por aclarar" })).toBeDisabled()
})
