import { beforeEach, expect, it, vi } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { CalendarSection } from "./settings-page"

const mocks = vi.hoisted(() => ({ status: vi.fn(), sync: vi.fn(), auth: vi.fn(), disconnect: vi.fn() }))
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock("@/lib/api", () => ({
  calendarApi: { getStatus: mocks.status, sync: mocks.sync, getAuthUrl: mocks.auth, disconnect: mocks.disconnect },
  usersApi: {}, categoriesApi: {}, myWeekApi: {},
}))
vi.mock("@/components/communication-schedules", () => ({ CommunicationSchedules: () => null }))
vi.mock("sonner", () => ({ toast: toasts }))
const connected = { connected: true, connection_status: "connected", last_synced_at: "2026-09-18T08:00:00Z", calendar_id: "primary" }
const revoked = { ...connected, connected: false, connection_status: "reconnect_required" }
function show() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><CalendarSection /></QueryClientProvider>) }
beforeEach(() => { vi.resetAllMocks(); window.history.replaceState({}, "", "/settings"); mocks.status.mockResolvedValue(connected) })

it("offers reconnection for a revoked grant and preserves meetings explicitly", async () => {
  mocks.status.mockResolvedValue(revoked)
  // No OAuth navigation: failed URL retrieval demonstrates the actual button flow.
  mocks.auth.mockRejectedValue(new Error("offline"))
  show()
  expect(await screen.findByText("Necesita reconectar")).toBeInTheDocument()
  expect(screen.getByText(/Las reuniones guardadas se conservan/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Sincronizar ahora" })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reconectar Google Calendar" }))
  await waitFor(() => expect(mocks.auth).toHaveBeenCalledTimes(1))
})

it("refreshes the durable connection state after a failed manual sync", async () => {
  mocks.status.mockResolvedValueOnce(connected).mockResolvedValue(revoked)
  mocks.sync.mockRejectedValue(new Error("needs reconnect"))
  show()
  fireEvent.click(await screen.findByRole("button", { name: "Sincronizar ahora" }))
  expect(await screen.findByRole("button", { name: "Reconectar Google Calendar" })).toBeInTheDocument()
})

it("leaves a transient failure connected and retryable", async () => {
  mocks.sync.mockRejectedValue(new Error("timeout"))
  show()
  fireEvent.click(await screen.findByRole("button", { name: "Sincronizar ahora" }))
  await waitFor(() => expect(mocks.status).toHaveBeenCalledTimes(2))
  expect(screen.getByText("Conectado")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Sincronizar ahora" })).toBeEnabled()
  expect(screen.queryByText("Necesita reconectar")).not.toBeInTheDocument()
})

it("distinguishes an intentional disconnect from expired authorization", async () => {
  mocks.status.mockResolvedValue({ ...revoked, connection_status: "disconnected", calendar_id: null })
  show()
  expect(await screen.findByRole("button", { name: "Conectar Google Calendar" })).toBeInTheDocument()
  expect(screen.queryByText("Necesita reconectar")).not.toBeInTheDocument()
})

it("keeps the calendar anchor available while its status is loading", () => {
  mocks.status.mockReturnValue(new Promise(() => {}))
  show()
  expect(screen.getByText("Cargando estado del calendario…").closest("#calendar")).not.toBeNull()
})

it("offers retry after a status error instead of assuming disconnection", async () => {
  mocks.status.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(revoked)
  show()
  fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }))
  expect(await screen.findByRole("button", { name: "Reconectar Google Calendar" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Conectar Google Calendar" })).not.toBeInTheDocument()
})

it("explains a cancelled Google authorization without treating it as a provider error", async () => {
  window.history.replaceState({}, "", "/settings?calendar=cancelled")
  show()
  await waitFor(() => expect(toasts.info).toHaveBeenCalledWith("Conexión de Google Calendar cancelada"))
  expect(window.location.pathname + window.location.search).toBe("/settings")
})
