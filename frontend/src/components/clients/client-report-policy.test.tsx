import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { AxiosError } from "axios"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { ClientReportPolicy } from "./client-report-policy"

const api = vi.hoisted(() => ({ getPolicy: vi.fn(), updatePolicy: vi.fn(), responsibles: vi.fn() }))
const auth = vi.hoisted(() => ({ isAdmin: true, user: { id: 1 } }))
vi.mock("@/lib/report-policy-api", () => ({ reportPolicyApi: api }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => auth }))
const unconfigured = { client_id: 1, configured: false, enabled: false, cadence: "weekly", responsible_user_id: null, responsible_name: null, revision: 0 }
const configured = { ...unconfigured, configured: true, enabled: true, responsible_user_id: 2, responsible_name: "Nacho", responsible_active: true, responsible_can_prepare: true, revision: 3 }
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><ClientReportPolicy clientId={1} clientName="Acme" /></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => { vi.resetAllMocks(); auth.isAdmin = true; api.getPolicy.mockResolvedValue(unconfigured); api.responsibles.mockResolvedValue([{ id: 2, full_name: "Nacho" }]); api.updatePolicy.mockResolvedValue(configured) })
it("requires explicit opt-in and a responsible, then saves a monthly policy at revision zero", async () => {
  setup(); fireEvent.click(await screen.findByRole("button", { name: "Configurar resumen" }))
  expect(screen.getByRole("checkbox")).not.toBeChecked()
  fireEvent.click(screen.getByRole("checkbox"))
  expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Frecuencia"), { target: { value: "monthly" } })
  fireEvent.change(screen.getByLabelText("Responsable"), { target: { value: "2" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }))
  await waitFor(() => expect(api.updatePolicy).toHaveBeenCalledWith(1, { enabled: true, cadence: "monthly", responsible_user_id: 2, revision: 0 }))
})
it("keeps local edits after network failure", async () => {
  api.updatePolicy.mockRejectedValue(new Error("offline")); setup()
  fireEvent.click(await screen.findByRole("button", { name: "Configurar resumen" }))
  fireEvent.change(screen.getByLabelText("Frecuencia"), { target: { value: "monthly" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Tu selección se conserva")
  expect(screen.getByLabelText("Frecuencia")).toHaveValue("monthly")
})
it("does not overwrite a newer policy after revision conflict", async () => {
  api.getPolicy.mockResolvedValue(configured)
  const conflict = new AxiosError("conflict")
  conflict.response = { status: 409, data: { detail: { code: "policy_changed", current: { ...configured, revision: 4, cadence: "monthly" } } } } as AxiosError["response"]
  api.updatePolicy.mockRejectedValueOnce(conflict)
  setup(); fireEvent.click(await screen.findByRole("button", { name: "Cambiar frecuencia o responsable" }))
  fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }))
  await screen.findByText(/Otra persona cambió/)
  expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled()
  expect(screen.getByLabelText("Frecuencia")).toHaveValue("weekly")
  fireEvent.click(screen.getByRole("button", { name: "Cargar configuración actual" }))
  expect(screen.getByLabelText("Frecuencia")).toHaveValue("monthly")
  fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }))
  await waitFor(() => expect(api.updatePolicy).toHaveBeenLastCalledWith(1, expect.objectContaining({ revision: 4, cadence: "monthly" })))
})
it("shows responsible members the policy without querying admin-only candidates or edit controls", async () => {
  auth.isAdmin = false; api.getPolicy.mockResolvedValue(configured); setup()
  await screen.findByText("Nacho")
  expect(api.responsibles).not.toHaveBeenCalled()
  expect(screen.queryByRole("button", { name: /Cambiar frecuencia/ })).not.toBeInTheDocument()
})
