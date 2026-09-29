import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ClientDetailPage from "./client-detail-page"

const mocks = vi.hoisted(() => ({
  enabled: new Set(["tasks", "timesheet", "digests", "communications", "reports", "resources", "billing"]),
  permissions: new Set(["tasks", "timesheet", "projects", "digests", "communications", "reports", "billing"]),
  writePermissions: new Set<string>(),
  admin: false,
  summary: vi.fn(),
  projects: vi.fn(),
  time: vi.fn(),
  health: vi.fn(),
}))

vi.mock("@/lib/hidden-modules", () => ({ isEnabled: (module: string) => mocks.enabled.has(module) }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: mocks.admin, hasPermission: (module: string, write = false) => write ? mocks.writePermissions.has(module) : mocks.permissions.has(module) }),
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
  const tree = () => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/clients/5?tab=${tab}`]}>
        <Routes><Route path="/clients/:id" element={<ClientDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
  const view = render(tree())
  return { ...view, client, refresh: () => view.rerender(tree()) }
}

describe("client detail areas", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.enabled = new Set(["tasks", "timesheet", "digests", "communications", "reports", "resources", "billing"])
    mocks.permissions = new Set(["clients", "tasks", "timesheet", "projects", "digests", "communications", "reports", "billing"])
    mocks.writePermissions = new Set(["clients", "tasks", "timesheet", "projects", "digests", "communications", "reports", "billing"])
    mocks.admin = false
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

  it("labels an internal client in its detail header", async () => {
    mocks.summary.mockResolvedValueOnce({ ...summary, client: { ...summary.client, is_internal: true } })
    show("ficha")
    expect(await screen.findByText("Interno")).toBeInTheDocument()
  })

  it("hides the financial what-if action while finance is disabled", async () => {
    show("ficha")
    await screen.findByText("FichaTab")
    expect(screen.queryByRole("button", { name: "¿Y si pierdo este cliente?" })).not.toBeInTheDocument()
  })

  it("offers the financial what-if action when finance is enabled", async () => {
    mocks.admin = true
    mocks.enabled.add("finance")
    show("panel")
    expect(await screen.findByRole("button", { name: "¿Y si pierdo este cliente?" })).toBeInTheDocument()
  })

  it("shows timer time on the Madrid civil day and preserves manual dates", async () => {
    mocks.time.mockResolvedValueOnce([
      { id: 1, date: "2026-09-21T22:30:00", started_at: "2026-09-21T22:30:00Z", minutes: 30, task_title: "Timer", notes: null, user_name: null },
      { id: 2, date: "2026-09-21T00:00:00", started_at: null, minutes: 15, task_title: "Manual", notes: null, user_name: null },
    ])
    show("tiempo")
    expect(await screen.findByText("Timer")).toBeInTheDocument()
    expect(screen.getByText("Manual")).toBeInTheDocument()
    expect(screen.getByText("22/9/2026")).toBeInTheDocument()
    expect(screen.getByText("21/9/2026")).toBeInTheDocument()
  })

  it("names business intelligence actions and associates its edit fields", async () => {
    show("panel")
    await userEvent.click(await screen.findByRole("button", { name: "Editar inteligencia de negocio" }))
    expect(screen.getByRole("combobox", { name: "Modelo de negocio" })).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "AOV (€)" })).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Conversión (%)" })).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "LTV (€)" })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "Madurez SEO" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Guardar inteligencia de negocio" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Cancelar edición de inteligencia de negocio" }))
    expect(screen.getByRole("button", { name: "Editar inteligencia de negocio" })).toBeInTheDocument()
  })

  it("keeps business intelligence read-only for a client reader", async () => {
    mocks.writePermissions.delete("clients")
    show("panel")

    expect(await screen.findByText("Inteligencia de Negocio")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Editar inteligencia de negocio" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Guardar inteligencia de negocio" })).not.toBeInTheDocument()
  })

  it("does not submit business intelligence after client write access is revoked", async () => {
    const view = show("panel")
    await userEvent.click(await screen.findByRole("button", { name: "Editar inteligencia de negocio" }))
    mocks.writePermissions.delete("clients")
    view.refresh()

    expect(screen.getByRole("combobox", { name: "Modelo de negocio" })).toBeDisabled()
    expect(screen.getByRole("spinbutton", { name: "AOV (€)" })).toBeDisabled()
    expect(screen.queryByRole("button", { name: "Guardar inteligencia de negocio" })).not.toBeInTheDocument()
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

  it("keeps the client ficha while task and time projections are unavailable", async () => {
    mocks.permissions.delete("tasks")
    mocks.permissions.delete("timesheet")
    mocks.summary.mockResolvedValue({
      ...summary, tasks: null, total_tasks: null,
      total_tracked_minutes: null, total_estimated_minutes: null, total_actual_minutes: null,
    })
    show("tiempo")

    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Acme" })).toBeInTheDocument()
    expect(screen.queryByText("Total tareas")).not.toBeInTheDocument()
    expect(screen.queryByText("Tiempo tracked")).not.toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "Tiempo" })).not.toBeInTheDocument()
    expect(mocks.time).not.toHaveBeenCalled()
  })

  it("hides cached task and time details as soon as permissions change", async () => {
    mocks.summary.mockResolvedValue({
      ...summary,
      tasks: [{ id: 8, title: "Trabajo privado", status: "pending" }],
      total_tasks: 1, total_tracked_minutes: 30,
    })
    const view = show("tareas")
    expect(await screen.findByRole("button", { name: "Trabajo privado" })).toBeInTheDocument()

    mocks.permissions.delete("tasks")
    mocks.permissions.delete("timesheet")
    view.refresh()

    expect(screen.getByText("FichaTab")).toBeInTheDocument()
    expect(screen.queryByText("Trabajo privado")).not.toBeInTheDocument()
    expect(screen.queryByText("Total tareas")).not.toBeInTheDocument()
    expect(screen.queryByText("Tiempo tracked")).not.toBeInTheDocument()
  })

  it("shows the financial client panel only for an admin while finance is enabled", async () => {
    mocks.admin = true
    mocks.enabled.add("finance")
    const view = show("panel")
    expect(await screen.findByText("Dashboard")).toBeInTheDocument()

    mocks.admin = false
    view.refresh()
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "¿Y si pierdo este cliente?" })).not.toBeInTheDocument()
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
    expect(await screen.findByText("81 puntos; no sustituye las condiciones anteriores.")).toBeInTheDocument()

    mocks.health.mockRejectedValueOnce({ response: { status: 403 } })
    await act(async () => { await client.invalidateQueries({ queryKey: ["client-health", 5] }) })
    expect(await screen.findByText("No se pudo cargar la salud del cliente.")).toBeInTheDocument()
    expect(screen.queryByText("81 puntos; no sustituye las condiciones anteriores.")).not.toBeInTheDocument()

    mocks.health.mockResolvedValueOnce(health)
    await userEvent.click(screen.getByRole("button", { name: "Reintentar salud" }))
    expect(await screen.findByText("81 puntos; no sustituye las condiciones anteriores.")).toBeInTheDocument()
  })

  it("does not request or render health without current client permission", async () => {
    mocks.permissions.delete("clients")
    mocks.health.mockResolvedValue({ score: 99 })
    show("ficha")

    expect(screen.getByRole("alert")).toHaveTextContent("No tienes acceso a este cliente.")
    expect(mocks.summary).not.toHaveBeenCalled()
    expect(mocks.health).not.toHaveBeenCalled()
    expect(screen.queryByText("99 puntos; no sustituye las condiciones anteriores.")).not.toBeInTheDocument()
  })

  it("removes cached client details immediately when client read access is revoked", async () => {
    const view = show("ficha")
    expect(await screen.findByText("FichaTab")).toBeInTheDocument()
    mocks.permissions.delete("clients")
    view.refresh()

    expect(screen.getByRole("alert")).toHaveTextContent("No tienes acceso a este cliente.")
    expect(screen.queryByText("FichaTab")).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Acme" })).not.toBeInTheDocument()
    expect(mocks.summary).toHaveBeenCalledTimes(1)
  })

  it("removes cached task health observations after task access is revoked", async () => {
    const fullHealth = {
      score: 70, risk_level: "warning", enough_information: true,
      available_source_count: 1, available_weight: 20,
      factors: { communication: null, tasks: 10, digests: null, profitability: null, followups: null },
      observations: { communication: "Fuente no disponible", tasks: "Tres tareas vencidas", digests: "Fuente no disponible", profitability: "Fuente no disponible", followups: "Fuente no disponible" },
      risk_signals: ["Tres tareas vencidas"],
    }
    const redactedHealth = {
      ...fullHealth, score: null, available_source_count: 0, available_weight: 0,
      factors: { ...fullHealth.factors, tasks: null },
      observations: { ...fullHealth.observations, tasks: "Fuente no disponible" },
      risk_signals: [],
    }
    mocks.health.mockResolvedValueOnce(fullHealth).mockResolvedValueOnce(redactedHealth)
    const view = show("ficha")
    expect(await screen.findAllByText("Tres tareas vencidas")).not.toHaveLength(0)

    mocks.permissions.delete("tasks")
    view.refresh()
    expect(screen.queryByText("Tres tareas vencidas")).not.toBeInTheDocument()
    await waitFor(() => expect(mocks.health).toHaveBeenCalledTimes(2))
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
