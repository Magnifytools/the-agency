import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"

import { JobRuntimeStatusPanel } from "./job-runtime-status"

const mock = vi.hoisted(() => ({ list: vi.fn() }))

vi.mock("@/lib/api", () => ({ jobRuntimeApi: { list: mock.list } }))

const jobs = [
  { key: "running", label: "Tareas recurrentes", description: "Revisa la cola; no confirma entregas.", state: "running", started_at: "2026-09-20T10:00:00Z", last_success_at: "2026-09-20T09:00:00Z", last_failure_at: null, failure_summary: null, paused_reason: null },
  { key: "stale", label: "Resúmenes de clientes", description: null, state: "stale", started_at: null, last_success_at: "2026-09-19T10:00:00Z", last_failure_at: null, failure_summary: "No hay una comprobación reciente.", paused_reason: null },
  { key: "failed", label: "Avisos", description: null, state: "failed", started_at: null, last_success_at: null, last_failure_at: "2026-09-20T09:00:00Z", failure_summary: "No se pudo consultar el calendario.", paused_reason: null },
  { key: "paused", label: "Reconciliación", description: null, state: "paused", started_at: null, last_success_at: null, last_failure_at: null, failure_summary: null, paused_reason: "Mantenimiento programado." },
  { key: "never", label: "Importación", description: null, state: "never", started_at: null, last_success_at: null, last_failure_at: null, failure_summary: null, paused_reason: null },
  { key: "success", label: "Limpieza", description: null, state: "success", started_at: null, last_success_at: "2026-09-20T10:00:00Z", last_failure_at: null, failure_summary: null, paused_reason: null },
] as const

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><JobRuntimeStatusPanel userId={7} /></QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())

it("waits to fetch until the administrator opens the panel and shows each runtime state", async () => {
  mock.list.mockResolvedValue({ jobs })
  show()
  expect(mock.list).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText("Procesos programados"))
  expect(await screen.findByText("Tareas recurrentes")).toBeInTheDocument()
  expect(mock.list).toHaveBeenCalledTimes(1)
  expect(screen.getByText("En curso")).toBeInTheDocument()
  expect(screen.getByText("Requiere revisión")).toBeInTheDocument()
  expect(screen.getByText("Con incidencias")).toBeInTheDocument()
  expect(screen.getByText("Pausada")).toBeInTheDocument()
  expect(screen.getByText("Aún sin ejecutar")).toBeInTheDocument()
  expect(screen.getByText("Comprobado")).toBeInTheDocument()
  expect(screen.getByText("No se pudo consultar el calendario.")).toBeInTheDocument()
  expect(screen.getByText("No hay una comprobación reciente.")).toBeInTheDocument()
  expect(screen.getByText("Mantenimiento programado.")).toBeInTheDocument()
})

it("keeps a real error and supports an explicit retry", async () => {
  mock.list.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ jobs: [] })
  show()
  fireEvent.click(screen.getByText("Procesos programados"))
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar el estado")
  expect(screen.queryByText("No hay procesos programados configurados.")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  await waitFor(() => expect(screen.getByText("No hay procesos programados configurados.")).toBeInTheDocument())
})

it("keeps the last known status visible when a manual refresh fails", async () => {
  mock.list.mockResolvedValueOnce({ jobs: [jobs[5]] }).mockRejectedValueOnce(new Error("offline"))
  show()
  fireEvent.click(screen.getByText("Procesos programados"))
  expect(await screen.findByText("Limpieza")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Actualizar estado" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Se muestran los últimos datos consultados")
  expect(screen.getByText("Limpieza")).toBeInTheDocument()
  expect(screen.getByText(/Último éxito:/)).toBeInTheDocument()
})
