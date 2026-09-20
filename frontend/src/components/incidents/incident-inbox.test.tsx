import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { IncidentInbox } from "./incident-inbox"

const incidentsApi = vi.hoisted(() => ({ list: vi.fn(), decide: vi.fn() }))
vi.mock("@/lib/incidents-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/incidents-api")>()),
  incidentsApi,
}))

const incident = {
  id: 31, revision: 4, condition_type: "task_overdue", state: "active", severity: "warning",
  title: "Tarea vencida: Preparar propuesta", message: "El compromiso venció ayer.", href: "/tasks?task=9",
  entity_type: "task", entity_key: "9", created_at: "2026-09-19T08:00:00Z", snoozed_until: null,
  resolved_at: null, resolution_reason: null, dismissal_reason: null,
}

function setup(compact = false) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <MemoryRouter><IncidentInbox userId={7} compact={compact} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  incidentsApi.list.mockResolvedValue({ items: [incident], next_cursor: null })
  incidentsApi.decide.mockResolvedValue({ ...incident, state: "dismissed", revision: 5 })
})

it("shows active incidents and opens their task without deciding them", async () => {
  setup()
  expect(await screen.findByRole("heading", { name: incident.title })).toBeInTheDocument()
  const link = screen.getByRole("link", { name: /abrir/i })
  expect(link).toHaveAttribute("href", "/tasks?task=9")
  expect(incidentsApi.decide).not.toHaveBeenCalled()
})

it("keeps history reachable when the compact inbox has no active incidents", async () => {
  incidentsApi.list.mockResolvedValue({ items: [], next_cursor: null })
  setup(true)
  expect((await screen.findByText("Sin alertas pendientes", { exact: false })).tagName).toBe("P")
  expect(screen.getByRole("link", { name: "Ver alertas" })).toHaveAttribute("href", "/incidents")
})

it("exposes a failed list fetch as a real retry", async () => {
  incidentsApi.list.mockRejectedValueOnce(new Error("offline"))
  setup()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar")
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByRole("heading", { name: incident.title })).toBeInTheDocument()
})

it("reconciles a 409 without replaying the stale decision", async () => {
  incidentsApi.decide.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: { current: { state: "dismissed" } } } } })
  setup()
  await screen.findByRole("heading", { name: incident.title })
  fireEvent.click(screen.getByRole("button", { name: "Descartar" }))
  fireEvent.change(screen.getByLabelText("Motivo para descartar"), { target: { value: "Duplicada" } })
  fireEvent.click(screen.getByRole("button", { name: "Confirmar descarte" }))
  await waitFor(() => expect(incidentsApi.list).toHaveBeenCalledTimes(2))
  expect(incidentsApi.decide).toHaveBeenCalledTimes(1)
})

it("requires a refresh after an uncertain decision result", async () => {
  incidentsApi.decide.mockRejectedValueOnce({ isAxiosError: true, code: "ECONNABORTED" })
  setup()
  await screen.findByRole("heading", { name: incident.title })
  fireEvent.click(screen.getByRole("button", { name: "Descartar" }))
  fireEvent.change(screen.getByLabelText("Motivo para descartar"), { target: { value: "No aplica" } })
  fireEvent.click(screen.getByRole("button", { name: "Confirmar descarte" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo confirmar")
  expect(screen.getByRole("button", { name: "Posponer" })).toBeDisabled()
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Posponer" })).not.toBeDisabled())
  expect(incidentsApi.decide).toHaveBeenCalledTimes(1)
})

it("keeps decisions blocked when the required refresh also fails", async () => {
  incidentsApi.decide.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503 } })
  setup()
  await screen.findByRole("heading", { name: incident.title })
  fireEvent.click(screen.getByRole("button", { name: "Descartar" }))
  fireEvent.change(screen.getByLabelText("Motivo para descartar"), { target: { value: "Servicio caído" } })
  fireEvent.click(screen.getByRole("button", { name: "Confirmar descarte" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo confirmar")
  incidentsApi.list.mockRejectedValueOnce(new Error("offline"))
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }))
  await waitFor(() => expect(screen.getByText(/Sigue bloqueada/)).toBeInTheDocument())
  expect(incidentsApi.decide).toHaveBeenCalledTimes(1)
})

it("uses a short read-only compact inbox and links to the complete page", async () => {
  incidentsApi.list.mockResolvedValue({ items: Array.from({ length: 7 }, (_, index) => ({ ...incident, id: index + 1, title: `Aviso ${index + 1}` })), next_cursor: 7 })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><IncidentInbox userId={7} compact /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText("Aviso 1")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Posponer" })).not.toBeInTheDocument()
  expect(screen.getAllByRole("link")).toHaveLength(6)
  expect(screen.getByRole("link", { name: "Ver todas las alertas" })).toHaveAttribute("href", "/incidents")
})
