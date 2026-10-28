import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { CredentialOffboardingDialog } from "./credential-offboarding-dialog"

const api = vi.hoisted(() => ({ exposure: vi.fn(), revokeShares: vi.fn() }))
vi.mock("@/lib/credentials-api", () => ({ credentialsApi: api }))
vi.mock("@/lib/api", () => ({
  usersApi: { listAll: vi.fn().mockResolvedValue([
    { id: 2, full_name: "Nacho", is_active: false }, { id: 1, full_name: "David", is_active: true },
  ]) },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const rows = [
  { id: 7, name: "WordPress Fit", url: null, client_name: "Fit", last_seen_at: "2026-10-20T08:00:00Z", times_seen: 2,
    shared_with_them: true, created_by_them: false, secret_changed_at: "2026-09-01T08:00:00Z", needs_rotation: true },
  { id: 8, name: "Google Ads", url: null, client_name: null, last_seen_at: null, times_seen: 0,
    shared_with_them: true, created_by_them: false, secret_changed_at: "2026-09-01T08:00:00Z", needs_rotation: false },
]

beforeEach(() => {
  api.exposure.mockReset().mockResolvedValue(rows)
  api.revokeShares.mockReset().mockResolvedValue({ removed: 2 })
})

it("lists what someone saw, flags what to rotate and removes their shares", async () => {
  const onEdit = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CredentialOffboardingDialog onOpenChange={vi.fn()} onEdit={onEdit} />
    </QueryClientProvider>,
  )
  const select = screen.getByLabelText("Persona")
  await screen.findByRole("option", { name: "Nacho (desactivado)" })
  fireEvent.change(select, { target: { value: "2" } })
  expect(await screen.findByText(/cambia la contraseña/)).toBeInTheDocument()
  expect(screen.getByText(/No la llegó a abrir/)).toBeInTheDocument()
  expect(api.exposure).toHaveBeenCalledWith(2)

  fireEvent.click(screen.getByRole("button", { name: "Cambiar" }))
  expect(onEdit).toHaveBeenCalledWith(7)

  fireEvent.click(screen.getByRole("button", { name: "Quitarle los 2 compartidos" }))
  fireEvent.click(await screen.findByRole("button", { name: "Quitar" }))
  await waitFor(() => expect(api.revokeShares).toHaveBeenCalledWith(2))
})
