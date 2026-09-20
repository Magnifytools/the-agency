import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { NotificationBell } from "./notification-bell"

const api = vi.hoisted(() => ({ list: vi.fn(), unread: vi.fn(), read: vi.fn(), readAll: vi.fn(), generate: vi.fn(), incidents: vi.fn(), count: vi.fn(), decide: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock("@/lib/api", () => ({
  notificationsApi: { list: api.list, unreadCount: api.unread, markRead: api.read, markAllRead: api.readAll, generateChecks: api.generate },
  api: { get: vi.fn(), post: vi.fn() },
}))
vi.mock("@/lib/incidents-api", async importOriginal => ({
  ...await importOriginal<object>(),
  incidentsApi: { list: api.incidents, count: api.count, decide: api.decide },
}))

beforeEach(() => {
  vi.clearAllMocks()
  api.count.mockResolvedValue({ count: 1 })
  api.unread.mockResolvedValue({ count: 2 })
  api.list.mockResolvedValue([])
  api.incidents.mockResolvedValue({ items: [{ id: 41, revision: 1, state: "active", severity: "warning", title: "Revisar espera", message: "Esperamos respuesta", href: "/tasks?task=8" }], next_cursor: null })
})

function show(onNavigate?: () => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><NotificationBell onNavigate={onNavigate} /><Routes><Route path="/tasks" element={<p>Tarea abierta</p>} /></Routes></MemoryRouter></QueryClientProvider>)
}

it("opens canonical incidents without producing checks or marking them read", async () => {
  const closeAccount = vi.fn()
  show(closeAccount)
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Alertas y actividad" }))
  expect(await screen.findByText("Revisar espera")).toBeInTheDocument()
  expect(screen.getByLabelText("1 alertas pendientes")).toBeInTheDocument()
  expect(api.generate).not.toHaveBeenCalled()
  await user.click(screen.getByRole("link", { name: /Revisar espera/ }))
  expect(await screen.findByText("Tarea abierta")).toBeInTheDocument()
  expect(api.read).not.toHaveBeenCalled()
  expect(api.decide).not.toHaveBeenCalled()
  expect(closeAccount).toHaveBeenCalledOnce()
})

it("distinguishes failed activity reads from an empty inbox and supports keyboard close", async () => {
  api.list.mockRejectedValueOnce(new Error("offline"))
  show()
  const user = userEvent.setup()
  const trigger = screen.getByRole("button", { name: "Alertas y actividad" })
  await user.click(trigger)
  await user.click(screen.getByRole("button", { name: /Actividad/ }))
  expect(await screen.findByText(/No se pudo cargar la actividad/)).toBeInTheDocument()
  expect(screen.queryByText("Sin actividad reciente.")).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByText("Sin actividad reciente.")).toBeInTheDocument()
  await user.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(trigger).toHaveFocus()
})
