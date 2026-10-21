import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { DigestMonthlyCycle } from "./digest-monthly-cycle"
import type { GenerationPreviewItem } from "@/lib/report-policy-api"

const mocks = vi.hoisted(() => ({ preview: vi.fn(), generate: vi.fn(), auth: { id: 2, admin: true, write: true } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: mocks.auth.id }, isAdmin: mocks.auth.admin, hasPermission: (_module: string, write?: boolean) => !write || mocks.auth.write }) }))
vi.mock("@/lib/api", () => ({ api: {} }))
vi.mock("@/lib/report-policy-api", async () => { const actual = await vi.importActual<typeof import("@/lib/report-policy-api")>("@/lib/report-policy-api"); return { ...actual, reportPolicyApi: { generationPreview: mocks.preview, generateCohort: mocks.generate } } })

const none = { digest: { latest_digest_id: null, latest_status: null, version_count: 0 } }
function item(id: number, name: string, overrides: Partial<GenerationPreviewItem> = {}): GenerationPreviewItem {
  return { client_id: id, client_name: name, policy_revision: 4, cadence: "monthly", responsible_user_id: 2, responsible_name: "Nacho", period_start: "2026-09-01", period_end: "2026-09-30", eligible: true, reason: "eligible", latest_digest_id: null, version_count: 0, state: "missing", ...none, internal_distribution: { digest_id: null, state: null, delivery_id: null, sent_at: null }, external_delivery: { digest_id: null, state: "unconfirmed", actor_name: null, confirmed_at: null }, ...overrides }
}
const prepared = { eligible: false, reason: "already_exists" as const, state: "draft", digest: { latest_digest_id: 40, latest_status: "sent" as const, version_count: 1 } }
const items = [
  item(1, "Sage", { ...prepared, state: "externally_delivered", digest: { latest_digest_id: 41, latest_status: "draft", version_count: 1 }, external_delivery: { digest_id: 41, state: "confirmed", actor_name: "David", confirmed_at: "2026-10-02T09:00:00Z" } }),
  item(2, "Fit Generation", prepared),
  item(3, "Acme", {}),
  item(4, "Sin config", { eligible: false, reason: "policy_missing", policy_revision: null, cadence: null, state: "not_configured" }),
  item(5, "Semanal", { cadence: "weekly", period_start: "2026-10-05", period_end: "2026-10-11" }),
  item(8, "Desactivada", { eligible: false, reason: "policy_disabled", policy_revision: 4, cadence: null, period_start: null, period_end: null, state: "disabled" }),
  // Con las dos cadencias, la fila semanal no entra en el ciclo mensual.
  item(3, "Acme", { cadence: "weekly", period_start: "2026-10-12", period_end: "2026-10-18" }),
  item(6, "Interno", { eligible: false, reason: "internal_client" }),
  item(7, "Inactivo", { eligible: false, reason: "client_inactive" }),
]

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/digests"]}><Routes>
    <Route path="/digests" element={<DigestMonthlyCycle />} />
    <Route path="/digests/:id/edit" element={<p>Editor abierto</p>} />
  </Routes></MemoryRouter></QueryClientProvider>)
}
const row = async (name: string) => (await screen.findByText(name)).closest("li") as HTMLElement

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); mocks.auth = { id: 2, admin: true, write: true }
  mocks.preview.mockResolvedValue({ as_of: "2026-10-19", scope: "team", items, counts: { eligible: 1, excluded: 6 } })
})

it("lists active external clients with the monthly report on, problems first", async () => {
  setup()
  expect(await screen.findByText(/Informe de septiembre de 2026/)).toBeInTheDocument()
  expect(mocks.preview).toHaveBeenCalledWith("team")
  const names = screen.getAllByRole("listitem").map(li => li.querySelector("p")?.textContent)
  // Sin política, apagada o sólo semanal: fuera del ciclo mensual.
  expect(names).toEqual(["Acme", "Fit Generation", "Sage"])
  expect(screen.getByLabelText("Recuento del ciclo mensual")).toHaveTextContent("1 de 3 entregados · 1 sin preparar · 1 sin entregar")
  expect(within(await row("Acme")).getByText("Pendiente de generar")).toBeInTheDocument()
  const fit = await row("Fit Generation")
  // Legacy "sent" status is not proof of delivery.
  expect(within(fit).getByText("Borrador sin entregar")).toBeInTheDocument()
  expect(within(fit).getByText(/sistema antiguo/)).toBeInTheDocument()
  expect(within(fit).getByRole("link", { name: "Abrir resumen de Fit Generation" })).toHaveAttribute("href", "/digests/40/edit")
  const sage = await row("Sage")
  expect(within(sage).getByText("Entregado")).toBeInTheDocument()
  expect(within(sage).getByText(/Entregado por David el 2 oct/)).toBeInTheDocument()
  for (const name of ["Sin config", "Semanal", "Desactivada"]) expect(screen.queryByText(name)).not.toBeInTheDocument()
  expect(screen.queryByText("Interno")).not.toBeInTheDocument()
  expect(screen.queryByText("Inactivo")).not.toBeInTheDocument()
})

it("says so when no client has the monthly report on", async () => {
  mocks.preview.mockResolvedValue({ as_of: "2026-10-19", scope: "team", items: [items[3], items[4]], counts: { eligible: 1, excluded: 1 } })
  setup()
  expect(await screen.findByText("Ningún cliente tiene activado el informe mensual.")).toBeInTheDocument()
})

it("generates the missing month and opens the new version", async () => {
  mocks.generate.mockResolvedValue({ results: [{ client_id: 3, outcome: "generated", digest_id: 77 }] })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Generar resumen de Acme" }))
  expect(await screen.findByText("Editor abierto")).toBeInTheDocument()
  expect(mocks.generate).toHaveBeenCalledWith({ tone: "cercano", items: [{ generation_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/), client_id: 3, policy_revision: 4, period_start: "2026-09-01", period_end: "2026-09-30" }] })
  expect(Object.keys(localStorage)).toEqual([])
})

it("explains a skipped generation and keeps an unconfirmed one recoverable", async () => {
  mocks.generate.mockResolvedValueOnce({ results: [{ client_id: 3, outcome: "skipped", reason: "concurrent_generation" }] })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Generar resumen de Acme" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Otra persona lo está preparando ahora.")

  mocks.generate.mockRejectedValueOnce(new Error("Network Error"))
  fireEvent.click(screen.getByRole("button", { name: "Generar resumen de Acme" }))
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Recarga la página"))
  expect(Object.keys(localStorage)).toHaveLength(1)
})

it("members see only their clients and cannot generate without write access", async () => {
  mocks.auth = { id: 2, admin: false, write: false }
  setup()
  expect(await screen.findByText(/a tu cargo/)).toBeInTheDocument()
  expect(mocks.preview).toHaveBeenCalledWith("mine")
  expect(screen.queryByRole("button", { name: /Generar/ })).not.toBeInTheDocument()
})
