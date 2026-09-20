import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ClientDetailPage from "./client-detail-page"

const mocks = vi.hoisted(() => ({
  enabled: new Set(["digests", "communications", "reports", "resources", "billing"]),
  permissions: new Set(["tasks", "projects", "digests", "communications", "reports", "billing"]),
  summary: vi.fn(),
  projects: vi.fn(),
  time: vi.fn(),
  health: vi.fn(),
}))

vi.mock("@/lib/hidden-modules", () => ({ isEnabled: (module: string) => mocks.enabled.has(module) }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: false, hasPermission: (module: string) => mocks.permissions.has(module) }),
}))
vi.mock("@/lib/api", () => ({
  clientsApi: { summary: mocks.summary, recentTimeEntries: mocks.time, whatIf: vi.fn() },
  projectsApi: { listAll: mocks.projects },
  holdedApi: { config: vi.fn(), clientInvoices: vi.fn() },
  clientHealthApi: { get: mocks.health },
  engineApi: { getConfig: vi.fn().mockResolvedValue({}) },
}))

vi.mock("@/components/clients/ficha-tab", () => ({ FichaTab: () => <div>FichaTab</div> }))
vi.mock("@/components/clients/activity-timeline", () => ({ ActivityTimeline: () => <div>ActivityTimeline</div> }))
vi.mock("@/components/clients/client-ai-advisor", () => ({ ClientAiAdvisor: () => <div>ClientAiAdvisor</div> }))
vi.mock("@/components/clients/contact-list", () => ({ ContactList: () => <div>ContactList</div> }))
vi.mock("@/components/clients/resource-list", () => ({ ResourceList: () => <div>ResourceList</div> }))
vi.mock("@/components/clients/billing-tab", () => ({ BillingTab: () => <div>BillingTab</div> }))
vi.mock("@/components/clients/client-dashboard-tab", () => ({ ClientDashboardTab: () => <div>Dashboard</div> }))
vi.mock("@/components/clients/client-reports-tab", () => ({ ClientReportsTab: () => <div>Reports</div> }))
vi.mock("@/components/clients/client-settings-tab", () => ({ ClientSettingsTab: () => <div>Settings</div> }))
vi.mock("@/components/clients/engine-metrics-widget", () => ({ EngineMetricsWidget: () => null }))
vi.mock("@/components/clients/engine-seo-tab", () => ({ EngineSeoTab: () => <div>SEO</div> }))
vi.mock("@/components/communications/communication-list", () => ({ CommunicationList: () => <div>Communications</div> }))
vi.mock("@/components/timer/timer-button", () => ({ TimerButton: () => null }))
vi.mock("@/components/timer/time-log-dialog", () => ({ TimeLogDialog: () => null }))
vi.mock("@/components/tasks/task-panel", () => ({
  TaskPanel: ({ open, taskId }: { open: boolean; taskId: number | null }) => open ? <div role="dialog">Tarea abierta {taskId}</div> : null,
}))

const summary = {
  client: { id: 5, name: "Acme", status: "active", engine_project_id: null },
  tasks: [], total_tasks: 0, total_tracked_minutes: 0,
  total_estimated_minutes: 0, total_actual_minutes: 0,
}

