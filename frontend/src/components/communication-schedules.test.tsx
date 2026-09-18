import { beforeEach, it, expect, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { CommunicationSchedules } from "./communication-schedules"
const mock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock("@/lib/api", () => ({ api: mock }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 }, isAdmin: false }) }))
vi.mock("./delivery-receipts", () => ({ DeliveryReceipts: ({ sourceId }: { sourceId: number }) => <div>Recibo {sourceId}</div> }))
const policy = { kind: "meeting", enabled: false, channels: [], revision: 0, time: null, minutes_before: 30, quiet_start: null, quiet_end: null, state: "needs_review", reason: "Elige los canales" }
const catalog = { user_id: 7, timezone: "Europe/Madrid", scheduler_enabled: false, extension_min_version: "2.2.0", extension_download_url: "/extension/agency-manager.crx", policies: [policy] }
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><CommunicationSchedules /></QueryClientProvider>) }
beforeEach(() => { vi.resetAllMocks(); mock.get.mockImplementation(async (url: string) => ({ data: url.endsWith("history") ? [] : catalog })) })
it("shows opt-in, paused status and a real extension update link", async () => {
  show()
  expect(await screen.findByText(/Los envíos están pausados/)).toBeInTheDocument()
  expect(screen.getByText("Reuniones", {selector:"summary span"}).closest("details")).not.toHaveAttribute("open")
  fireEvent.click(screen.getByText("Reuniones", {selector:"summary span"}))
  expect(screen.getByRole("checkbox", { name: "Activar reuniones" })).not.toBeChecked()
  fireEvent.click(screen.getByText("Avisos en Chrome"))
  expect(screen.getByRole("link", { name: "Descargar actualización" })).toHaveAttribute("href", "/extension/agency-manager.crx")
  expect(screen.getByRole("link", {name:"Configurar Google Calendar"})).toHaveAttribute("href", "#calendar")
})
it("saves actual channels and advance notice, preserving draft after an error", async () => {
  mock.put.mockRejectedValueOnce(new Error("offline"))
  show()
  fireEvent.click(await screen.findByText("Reuniones", {selector:"summary span"}))
  fireEvent.click(screen.getByRole("checkbox", { name: "Activar reuniones" }))
  fireEvent.click(screen.getByRole("checkbox", { name: "En esta extensión de Chrome" }))
  fireEvent.change(screen.getByRole("spinbutton", { name: "Antelación (minutos)" }), { target: { value: "15" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar reuniones" }))
  await screen.findByRole("alert")
  expect(mock.put).toHaveBeenCalledWith("/communication-schedules/meeting", expect.objectContaining({ enabled: true, channels: ["extension"], minutes_before: 15, revision: 0 }))
  expect(screen.getByRole("checkbox", { name: "En esta extensión de Chrome" })).toBeChecked()
  expect(screen.getByRole("spinbutton")).toHaveValue(15)
})
it("renders occurrence receipt and failures independently from the form", async () => {
  mock.get.mockImplementation(async (url: string) => ({ data: url.endsWith("history") ? [{ id: 3, kind: "morning", channel: "team_webhook", period_start: "2026-09-18", state: "ready", reason: "Preparado", receipt: { source_id: 42 } }, { id: 4, kind: "meeting", channel: "extension", period_start: "2026-09-18", state: "blocked", reason: "Conecta Google Calendar", receipt: null }] : catalog }))
  show()
  expect(await screen.findByText("Recibo 42")).toBeInTheDocument()
  expect(screen.getByText("Conecta Google Calendar")).toBeInTheDocument()
})
it("reloads a changed revision only when the user discards their draft", async () => {
  mock.put.mockRejectedValueOnce(new Error("conflict"))
  show()
  fireEvent.click(await screen.findByText("Reuniones", {selector:"summary span"}))
  fireEvent.click(screen.getByRole("button", { name: "Guardar reuniones" }))
  await screen.findByRole("alert")
  mock.get.mockImplementation(async (url: string) => ({ data: url.endsWith("history") ? [] : { ...catalog, policies: [{ ...policy, revision: 2, minutes_before: 60 }] } }))
  fireEvent.click(screen.getByRole("button", { name: "Descartar borrador y recargar" }))
  await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(60))
})
