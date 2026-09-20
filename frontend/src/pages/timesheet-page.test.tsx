import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import TimesheetPage from "./timesheet-page"

const api = vi.hoisted(() => ({
  weekly: vi.fn(), list: vi.fn(), assigned: vi.fn(), adminTimers: vi.fn(),
  byClient: vi.fn(), byProject: vi.fn(), active: vi.fn(), start: vi.fn(), stop: vi.fn(),
  clients: vi.fn(), projects: vi.fn(), update: vi.fn(), exportCsv: vi.fn(),
}))
const auth = vi.hoisted(() => ({ canWriteTime: true }))

vi.mock("@/lib/api", () => ({
  timeEntriesApi: { weekly: api.weekly, list: api.list, adminTimers: api.adminTimers, byClient: api.byClient, byProject: api.byProject, update: api.update, exportCsv: api.exportCsv },
  tasksApi: { listAll: api.assigned }, timerApi: { active: api.active, start: api.start, stop: api.stop },
  clientsApi: { listAll: api.clients }, projectsApi: { listAll: api.projects },
}))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 }, isAdmin: false, hasPermission: (_module: string, write?: boolean) => write ? auth.canWriteTime : true }) }))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => "2026-09-20" }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><TimesheetPage /></QueryClientProvider>)
  return client
}

describe("TimesheetPage recovery", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    auth.canWriteTime = true
    api.weekly.mockResolvedValue({ days: [], users: [] })
    api.list.mockResolvedValue([])
    api.assigned.mockResolvedValue([])
    api.adminTimers.mockResolvedValue([])
    api.byClient.mockResolvedValue([])
    api.byProject.mockResolvedValue([])
    api.active.mockResolvedValue(null)
    api.clients.mockResolvedValue([])
    api.projects.mockResolvedValue([])
  })

  it("does not present a failed today query as zero records", async () => {
    api.list.mockRejectedValueOnce(new Error("offline"))
    show()
    await screen.findByText("No se pudo cargar los registros de hoy.")
    expect(screen.queryByText("Sin registros hoy")).not.toBeInTheDocument()
    expect(screen.getByText(/registros de hoy no disponibles/)).toBeInTheDocument()
  })

  it.each([
    ["Por Cliente", "No se pudo cargar el informe por cliente.", "Sin datos por cliente", "byClient"],
    ["Por Proyecto", "No se pudo cargar el informe por proyecto.", "Sin datos por proyecto", "byProject"],
  ] as const)("separates a failed %s report from an empty report", async (tab, message, empty, method) => {
    api[method].mockRejectedValueOnce(new Error("offline"))
    show()
    fireEvent.click(screen.getByRole("button", { name: tab }))
    await screen.findByText(message)
    expect(screen.queryByText(empty)).not.toBeInTheDocument()
    api[method].mockResolvedValueOnce([])
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await screen.findByText(empty)
  })

  it("does not render timer or entry editing actions for a timesheet reader", async () => {
    auth.canWriteTime = false
    api.list.mockResolvedValue([{ id: 5, minutes: 15, notes: "Consulta", task_id: null }])
    show()
    await screen.findByText("Consulta")
    expect(screen.queryByText("Iniciar")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Editar registro" })).not.toBeInTheDocument()
    expect(api.assigned).not.toHaveBeenCalled()
  })

  it("keeps entry editing available to a timesheet writer", async () => {
    api.list.mockResolvedValue([{ id: 5, minutes: 15, notes: "Consulta", task_id: null }])
    show()
    await screen.findByText("Consulta")
    expect(screen.getByRole("button", { name: "Editar registro" })).toBeInTheDocument()
  })
})
