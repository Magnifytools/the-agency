import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { AxiosError } from "axios"
import { DigestExternalDelivery } from "./digest-external-delivery"
const api = vi.hoisted(() => ({ externalEvents: vi.fn(), recordExternalEvent: vi.fn() }))
vi.mock("@/lib/report-policy-api", () => ({ reportPolicyApi: api }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1 }, hasPermission: () => true }) }))
const empty = { can_record: true, events: [], external_delivery: { digest_id: 10, state: "unconfirmed", actor_name: null, confirmed_at: null }, has_newer_version: false }
function setup(props: { unsaved?: boolean } = {}) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><DigestExternalDelivery digestId={10} {...props} /></QueryClientProvider>)
}
beforeEach(() => { vi.resetAllMocks(); api.externalEvents.mockResolvedValue(empty); api.recordExternalEvent.mockResolvedValue({}) })
it("does not equate internal sharing with external delivery and requires an explicit confirmation", async () => {
  setup(); fireEvent.click(await screen.findByRole("button", { name: "Marcar como entregado al cliente" }))
  expect(screen.getByText(/Compartir en Discord interno no la confirma/)).toBeInTheDocument()
  expect(api.recordExternalEvent).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }))
  await waitFor(() => expect(api.recordExternalEvent).toHaveBeenCalledWith(10, "confirmed", expect.any(String)))
})
it("reuses the same idempotency key after an uncertain network failure", async () => {
  api.recordExternalEvent.mockRejectedValueOnce(new Error("network")); setup()
  fireEvent.click(await screen.findByRole("button", { name: "Marcar como entregado al cliente" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }))
  fireEvent.click(await screen.findByRole("button", { name: "Reintentar registro" }))
  await waitFor(() => expect(api.recordExternalEvent).toHaveBeenCalledTimes(2))
  expect(api.recordExternalEvent.mock.calls[1]).toEqual(api.recordExternalEvent.mock.calls[0])
})
it("prevents confirming a draft with unsaved text", async () => {
  setup({ unsaved: true })
  expect(await screen.findByRole("button", { name: "Marcar como entregado al cliente" })).toBeDisabled()
  expect(screen.getByText(/Guarda los cambios antes/)).toBeInTheDocument()
})
it("uses the server capability and retains revoked confirmation history", async () => {
  api.externalEvents.mockResolvedValue({ ...empty, can_record: false, has_newer_version: true, events: [{ id: 1, digest_id: 10, actor_id: 2, actor_name: "Nacho", action: "revoked", created_at: "2026-09-19T08:00:00Z" }] })
  setup(); await screen.findByText(/Hay una versión posterior/)
  expect(screen.queryByRole("button", { name: "Marcar como entregado al cliente" })).not.toBeInTheDocument()
  fireEvent.click(screen.getByText(/Historial de confirmaciones/))
  expect(screen.getByText("Confirmación retirada")).toBeInTheDocument()
})
function rejected(status: number) {
  const error = new AxiosError("rejected")
  error.response = { status, data: { detail: { code: status === 409 ? "already_confirmed" : "forbidden" } } } as AxiosError["response"]
  return error
}
it("refreshes a concurrent confirmation instead of retrying a known conflict forever", async () => {
  api.recordExternalEvent.mockRejectedValue(rejected(409)); setup()
  fireEvent.click(await screen.findByRole("button", { name: "Marcar como entregado al cliente" }))
  api.externalEvents.mockResolvedValue({ ...empty, external_delivery: { digest_id: 10, state: "confirmed", actor_name: "Nacho", confirmed_at: "2026-09-19T08:00:00Z" } })
  fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("La confirmación cambió")
  expect(await screen.findByText(/Marcado como entregado al cliente por Nacho/)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole("button", { name: "Corregir confirmación de entrega" })).not.toBeDisabled())
  expect(screen.queryByRole("button", { name: "Reintentar registro" })).not.toBeInTheDocument()
})
it("removes the action when write permission was revoked even if the previous read was allowed", async () => {
  api.recordExternalEvent.mockRejectedValue(rejected(403)); setup()
  fireEvent.click(await screen.findByRole("button", { name: "Marcar como entregado al cliente" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Ya no tienes permiso")
  expect(screen.queryByRole("button", { name: "Marcar como entregado al cliente" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Reintentar registro" })).not.toBeInTheDocument()
})
