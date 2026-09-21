import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, it, vi } from "vitest"

import SettingsPage from "./settings-page"

const auth = vi.hoisted(() => ({ isAdmin: false, user: { id: 12, role: "member", preferences: {} } }))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: auth.user, isAdmin: auth.isAdmin, hasPermission: () => false, refreshUser: vi.fn() }),
}))
vi.mock("@/components/communication-schedules", () => ({ CommunicationSchedules: () => <div>Avisos</div> }))
vi.mock("@/components/job-runtime-status", () => ({ JobRuntimeStatusPanel: () => <div>Procesos programados</div> }))
vi.mock("@/lib/api", () => ({
  usersApi: { update: vi.fn() },
  categoriesApi: { list: vi.fn() },
  myWeekApi: { listHolidays: vi.fn(), createHoliday: vi.fn(), deleteHoliday: vi.fn() },
  calendarApi: { getStatus: vi.fn().mockResolvedValue({ connected: false }), getAuthUrl: vi.fn(), disconnect: vi.fn(), sync: vi.fn() },
}))

it("does not render the scheduled-process panel or anchor for a member", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  expect(screen.getAllByText("Avisos")).not.toHaveLength(0)
  expect(screen.queryByText("Procesos programados")).not.toBeInTheDocument()
  expect(document.getElementById("scheduled-processes")).toBeNull()
  expect(document.getElementById("operational-usage")).toBeNull()
})
