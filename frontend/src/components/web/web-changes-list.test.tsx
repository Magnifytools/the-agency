import { useState } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { WebChangesList, type ChangeListFilters } from "./web-changes-list"

const api = vi.hoisted(() => ({ list: vi.fn(), ack: vi.fn(), ackAll: vi.fn() }))
const perms = vi.hoisted(() => ({ write: true }))
vi.mock("@/lib/api", () => ({ webChangesApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string, write = false) => module === "web" && (!write || perms.write) }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (id: string, severity: "critical" | "warning" | "info", extra: object = {}) => ({
  id, client_id: 7, client_name: "Fit", watch_id: "w1", url: "https://fit.es/master", label: null, run_id: null,
  max_severity: severity, detected_at: "2026-10-21T06:40:00+00:00", acknowledged_at: null, acknowledged_by: null,
  acknowledged_by_label: null, note: null, has_diff: true,
  items: [{ id: `${id}-i`, kind: "seo", field: "title", severity, rule_code: "TITLE_CHANGED", rule_label: "title cambiado",
    before_val: "Máster", after_val: "Máster online", detail: null }],
  ...extra,
})

// Lo que devuelve el servidor: los recuentos son los mismos con cualquier filtro.
const counts = { critical: 1, warning: 3, info: 7, all: 11 }
const pending = { critical: 1, warning: 2, info: 4, all: 7 }
const reply = (changes: unknown[]) => ({ changes, counts, counts_pending: pending, total: changes.length, truncated: false })

function Harness({ clientId, initial }: { clientId?: number; initial: ChangeListFilters }) {
  const [filters, setFilters] = useState(initial)
  return <WebChangesList clientId={clientId} filters={filters} onFiltersChange={setFilters} showClient={clientId === undefined} />
}

function setup(clientId: number | null = 7, initial: ChangeListFilters = { severity: "all", pending: true }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><Harness clientId={clientId ?? undefined} initial={initial} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  perms.write = true
})

it("filters change the request params", async () => {
  api.list.mockResolvedValue(reply([change("c1", "critical")]))
  setup()
  await screen.findByText("title cambiado")
  expect(api.list).toHaveBeenLastCalledWith({ client_id: 7, acknowledged: false, limit: 200 })

  const severity = screen.getByRole("group", { name: "Filtrar por severidad" })
  fireEvent.click(within(severity).getByRole("button", { name: /Críticos/ }))
  await waitFor(() => expect(api.list).toHaveBeenLastCalledWith({ client_id: 7, severity: "critical", acknowledged: false, limit: 200 }))

  fireEvent.click(within(screen.getByRole("group", { name: "Filtrar por estado de revisión" })).getByRole("button", { name: /Todo/ }))
  await waitFor(() => expect(api.list).toHaveBeenLastCalledWith({ client_id: 7, severity: "critical", limit: 200 }))
})

it("counts ignore the active filter and look like a control", async () => {
  api.list.mockResolvedValue(reply([change("c1", "critical")]))
  setup(7, { severity: "critical", pending: true })
  const severity = await screen.findByRole("group", { name: "Filtrar por severidad" })
  await screen.findByText("title cambiado")
  // Con "Críticos" pulsado, los demás siguen diciendo cuántos hay (sin revisar).
  expect(within(severity).getByRole("button", { name: /Críticos/ })).toHaveAttribute("aria-pressed", "true")
  expect(within(severity).getByRole("button", { name: /Avisos/ })).toHaveTextContent("2")
  expect(within(severity).getByRole("button", { name: /Menores/ })).toHaveTextContent("4")
  expect(within(severity).getByRole("button", { name: /Todos/ })).toHaveTextContent("7")
  const state = screen.getByRole("group", { name: "Filtrar por estado de revisión" })
  // Los de estado cuentan dentro de la severidad elegida.
  expect(within(state).getByRole("button", { name: /Sin revisar/ })).toHaveTextContent("1")
  expect(within(state).getByRole("button", { name: /Todo/ })).toHaveTextContent("1")
})

it("acknowledges one change and refetches", async () => {
  api.list.mockResolvedValue(reply([change("c1", "warning")]))
  api.ack.mockResolvedValue({ ...change("c1", "warning"), acknowledged_at: "2026-10-21T08:00:00+00:00" })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Marcar revisado" }))
  await waitFor(() => expect(api.ack).toHaveBeenCalledWith("c1"))
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2))
})

it("acknowledge-all asks first and is scoped to client and severity", async () => {
  api.list.mockResolvedValue(reply([change("c1", "warning")]))
  api.ackAll.mockResolvedValue({ acknowledged: 2 })
  setup(7, { severity: "warning", pending: true })
  fireEvent.click(await screen.findByRole("button", { name: /Marcar estos revisados/ }))
  expect(api.ackAll).not.toHaveBeenCalled()
  // El número sale del servidor (counts_pending), no de lo pintado.
  const confirm = screen.getByRole("group", { name: "Confirmar revisión en bloque" })
  expect(confirm).toHaveTextContent("¿Marcar 2 como revisados?")
  fireEvent.click(within(confirm).getByRole("button", { name: "Sí, marcar" }))
  await waitFor(() => expect(api.ackAll).toHaveBeenCalledWith({ client_id: 7, severity: "warning" }))
})

it("readers see changes but no review controls", async () => {
  perms.write = false
  api.list.mockResolvedValue(reply([change("c1", "critical")]))
  setup()
  await screen.findByText("title cambiado")
  expect(screen.queryByRole("button", { name: "Marcar revisado" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Marcar todo revisado/ })).not.toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: "Ver detalle" })[0]).toHaveAttribute("href", "/web/cambios/c1")
})

it("summarises a layout-only change with its size", async () => {
  api.list.mockResolvedValue(reply([change("c2", "info", {
    items: [{ id: "h", kind: "html", field: "raw_html", severity: "info", rule_code: "HTML_CHANGED", rule_label: "cambió el HTML",
      before_val: null, after_val: null, detail: { added: 14, removed: 9, after_lines: 3837 } }],
  })]))
  setup(null)
  expect(await screen.findByText("Solo maquetación · +14/−9 líneas de 3.837")).toBeInTheDocument()
  expect(screen.getByText("Ni el texto visible ni el SEO se movieron.")).toBeInTheDocument()
  // En la lista global cada fila dice de qué cliente es.
  expect(screen.getByRole("link", { name: "Fit" })).toHaveAttribute("href", "/clients/7?tab=web")
  expect(api.list).toHaveBeenLastCalledWith({ acknowledged: false, limit: 200 })
})

it("an empty pending list says what is left in the history", async () => {
  api.list.mockResolvedValue(reply([]))
  setup()
  expect(await screen.findByText("No queda nada sin revisar.")).toBeInTheDocument()
  expect(screen.getByText(/11 ya revisados siguen en el histórico/)).toBeInTheDocument()
})
