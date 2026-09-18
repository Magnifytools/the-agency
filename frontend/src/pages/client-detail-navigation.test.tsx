import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ClientDetailPage from "./client-detail-page"

const mocks = vi.hoisted(() => ({
  enabled: new Set(["digests", "communications", "reports", "resources", "billing"]),
  permissions: new Set(["tasks", "projects", "digests", "communications", "reports", "billing"]),
  summary: vi.fn(),
  projects: vi.fn(),
}))

vi.mock("@/lib/hidden-modules", () => ({ isEnabled: (module: string) => mocks.enabled.has(module) }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: false, hasPermission: (module: string) => mocks.permissions.has(module) }),
}))
vi.mock("@/lib/api", () => ({
  clientsApi: { summary: mocks.summary, recentTimeEntries: vi.fn().mockResolvedValue([]), whatIf: vi.fn() },
  projectsApi: { listAll: mocks.projects },
  holdedApi: { config: vi.fn(), clientInvoices: vi.fn() },
  clientHealthApi: { get: vi.fn().mockResolvedValue(null) },
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
vi.mock("@/components/tasks/task-panel", () => ({ TaskPanel: () => null }))

const summary = {
  client: { id: 5, name: "Acme", status: "active", engine_project_id: null },
  tasks: [], total_tasks: 0, total_tracked_minutes: 0,
  total_estimated_minutes: 0, total_actual_minutes: 0,
}

function show(tab: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/clients/5?tab=${tab}`]}>
        <Routes><Route path="/clients/:id" element={<ClientDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("client detail areas", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.enabled = new Set(["digests", "communications", "reports", "resources", "billing"])
    mocks.permissions = new Set(["tasks", "projects", "digests", "communications", "reports", "billing"])
    mocks.summary.mockResolvedValue(summary)
    mocks.projects.mockResolvedValue([])
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
})
