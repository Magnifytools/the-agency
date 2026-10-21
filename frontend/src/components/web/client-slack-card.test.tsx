import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { ClientSlackCard } from "./client-slack-card"

const api = vi.hoisted(() => ({ slack: vi.fn(), saveSlack: vi.fn(), removeSlack: vi.fn(), testSlack: vi.fn() }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("@/lib/api", () => ({ webApi: api }))
vi.mock("sonner", () => ({ toast }))

const HOOK = "https://hooks.slack.com/services/T0/B1/abc123"
const empty = {
  configured: false, enabled: false, active: false, revoked_at: null, channel_hint: null,
  downtime_to_slack: true, user_agent: null, updated_at: null,
}
const active = { ...empty, configured: true, enabled: true, active: true, channel_hint: "#fit-avisos", updated_at: "2026-10-21T08:00:00+00:00" }

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ClientSlackCard clientId={7} /></QueryClientProvider>)
}

beforeEach(() => vi.resetAllMocks())

it("saves a new webhook and never shows it back", async () => {
  api.slack.mockResolvedValue(empty)
  api.saveSlack.mockResolvedValue(active)
  setup()
  expect(await screen.findByRole("status")).toHaveTextContent("Sin configurar")
  expect(screen.queryByRole("button", { name: /Enviar prueba/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Webhook de Slack"), { target: { value: HOOK } })
  fireEvent.change(screen.getByLabelText(/Canal/), { target: { value: "fit-avisos" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.saveSlack).toHaveBeenCalledWith(7, {
    webhook_url: HOOK, channel_hint: "fit-avisos", enabled: true, downtime_to_slack: true, user_agent: null,
  }))
  expect(await screen.findByRole("status")).toHaveTextContent("Activo: las caídas y recuperaciones")
  expect(screen.getByLabelText("Webhook de Slack")).toHaveValue("")
  expect(screen.queryByDisplayValue(HOOK)).not.toBeInTheDocument()
})

it("keeps the stored webhook when only other fields change", async () => {
  api.slack.mockResolvedValue(active)
  api.saveSlack.mockResolvedValue({ ...active, enabled: false, active: false })
  setup()
  await screen.findByText(/Canal: #fit-avisos/)
  fireEvent.click(screen.getByLabelText("Enviar avisos a este canal"))
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.saveSlack).toHaveBeenCalled())
  expect(api.saveSlack.mock.calls[0][1]).not.toHaveProperty("webhook_url")
  expect(await screen.findByRole("status")).toHaveTextContent("Configurado pero apagado")
})

it("shows a revoked webhook and the test result", async () => {
  api.slack.mockResolvedValue({ ...active, enabled: false, active: false, revoked_at: "2026-10-21T09:00:00+00:00" })
  api.testSlack.mockResolvedValue({ ok: false, revoked: true, error: "El webhook ya no existe en Slack." })
  setup()
  expect(await screen.findByRole("status")).toHaveTextContent(/Revocado el .* Pega uno nuevo/)
  fireEvent.click(screen.getByRole("button", { name: /Enviar prueba/ }))
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("El webhook ya no existe en Slack."))
})

it("removing the webhook asks first", async () => {
  api.slack.mockResolvedValue(active)
  api.removeSlack.mockResolvedValue(empty)
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Quitar webhook" }))
  expect(api.removeSlack).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Quitar" }))
  await waitFor(() => expect(api.removeSlack).toHaveBeenCalledWith(7))
})
