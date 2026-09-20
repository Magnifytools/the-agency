import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import SettingsPage from "./settings-page"

const api = vi.hoisted(() => ({ categories: vi.fn(), holidays: vi.fn(), deleteCategory: vi.fn(), deleteHoliday: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1, role: "admin", preferences: {} }, isAdmin: true, hasPermission: () => true, refreshUser: vi.fn() }) }))
vi.mock("@/components/communication-schedules", () => ({ CommunicationSchedules: () => <div /> }))
vi.mock("@/components/job-runtime-status", () => ({ JobRuntimeStatusPanel: () => <div /> }))
vi.mock("@/lib/api", () => ({
  usersApi: { update: vi.fn() },
  categoriesApi: { list: api.categories, create: vi.fn(), update: vi.fn(), delete: api.deleteCategory },
  myWeekApi: { listHolidays: api.holidays, createHoliday: vi.fn(), deleteHoliday: api.deleteHoliday },
  calendarApi: { getStatus: vi.fn().mockResolvedValue({ connected: false }), getAuthUrl: vi.fn(), disconnect: vi.fn(), sync: vi.fn() },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  return client
}

describe("Settings safe catalogs", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.categories.mockResolvedValue([{ id: 4, name: "SEO", default_minutes: 60 }])
    api.holidays.mockResolvedValue([{ id: 8, name: "Festivo local", date: "2026-09-21", region: null, locality: null }])
  })

  it("hides stale categories, closes a pending delete and recovers an empty success", async () => {
    const client = show()
    expect(await screen.findByText("SEO")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Eliminar categoría SEO" }))
    expect(screen.getByRole("heading", { name: "Eliminar categoría" })).toBeInTheDocument()
    api.categories.mockRejectedValueOnce(new Error("offline"))
    await act(async () => { await client.invalidateQueries({ queryKey: ["task-categories"] }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar las categorías")
    expect(screen.queryByText("SEO")).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Eliminar categoría" })).not.toBeInTheDocument()
    expect(api.deleteCategory).not.toHaveBeenCalled()
    api.categories.mockResolvedValueOnce([])
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("No hay categorías configuradas")).toBeInTheDocument()
  })

  it("does not turn a holiday failure into an empty catalog and retries only holidays", async () => {
    const client = show()
    expect(await screen.findByText("Festivo local")).toBeInTheDocument()
    api.holidays.mockRejectedValueOnce(new Error("offline"))
    await act(async () => { await client.invalidateQueries({ queryKey: ["holidays"] }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los festivos")
    expect(screen.queryByText("Festivo local")).not.toBeInTheDocument()
    expect(screen.queryByText("No hay festivos configurados")).not.toBeInTheDocument()
    const categoryCalls = api.categories.mock.calls.length
    api.holidays.mockResolvedValueOnce([])
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("No hay festivos configurados")).toBeInTheDocument()
    expect(api.categories).toHaveBeenCalledTimes(categoryCalls)
  })
})
