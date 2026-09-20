import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { EngineSeoTab } from "./engine-seo-tab"

const mocks = vi.hoisted(() => ({ isAdmin: false, sync: vi.fn(), toastError: vi.fn(), toastSuccess: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: mocks.isAdmin }) }))
vi.mock("@/lib/api", () => ({ engineApi: { getConfig: vi.fn().mockResolvedValue({}), triggerSync: mocks.sync, listProjects: vi.fn() }, clientsApi: { update: vi.fn() } }))
vi.mock("sonner", () => ({ toast: { success: mocks.toastSuccess, error: mocks.toastError } }))

const client = (overrides = {}) => ({
  id: 7, name: "Acme", engine_project_id: 99, engine_metrics_synced_at: "2026-09-20T12:00:00Z",
  engine_summary_data: { project_id: 99, project_name: "Acme", domain: "acme.test", content_count: 1, indexed_count: 1, inspected_count: 2, observed_keyword_count: 0, keywords_top3: 0, keywords_top10: 0, keywords_top20: 0, clicks_30d: null, impressions_30d: null, clicks_previous_30d: 0, impressions_previous_30d: 0, clicks_change_pct: 0, avg_position: null, trend: "stable", seo_health: null, recent_changes: [], as_of: "2026-09-20", period_start: "2026-08-22", previous_period_start: "2026-07-23", ranking_device: "desktop" },
  engine_alerts_data: null,
  ...overrides,
}) as never

function show(value = client()) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><EngineSeoTab client={value} /></QueryClientProvider>)
}

beforeEach(() => { vi.clearAllMocks(); mocks.isAdmin = false })

describe("EngineSeoTab", () => {
  it("does not turn missing metrics or alerts into healthy zeros and describes the snapshot range", async () => {
    show()
    expect(await screen.findByText("Alertas no disponibles en la última sincronización.")).toBeInTheDocument()
    expect(screen.queryByText("No hay alertas SEO en los datos sincronizados")).not.toBeInTheDocument()
    expect(screen.getByText(/Datos de 2026-08-22 a 2026-09-20/)).toBeInTheDocument()
    expect(screen.getByText("Sin observaciones de ranking en este período.")).toBeInTheDocument()
    expect(screen.getAllByText("-").length).toBeGreaterThanOrEqual(2)
  })

  it("does not claim ranking coverage for a legacy snapshot without period metadata", async () => {
    show(client({ engine_summary_data: { project_id: 99, project_name: "Acme", domain: "acme.test", content_count: 1, indexed_count: 1, keywords_top3: 0, keywords_top10: 0, keywords_top20: 0, clicks_30d: 1, impressions_30d: 1, clicks_previous_30d: 0, impressions_previous_30d: 0, clicks_change_pct: 0, avg_position: null, trend: "stable", seo_health: null, recent_changes: [] } }))
    expect(await screen.findByText("Visibilidad SEO")).toBeInTheDocument()
    expect(screen.queryByText(/keywords con observación en el período/)).not.toBeInTheDocument()
  })

  it("only treats an explicit empty alert snapshot as healthy", async () => {
    show(client({ engine_alerts_data: { alerts: [] } }))
    expect(await screen.findByText("No hay alertas SEO en los datos sincronizados")).toBeInTheDocument()
  })
  it("hides manual sync for a member even when the linked snapshot is absent", () => {
    show(client({ engine_summary_data: null, engine_metrics_synced_at: null }))
    expect(screen.getByText("Datos pendientes de sincronización")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Sincronizar ahora" })).not.toBeInTheDocument()
  })

  it("reports partial sync without claiming success", async () => {
    mocks.isAdmin = true
    mocks.sync.mockResolvedValue({ synced: 0, failed: 1 })
    show()
    await screen.findByText("Visibilidad SEO")
    await screen.getByRole("button", { name: /Sincronizar ahora|Sincronizar/ }).click()
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith(expect.stringMatching(/incompleta/)))
    expect(mocks.toastSuccess).not.toHaveBeenCalled()
  })

})
