import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, useLocation } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { DigestCohort } from "./digest-cohort"
import type { GenerationPreviewItem } from "@/lib/report-policy-api"
const mocks = vi.hoisted(() => ({ preview: vi.fn(), generate: vi.fn(), recover: vi.fn(), auth: { id: 2, admin: false, write: true } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: mocks.auth.id }, isAdmin: mocks.auth.admin, hasPermission: (_module: string, write?: boolean) => !write || mocks.auth.write }) }))
vi.mock("@/lib/api", () => ({ api: {}, digestsApi: { recoverGeneration: mocks.recover } }))
vi.mock("@/lib/report-policy-api", async () => { const actual = await vi.importActual<typeof import("@/lib/report-policy-api")>("@/lib/report-policy-api"); return { ...actual, reportPolicyApi: { generationPreview: mocks.preview, generateCohort: mocks.generate } } })
function item(id: number, overrides: Partial<GenerationPreviewItem> = {}): GenerationPreviewItem {
  return { client_id: id, client_name: `Cliente ${id}`, policy_revision: 3, cadence: "weekly", responsible_user_id: 2, responsible_name: "Responsable", period_start: "2026-09-07", period_end: "2026-09-13", eligible: true, reason: "eligible", latest_digest_id: null, version_count: 0, state: "pending", digest: {latest_digest_id: null, latest_status: null, version_count: 0}, internal_distribution: {digest_id: null, state: null, delivery_id: null, sent_at: null}, external_delivery: {digest_id: null, state: "unconfirmed", actor_name: null, confirmed_at: null}, ...overrides }
}
const response = (items: GenerationPreviewItem[], scope = "mine") => ({ as_of: "2026-09-19", scope, items, counts: {eligible: items.filter(i => i.eligible).length, excluded: items.filter(i => !i.eligible).length} })
function setup(clientId?: number, expectedPeriod?: { start: string; end: string }) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  const element = <QueryClientProvider client={client}><MemoryRouter><DigestCohort clientId={clientId} expectedPeriod={expectedPeriod} /></MemoryRouter></QueryClientProvider>
  return {...render(element), element, client}
}
function PeriodLinkHarness() {
  const { search } = useLocation()
  const params = new URLSearchParams(search)
  const clientId = Number(params.get("client_id")) || undefined
  const start = params.get("period_start") || ""
  const end = params.get("period_end") || ""
  return <DigestCohort clientId={clientId} expectedPeriod={start && end ? { start, end } : undefined} />
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mocks.auth = {id: 2, admin: false, write: true}; mocks.preview.mockResolvedValue(response([item(1), item(2, {cadence: "monthly", period_start: "2026-08-01", period_end: "2026-08-31"}), item(3, {eligible: false, reason: "policy_missing", policy_revision: null})])); mocks.generate.mockResolvedValue({results: []}); mocks.recover.mockRejectedValue({ response: { status: 404 } }) })
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
  await waitFor(() => expect(mocks.generate).toHaveBeenCalledWith({items: [{generation_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/), client_id: 2, policy_revision: 3, period_start: "2026-08-01", period_end: "2026-08-31"}], tone: "cercano"}))
})
it("recovers every version from a persisted cohort after reload", async () => {
  const operationKey = "cohort-operation-key"
  const firstKey = "cohort-generation-one"
  const secondKey = "cohort-generation-two"
  localStorage.setItem(`agency:digest-generation:2:${operationKey}`, JSON.stringify({ kind: "cohort", operation_key: operationKey, tone: "cercano", items: [
    { generation_key: firstKey, client_id: 1, policy_revision: 3, period_start: "2026-09-07", period_end: "2026-09-13" },
    { generation_key: secondKey, client_id: 2, policy_revision: 3, period_start: "2026-08-01", period_end: "2026-08-31" },
  ] }))
  mocks.recover.mockImplementation(async (key: string) => ({ id: key === firstKey ? 31 : 32 }))
  setup()
  expect(await screen.findByRole("link", { name: "Abrir versión #31" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Abrir versión #32" })).toBeInTheDocument()
  expect(mocks.recover).toHaveBeenCalledWith(firstKey)
  expect(mocks.recover).toHaveBeenCalledWith(secondKey)
  expect(localStorage.getItem(`agency:digest-generation:2:${operationKey}`)).toBeNull()
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
  await screen.findByText(/No se pudo confirmar toda la selección/)
  expect(screen.getByRole("button", {name: "Preparar selección (1)"})).toBeDisabled()
  mocks.preview.mockResolvedValue(response([existing]))
  fireEvent.click(screen.getByRole("button", {name: "Actualizar selección"}))
  await waitFor(() => expect(screen.getByRole("button", {name: "Preparar selección (0)"})).toBeDisabled())
  expect(mocks.generate).toHaveBeenCalledTimes(1)
})
it("read-only users can inspect reasons without preparing anything", async () => {
  mocks.auth.write = false
  setup()
  expect(await screen.findByText("Falta configurar la frecuencia y el responsable")).toBeInTheDocument()
  expect(screen.getByRole("heading", {name: "Resúmenes pendientes"})).toBeInTheDocument()
  expect(screen.getByRole("button", {name: "Actualizar datos"})).not.toBeDisabled()
  expect(screen.queryByRole("checkbox", {name: "Preparar Cliente 1"})).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Tono de los nuevos resúmenes")).not.toBeInTheDocument()
  expect(screen.queryByText(/seleccionados · Máximo 50/)).not.toBeInTheDocument()
  expect(screen.queryByRole("button", {name: /Preparar selección/})).not.toBeInTheDocument()
})
it("keeps a persisted cohort visible but cannot retry after write permission is revoked", async () => {
  const operationKey = "revoked-cohort-operation"
  localStorage.setItem(`agency:digest-generation:2:${operationKey}`, JSON.stringify({ kind: "cohort", operation_key: operationKey, tone: "cercano", items: [
    { generation_key: "revoked-cohort-generation", client_id: 1, policy_revision: 3, period_start: "2026-09-07", period_end: "2026-09-13" },
  ] }))
  mocks.auth.write = false
  setup()
  expect(await screen.findByText(/Hay una selección sin respuesta confirmada/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Reintentar la misma selección" })).not.toBeInTheDocument()
  expect(mocks.generate).not.toHaveBeenCalled()
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
it("prepares the exact monthly period linked by an incident", async () => {
  mocks.preview.mockResolvedValue(response([item(2, {cadence: "monthly", period_start: "2026-08-01", period_end: "2026-08-31"})]))
  setup(2, {start: "2026-08-01", end: "2026-08-31"})
  const monthly = await screen.findByRole("checkbox", {name: "Preparar Cliente 2"})
  expect(await screen.findByText(/Período del aviso: 1 ago 2026 — 31 ago 2026/)).toBeInTheDocument()
  fireEvent.click(monthly)
  fireEvent.click(screen.getByRole("button", {name: "Preparar selección (1)"}))
  await waitFor(() => expect(mocks.generate).toHaveBeenCalledWith({items: [{generation_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/), client_id: 2, policy_revision: 3, period_start: "2026-08-01", period_end: "2026-08-31"}], tone: "cercano"}))
})
it("does not prepare a newer policy period from an old incident link and recovers current periods", async () => {
  mocks.preview.mockResolvedValue(response([item(2, {cadence: "monthly", period_start: "2026-09-01", period_end: "2026-09-30"})]))
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/digests?client_id=2&period_start=2026-08-01&period_end=2026-08-31"]}><PeriodLinkHarness /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole("alert")).toHaveTextContent("La política actual usa otro período")
  expect(screen.queryByRole("checkbox", {name: "Preparar Cliente 2"})).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("link", {name: "Ver períodos actuales"}))
  expect(await screen.findByRole("checkbox", {name: "Preparar Cliente 2"})).toBeInTheDocument()
  expect(screen.queryByText(/Período del aviso:/)).not.toBeInTheDocument()
  expect(mocks.generate).not.toHaveBeenCalled()
})
