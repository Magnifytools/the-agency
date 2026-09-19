import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { DigestCohort } from "./digest-cohort"
import type { GenerationPreviewItem } from "@/lib/report-policy-api"
const mocks = vi.hoisted(() => ({ preview: vi.fn(), generate: vi.fn(), auth: { id: 2, admin: false, write: true } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: mocks.auth.id }, isAdmin: mocks.auth.admin, hasPermission: (_module: string, write?: boolean) => !write || mocks.auth.write }) }))
vi.mock("@/lib/report-policy-api", async () => { const actual = await vi.importActual<typeof import("@/lib/report-policy-api")>("@/lib/report-policy-api"); return { ...actual, reportPolicyApi: { generationPreview: mocks.preview, generateCohort: mocks.generate } } })
function item(id: number, overrides: Partial<GenerationPreviewItem> = {}): GenerationPreviewItem {
  return { client_id: id, client_name: `Cliente ${id}`, policy_revision: 3, cadence: "weekly", responsible_user_id: 2, responsible_name: "Responsable", period_start: "2026-09-07", period_end: "2026-09-13", eligible: true, reason: "eligible", latest_digest_id: null, version_count: 0, state: "pending", digest: {latest_digest_id: null, latest_status: null, version_count: 0}, internal_distribution: {digest_id: null, state: null, delivery_id: null, sent_at: null}, external_delivery: {digest_id: null, state: "unconfirmed", actor_name: null, confirmed_at: null}, ...overrides }
}
const response = (items: GenerationPreviewItem[], scope = "mine") => ({ as_of: "2026-09-19", scope, items, counts: {eligible: items.filter(i => i.eligible).length, excluded: items.filter(i => !i.eligible).length} })
function setup(clientId?: number) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  const element = <QueryClientProvider client={client}><MemoryRouter><DigestCohort clientId={clientId} /></MemoryRouter></QueryClientProvider>
  return {...render(element), element, client}
}
beforeEach(() => { vi.clearAllMocks(); mocks.auth = {id: 2, admin: false, write: true}; mocks.preview.mockResolvedValue(response([item(1), item(2, {cadence: "monthly", period_start: "2026-08-01", period_end: "2026-08-31"}), item(3, {eligible: false, reason: "policy_missing", policy_revision: null})])); mocks.generate.mockResolvedValue({results: []}) })
it("starts unselected, explains exclusions, and sends only selected monthly period/revision", async () => {
  setup()
  const monthly = await screen.findByRole("checkbox", {name: "Preparar Cliente 2"})
  expect(monthly).not.toBeChecked()
  expect(screen.getByRole("button", {name: "Preparar selección (0)"})).toBeDisabled()
  expect(screen.getByRole("checkbox", {name: "Preparar Cliente 3"})).toBeDisabled()
  expect(screen.getByText("Falta configurar la frecuencia y el responsable")).toBeInTheDocument()
  expect(screen.queryByLabelText("Responsabilidad")).not.toBeInTheDocument()
  fireEvent.click(monthly)
  fireEvent.click(screen.getByRole("button", {name: "Preparar selección (1)"}))
  await waitFor(() => expect(mocks.generate).toHaveBeenCalledWith({items: [{client_id: 2, policy_revision: 3, period_start: "2026-08-01", period_end: "2026-08-31"}], tone: "cercano"}))
})
it("admin can choose team, and changing scope discards the old selection", async () => {
  mocks.auth.admin = true
  setup()
  fireEvent.click(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"}))
  fireEvent.change(screen.getByLabelText("Responsabilidad"), {target: {value: "team"}})
  await waitFor(() => expect(mocks.preview).toHaveBeenCalledWith("team"))
  expect(screen.getByRole("button", {name: "Preparar selección (0)"})).toBeDisabled()
})
it("shows independent generated/skipped/failed results and links exact versions", async () => {
  mocks.preview.mockResolvedValue(response([item(1), item(2), item(3)]))
  mocks.generate.mockResolvedValue({results: [{client_id: 1, outcome: "generated", digest_id: 20}, {client_id: 2, outcome: "skipped", reason: "already_exists", digest_id: 19}, {client_id: 3, outcome: "failed", reason: "generation_failed"}]})
  setup()
  await screen.findByRole("checkbox", {name: "Preparar Cliente 1"})
  for (const checkbox of screen.getAllByRole("checkbox")) fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole("button", {name: "Preparar selección (3)"}))
  const result = await screen.findByRole("region", {name: "Resultado de la preparación"})
  expect(result).toHaveTextContent("Cliente 1 · Generado")
  expect(result).toHaveTextContent("Cliente 2 · Omitido")
  expect(result).toHaveTextContent("Cliente 3 · Fallido")
  expect(within(result).getByRole("link", {name: "Abrir versión #20"})).toHaveAttribute("href", "/digests/20/edit")
})
it("network uncertainty requires a fresh preview before another attempt", async () => {
  mocks.generate.mockRejectedValue(new Error("Timeout"))
  const existing = item(1, {eligible: false, reason: "already_exists"})
  setup()
  fireEvent.click(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"}))
  fireEvent.click(screen.getByRole("button", {name: "Preparar selección (1)"}))
  await screen.findByText(/Puede haber versiones ya guardadas/)
  expect(screen.getByRole("button", {name: "Preparar selección (1)"})).toBeDisabled()
  mocks.preview.mockResolvedValue(response([existing]))
  fireEvent.click(screen.getByRole("button", {name: "Actualizar selección"}))
  await waitFor(() => expect(screen.getByRole("button", {name: "Preparar selección (0)"})).toBeDisabled())
  expect(mocks.generate).toHaveBeenCalledTimes(1)
})
it("read-only users can inspect reasons without preparing anything", async () => {
  mocks.auth.write = false
  setup()
  expect(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"})).toBeDisabled()
  expect(screen.queryByRole("button", {name: /Preparar selección/})).not.toBeInTheDocument()
})
it("preview failure remains visible and retry recovers", async () => {
  mocks.preview.mockRejectedValueOnce(new Error("offline"))
  setup()
  fireEvent.click(await screen.findByRole("button", {name: "Reintentar consulta"}))
  await screen.findByRole("checkbox", {name: "Preparar Cliente 1"})
})
it("revision changes revoke selection and refresh never invents new selections", async () => {
  setup()
  fireEvent.click(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"}))
  mocks.preview.mockResolvedValue(response([item(1, {policy_revision: 4})]))
  fireEvent.click(screen.getByRole("button", {name: "Actualizar selección"}))
  await waitFor(() => expect(screen.getByRole("checkbox", {name: "Preparar Cliente 1"})).not.toBeChecked())
})
it("double-click while pending produces one request and old identity completion stays hidden", async () => {
  let resolve!: (value: unknown) => void
  mocks.generate.mockReturnValue(new Promise(done => {resolve = done}))
  const view = setup()
  fireEvent.click(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"}))
  const button = screen.getByRole("button", {name: "Preparar selección (1)"})
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(mocks.generate).toHaveBeenCalledTimes(1))
  mocks.auth.id = 4
  view.rerender(view.element)
  // Force a new provider child render as an actual authentication context would.
  view.rerender(<QueryClientProvider client={view.client}><MemoryRouter><DigestCohort /></MemoryRouter></QueryClientProvider>)
  await act(async () => { resolve({results: [{client_id: 1, outcome: "generated", digest_id: 100}]}) })
  expect(screen.queryByText("Abrir versión #100")).not.toBeInTheDocument()
})

it("filters the cohort with the page client and drops selection on a new filter", async () => {
  const view = setup(1)
  fireEvent.click(await screen.findByRole("checkbox", {name: "Preparar Cliente 1"}))
  expect(screen.queryByRole("checkbox", {name: "Preparar Cliente 2"})).not.toBeInTheDocument()
  expect(screen.getByText(/1 pendientes · 0 fuera/)).toBeInTheDocument()
  view.rerender(<QueryClientProvider client={view.client}><MemoryRouter><DigestCohort clientId={2} /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole("checkbox", {name: "Preparar Cliente 2"})).not.toBeChecked()
  expect(screen.getByRole("button", {name: "Preparar selección (0)"})).toBeDisabled()
})
it("labels an older confirmed delivery without claiming the latest version was delivered", async () => {
  mocks.preview.mockResolvedValue(response([item(1, {state: "newer_version_unconfirmed", eligible: false, reason: "already_exists", digest: {latest_digest_id: 20, latest_status: "draft", version_count: 2}, external_delivery: {digest_id: 19, state: "confirmed", actor_name: "Responsible", confirmed_at: "2026-09-19T10:00:00Z"}})]))
  setup()
  expect(await screen.findByText("La última versión aún no tiene entrega confirmada.")).toBeInTheDocument()
  expect(screen.getByText(/Confirmada manualmente por Responsible · Versión #19/)).toBeInTheDocument()
  expect(screen.getByRole("link", {name: "Ver versión #20"})).toHaveAttribute("href", "/digests/20/edit")
})