function show(tab: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/clients/5?tab=${tab}`]}>
        <Routes><Route path="/clients/:id" element={<ClientDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, client }
}

describe("client detail areas", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.enabled = new Set(["digests", "communications", "reports", "resources", "billing"])
    mocks.permissions = new Set(["clients", "tasks", "projects", "digests", "communications", "reports", "billing"])
    mocks.summary.mockResolvedValue(summary)
    mocks.projects.mockResolvedValue([])
    mocks.time.mockResolvedValue([])
    mocks.health.mockResolvedValue(null)
  })

  it("keeps a legacy activity URL inside the four-area navigation", async () => {
    show("actividad")
    expect(await screen.findByText("ActivityTimeline")).toBeInTheDocument()
    const nav = screen.getByRole("navigation", { name: "Áreas del cliente" })
    expect(nav).toHaveTextContent("Resumen")
    expect(nav).toHaveTextContent("Trabajo")
    expect(nav).toHaveTextContent("Resúmenes y archivos")
    expect(nav).toHaveTextContent("Ajustes")
    expect(screen.getByLabelText("Área del cliente")).toHaveValue("resumen")
  })

  it("falls back safely when a legacy URL points to a hidden module", async () => {
    mocks.enabled.delete("communications")
    show("comunicaciones")
    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    expect(screen.queryByText("Communications")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Área del cliente")).toHaveValue("resumen")
  })

  it("does not expose or query project work without project permission", async () => {
    mocks.permissions.delete("projects")
    show("proyectos")
    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    await waitFor(() => expect(mocks.projects).not.toHaveBeenCalled())
    expect(screen.queryByRole("option", { name: "Proyectos" })).not.toBeInTheDocument()
  })

  it("shows a retry when the client summary fails", async () => {
    mocks.summary.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(summary)
    show("ficha")

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar la ficha")
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    expect(mocks.summary).toHaveBeenCalledTimes(2)
  })

  it("hides cached health after an error until a fresh response succeeds", async () => {
    const health = {
      score: 81, risk_level: "healthy", enough_information: true,
      available_source_count: 3, available_weight: 65,
      factors: { communication: 20, tasks: 20, digests: 12, profitability: 16, followups: 13 },
      observations: { communication: "Comunicación", tasks: "Tareas", digests: "Resúmenes", profitability: "Rentabilidad", followups: "Seguimiento" },
      risk_signals: [],
    }
    mocks.health.mockResolvedValueOnce(health)
    const { client } = show("ficha")
    expect(await screen.findByText("81/100")).toBeInTheDocument()

    mocks.health.mockRejectedValueOnce({ response: { status: 403 } })
    await act(async () => { await client.invalidateQueries({ queryKey: ["client-health", 5] }) })
    expect(await screen.findByText("No se pudo cargar la salud del cliente.")).toBeInTheDocument()
    expect(screen.queryByText("81/100")).not.toBeInTheDocument()

    mocks.health.mockResolvedValueOnce(health)
    await userEvent.click(screen.getByRole("button", { name: "Reintentar salud" }))
    expect(await screen.findByText("81/100")).toBeInTheDocument()
  })

  it("does not request or render health without current client permission", async () => {
    mocks.permissions.delete("clients")
    mocks.health.mockResolvedValue({ score: 99 })
    show("ficha")

    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    expect(mocks.health).not.toHaveBeenCalled()
    expect(screen.queryByText("99/100")).not.toBeInTheDocument()
  })

  it("keeps summaries useful when optional output modules are hidden", async () => {
    mocks.enabled = new Set(["digests"])
    show("resumenes")

    const link = await screen.findByRole("link", { name: "Abrir resúmenes de Acme" })
    expect(link).toHaveAttribute("href", "/digests?client_id=5")
    expect(screen.getByLabelText("Área del cliente")).toHaveValue("outputs")
  })

  it("falls back without a link when a saved summaries URL targets a hidden module", async () => {
    mocks.enabled.delete("digests")
    show("resumenes")

    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Abrir resúmenes/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "Resúmenes" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("Área del cliente")).toHaveValue("resumen")
  })
  it("shows task rows without depending on inactive project or time queries", async () => {
    mocks.summary.mockResolvedValue({ ...summary, tasks: [{ id: 8, title: "Trabajo visible", status: "pending" }] })
    show("tareas")
    expect(await screen.findByRole("button", { name: "Trabajo visible" })).toBeInTheDocument()
    expect(mocks.projects).not.toHaveBeenCalled()
    expect(mocks.time).not.toHaveBeenCalled()
    expect(screen.queryByText("Total tareas")).not.toBeInTheDocument()
  })

  it("puts active work first and keeps the complete history keyboard-accessible", async () => {
    mocks.summary.mockResolvedValue({
      ...summary,
      tasks: [
        { id: 57, title: "Terminada antigua", status: "completed", estimated_minutes: 30, actual_minutes: 40 },
        { id: 12, title: "Esperando material", status: "waiting", estimated_minutes: 15, actual_minutes: 5 },
        { id: 31, title: "Terminada reciente", status: "completed", estimated_minutes: null, actual_minutes: null },
        { id: 8, title: "Trabajo activo", status: "in_progress", estimated_minutes: 60, actual_minutes: 20 },
      ],
    })
    show("tareas")

    expect(await screen.findByRole("table", { name: "Trabajo activo" })).toHaveTextContent("Esperando material")
    expect(screen.getByRole("table", { name: "Trabajo activo" })).toHaveTextContent("Trabajo activo")
    expect(screen.getByRole("button", { name: "Terminada antigua", hidden: true })).not.toBeVisible()

    const completedToggle = screen.getByText("Completadas (2)")
    completedToggle.focus()
    await userEvent.keyboard("{Enter}")

    const history = screen.getByRole("table", { name: "Tareas completadas" })
    expect(history).toHaveTextContent("Terminada antigua")
    expect(history).toHaveTextContent("30m")
    expect(history).toHaveTextContent("40m")
    await userEvent.click(screen.getByRole("button", { name: "Terminada antigua" }))
    expect(screen.getByRole("dialog")).toHaveTextContent("Tarea abierta 57")
  })

  it("loads and retries projects independently from the inactive time query", async () => {
    mocks.projects.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([
      { id: 3, name: "Proyecto visible", status: "active", task_count: 1, completed_task_count: 0, progress_percent: 0 },
    ])
    show("proyectos")
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los proyectos")
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByRole("link", { name: "Proyecto visible" })).toHaveAttribute("href", "/projects/3")
    expect(mocks.time).not.toHaveBeenCalled()
  })

  it("shows time failure instead of a false empty history and retries", async () => {
    mocks.time.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([
      { id: 4, date: "2026-09-17T00:00:00", started_at: null, minutes: 45, task_title: "Tiempo visible", notes: "manual" },
    ])
    show("tiempo")
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar el tiempo")
    expect(screen.queryByText("No hay entradas de tiempo")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("Tiempo visible")).toBeInTheDocument()
    expect(mocks.projects).not.toHaveBeenCalled()
  })

})
