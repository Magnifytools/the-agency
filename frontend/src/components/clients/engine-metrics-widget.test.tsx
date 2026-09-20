import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { EngineMetricsWidget } from "./engine-metrics-widget"
const mocks = vi.hoisted(() => ({ isAdmin: false, sync: vi.fn(), error: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: mocks.isAdmin }) }))
vi.mock("@/lib/api", () => ({ engineApi: { triggerSync: mocks.sync } }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: mocks.error } }))
const client = { id: 1, engine_project_id: 2, engine_metrics_synced_at: "2026-09-20T12:00:00", engine_content_count: null, engine_keyword_count: null, engine_avg_position: null, engine_clicks_30d: null, engine_impressions_30d: null } as never
function show() { return render(<QueryClientProvider client={new QueryClient()}><EngineMetricsWidget client={client} /></QueryClientProvider>) }
beforeEach(() => { vi.clearAllMocks(); mocks.isAdmin = false })
describe("EngineMetricsWidget", () => {
 it("interprets a timestamp without offset as UTC", () => {
   vi.useFakeTimers()
   vi.setSystemTime(new Date("2026-09-20T14:00:00Z"))
   try {
     show()
     expect(screen.getByText("Datos sincronizados hace 2h")).toBeInTheDocument()
   } finally {
     vi.useRealTimers()
   }
 })
 it("does not offer refresh to a member", () => { show(); expect(screen.queryByLabelText("Sincronizar Engine")).not.toBeInTheDocument() })
 it("does not call a zero-client unconfigured sync a success", async () => { mocks.isAdmin = true; mocks.sync.mockResolvedValueOnce({ synced: 0, failed: 0, detail: "not configured" }); show(); fireEvent.click(screen.getByLabelText("Sincronizar Engine")); await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Engine no está configurado.")) })
 it("reports a failed refresh", async () => { mocks.isAdmin = true; mocks.sync.mockRejectedValueOnce(new Error("offline")); show(); fireEvent.click(screen.getByLabelText("Sincronizar Engine")); await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("No se pudo sincronizar Engine.")) })
})
