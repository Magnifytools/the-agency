import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import userEvent from "@testing-library/user-event"

import { categoriesApi, holidaysApi, usersApi } from "@/lib/api"
import { HIDDEN_MODULES, setRuntimeHiddenModules } from "@/lib/hidden-modules"
import SettingsPage from "./settings-page"

const auth = vi.hoisted(() => ({ isAdmin: false, user: { id: 12, role: "member", preferences: { shortcuts: { goto_leads: "G+Y" } } } }))

// Estas pruebas tratan un atajo guardado de un módulo OCULTO. El Pipeline ya no
// lo está (28 oct 2026), así que aquí se oculta a propósito.
beforeEach(() => {
  auth.isAdmin = false
  setRuntimeHiddenModules([...HIDDEN_MODULES, "leads"])
})
afterEach(() => setRuntimeHiddenModules([...HIDDEN_MODULES]))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: auth.user, isAdmin: auth.isAdmin, hasPermission: () => false, refreshUser: vi.fn() }),
}))
vi.mock("@/components/communication-schedules", () => ({ CommunicationSchedules: () => <div>Avisos</div> }))
vi.mock("@/components/job-runtime-status", () => ({ JobRuntimeStatusPanel: () => <div>Procesos programados</div> }))
vi.mock("@/lib/api", () => ({
  usersApi: { update: vi.fn() },
  categoriesApi: { list: vi.fn() },
  holidaysApi: { list: vi.fn(), create: vi.fn(), delete: vi.fn() },
  calendarApi: { getStatus: vi.fn().mockResolvedValue({ connected: false }), getAuthUrl: vi.fn(), disconnect: vi.fn(), sync: vi.fn() },
  gscApi: { getStatus: vi.fn().mockResolvedValue({ configured: true, connections: [], sites: [] }), getAuthUrl: vi.fn(), disconnect: vi.fn(), sync: vi.fn(), listSites: vi.fn() },
  ga4Api: { getStatus: vi.fn().mockResolvedValue({ configured: true, properties: [] }), sync: vi.fn() },
  extensionApi: { info: vi.fn().mockResolvedValue({ version: "2.2.7", filename: "the-agency-extension-v2.2.7.zip", download_url: "/api/extension/download", released_on: null, releases: [] }) },
}))

it("does not render the scheduled-process panel or anchor for a member", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  expect(screen.getAllByText("Avisos")).not.toHaveLength(0)
  expect(screen.queryByText("Procesos programados")).not.toBeInTheDocument()
  expect(document.getElementById("scheduled-processes")).toBeNull()
  expect(document.getElementById("operational-usage")).toBeNull()
})

it("hides the inactive Pipeline shortcut while preserving its saved binding", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  expect(screen.queryByText("Ir a Pipeline")).not.toBeInTheDocument()
  expect(screen.getByText("Ir a Visión general")).toBeInTheDocument()
  expect(screen.getByText("Ir a Por aclarar")).toBeInTheDocument()
  expect(screen.getByText("Ir a Horas")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Restaurar por defecto" }))
  await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }))
  expect(usersApi.update).toHaveBeenCalledWith(12, expect.objectContaining({ preferences: expect.objectContaining({ shortcuts: expect.objectContaining({ goto_leads: "G+Y" }) }) }))
})

it("does not offer digest automation preferences that no sending flow reads", () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  expect(screen.queryByLabelText("Envío automático")).not.toBeInTheDocument()
  expect(screen.queryByText("Preferencias de digest")).not.toBeInTheDocument()
})

it("captures a sequential navigation chord and saves the executable binding", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  await userEvent.click(screen.getAllByRole("button", { name: "Editar" })[2])
  fireEvent.keyDown(window, { key: "y" })
  expect(screen.getByText("Presiona G…")).toBeInTheDocument()
  fireEvent.keyDown(window, { key: "g" })
  expect(screen.getByText("G, luego una letra…")).toBeInTheDocument()
  fireEvent.keyDown(window, { key: "y" })
  await userEvent.click(screen.getByRole("button", { name: "OK" }))
  expect(screen.getByText("G+Y")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }))
  expect(usersApi.update).toHaveBeenCalledWith(12, expect.objectContaining({ preferences: expect.objectContaining({ shortcuts: expect.objectContaining({ goto_dashboard: "G+Y" }) }) }))
})

it("rejects a chord already assigned to an active navigation action", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  await userEvent.click(screen.getAllByRole("button", { name: "Editar" })[2])
  fireEvent.keyDown(window, { key: "g" })
  fireEvent.keyDown(window, { key: "a" })
  await userEvent.click(screen.getByRole("button", { name: "OK" }))
  expect(screen.getAllByText("G+A")).toHaveLength(2)
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument()
})

it("keeps unsupported modifier combinations in edit mode", async () => {
  vi.mocked(usersApi.update).mockClear()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)
  await userEvent.click(screen.getAllByRole("button", { name: "Editar" })[0])
  fireEvent.keyDown(window, { key: "k", altKey: true })
  await userEvent.click(screen.getByRole("button", { name: "OK" }))
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument()
  expect(usersApi.update).not.toHaveBeenCalled()
})

it("names the category creation and editing controls", async () => {
  auth.isAdmin = true
  vi.mocked(categoriesApi.list).mockResolvedValue([{ id: 4, name: "SEO", default_minutes: 60, created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z" }])
  vi.mocked(holidaysApi.list).mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)

  await waitFor(() => expect(screen.getByRole("textbox", { name: "Nombre de la nueva categoría" })).toBeEnabled())
  expect(screen.getByRole("spinbutton", { name: "Minutos por defecto de la nueva categoría" })).toBeEnabled()
  expect(screen.getByRole("button", { name: "Añadir categoría" })).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Editar categoría SEO" }))
  expect(screen.getByRole("textbox", { name: "Nombre de la categoría SEO" })).toHaveValue("SEO")
  expect(screen.getByRole("spinbutton", { name: "Minutos por defecto de la categoría SEO" })).toHaveValue(60)
  expect(screen.getByRole("button", { name: "Guardar categoría SEO" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Cancelar edición de categoría SEO" })).toBeInTheDocument()
})

it("associates holiday labels and names its date and name fields", async () => {
  auth.isAdmin = true
  vi.mocked(categoriesApi.list).mockResolvedValue([])
  vi.mocked(holidaysApi.list).mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)

  await waitFor(() => expect(screen.getByRole("textbox", { name: "Nombre del nuevo festivo" })).toBeEnabled())
  expect(screen.getByLabelText("Fecha del nuevo festivo")).toBeEnabled()
  expect(screen.getByRole("combobox", { name: "Ámbito" })).toBe(screen.getByLabelText("Ámbito"))
  expect(screen.getByRole("textbox", { name: "Localidad (opcional)" })).toBe(screen.getByLabelText("Localidad (opcional)"))
})
