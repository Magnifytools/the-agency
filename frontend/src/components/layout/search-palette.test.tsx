import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { SearchPalette } from "./search-palette"

const api = vi.hoisted(() => ({ search: vi.fn() }))
const auth = vi.hoisted(() => ({ user: { id: 7 }, permissions: new Set(["clients", "projects", "tasks", "leads"]) }))
vi.mock("@/lib/api", () => ({ searchApi: api }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: auth.user, hasPermission: (module: string) => auth.permissions.has(module) }) }))
vi.mock("@/lib/hidden-modules", () => ({ isEnabled: () => true }))

const emptyResults = { clients: [], projects: [], tasks: [], leads: [] }

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function show(open = true, onOpenChange = vi.fn()) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><SearchPalette open={open} onOpenChange={onOpenChange} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  auth.user = { id: 7 }
  auth.permissions = new Set(["clients", "projects", "tasks", "leads"])
  api.search.mockReset()
  api.search.mockResolvedValue(emptyResults)
})

it("shows loading and a retryable error instead of an empty result", async () => {
  api.search.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ clients: [{ id: 1, name: "Acme", company: null }], projects: [], tasks: [], leads: [] })
  show()
  await userEvent.type(screen.getByRole("textbox", { name: "Buscar" }), "ac")
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo buscar")
  await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  await waitFor(() => expect(screen.getByText("Acme")).toBeInTheDocument())
})

it("moves one result at a time and navigates only the selected result", async () => {
  api.search.mockResolvedValue({
    ...emptyResults,
    clients: [
      { id: 1, name: "Acme", company: null },
      { id: 2, name: "Beta", company: null },
      { id: 3, name: "Cobalto", company: null },
    ],
  })
  show()
  const input = screen.getByRole("textbox", { name: "Buscar" })
  await userEvent.type(input, "ac")
  expect(await screen.findByText("Beta")).toBeInTheDocument()
  await userEvent.keyboard("{ArrowDown}")
  expect(screen.getByRole("button", { name: "Beta" })).toHaveClass("bg-brand/10")
  await userEvent.keyboard("{Enter}")
  expect(screen.getByTestId("location")).toHaveTextContent("/clients/2")
})

it("traps focus in the shared dialog and restores it after Escape", async () => {
  function Harness() {
    const [open, setOpen] = useState(false)
    return <><button onClick={() => setOpen(true)}>Abrir búsqueda</button><SearchPalette open={open} onOpenChange={setOpen} /></>
  }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><Harness /></MemoryRouter></QueryClientProvider>)
  const opener = screen.getByRole("button", { name: "Abrir búsqueda" })
  opener.focus()
  await userEvent.click(opener)
  const input = await screen.findByRole("textbox", { name: "Buscar" })
  await waitFor(() => expect(input).toHaveFocus())
  screen.getByRole("button", { name: "Cerrar" }).focus()
  await userEvent.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(opener).toHaveFocus()
})

it("does not retain results when the identity changes", async () => {
  let resolveSecondSearch: ((value: typeof emptyResults) => void) | undefined
  api.search
    .mockResolvedValueOnce({ ...emptyResults, clients: [{ id: 1, name: "Acme", company: null }] })
    .mockImplementationOnce(() => new Promise((resolve) => { resolveSecondSearch = resolve }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPalette open onOpenChange={vi.fn()} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.type(screen.getByRole("textbox", { name: "Buscar" }), "ac")
  expect(await screen.findByText("Acme")).toBeInTheDocument()

  auth.user = { id: 8 }
  rendered.rerender(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPalette open onOpenChange={vi.fn()} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await within(screen.getByRole("dialog")).findByRole("status")).toHaveTextContent("Buscando")
  expect(screen.queryByText("Acme")).not.toBeInTheDocument()
  resolveSecondSearch?.(emptyResults)
})

it("does not retain results when the active permissions change", async () => {
  let resolveSecondSearch: ((value: typeof emptyResults) => void) | undefined
  api.search
    .mockResolvedValueOnce({ ...emptyResults, clients: [{ id: 1, name: "Acme", company: null }] })
    .mockImplementationOnce(() => new Promise((resolve) => { resolveSecondSearch = resolve }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPalette open onOpenChange={vi.fn()} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.type(screen.getByRole("textbox", { name: "Buscar" }), "ac")
  expect(await screen.findByText("Acme")).toBeInTheDocument()

  auth.permissions = new Set(["tasks"])
  rendered.rerender(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPalette open onOpenChange={vi.fn()} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await within(screen.getByRole("dialog")).findByRole("status")).toHaveTextContent("Buscando")
  expect(screen.queryByText("Acme")).not.toBeInTheDocument()
  resolveSecondSearch?.(emptyResults)
})

it("does not navigate a cached result while a refetch error is visible", async () => {
  api.search.mockResolvedValueOnce({ ...emptyResults, clients: [{ id: 1, name: "Acme", company: null }] })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPalette open onOpenChange={vi.fn()} /><Location /></MemoryRouter>
    </QueryClientProvider>,
  )
  const input = screen.getByRole("textbox", { name: "Buscar" })
  await userEvent.type(input, "ac")
  expect(await screen.findByText("Acme")).toBeInTheDocument()
  api.search.mockRejectedValueOnce(new Error("offline"))
  await queryClient.invalidateQueries({ queryKey: ["global-search"] })
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo buscar")
  input.focus()
  await userEvent.keyboard("{Enter}")
  expect(screen.getByTestId("location")).toHaveTextContent("/")
})
import { useState } from "react"
